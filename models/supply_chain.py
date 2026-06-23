"""
FoodSafe India — Model 2: Supply Chain Propagation
Directed graph (NetworkX DAG) + Bayesian updating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

logger = logging.getLogger("foodsafe.models.supply_chain")

PRIOR_WEIGHT  = 0.70   # weight for propagated prior
ACTUAL_WEIGHT = 0.30   # weight for actual test data
MAX_CONF_NO_TESTS = 0.60  # confidence cap when no actual tests exist


@dataclass
class NodeData:
    node_id:     int
    node_type:   str
    name:        str
    district_id: Optional[int]
    commodity_id: Optional[int]
    # Measured contamination (from enforcement_records), None if no tests
    measured_ppb: Optional[float] = None
    n_tests:      int = 0
    # Estimated contamination (from propagation)
    estimated_ppb: Optional[float] = None
    confidence:    float = 0.0
    source:        str = "none"   # "measured" | "propagated" | "mixed"


class SupplyChainGraph:
    """
    Builds a NetworkX DAG from supply_chain_nodes + supply_chain_edges,
    then propagates contamination estimates from source nodes to derived nodes.
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()

    # --------------------------------------------------------
    # LOAD FROM DB
    # --------------------------------------------------------

    def load_from_db(self, conn, commodity_id: Optional[int] = None):
        """Load all nodes and edges for a commodity (or all if None)."""
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Nodes
            if commodity_id:
                cur.execute("""
                    SELECT id, node_type, name, district_id, commodity_id
                    FROM supply_chain_nodes WHERE commodity_id = %s
                """, (commodity_id,))
            else:
                cur.execute("SELECT id, node_type, name, district_id, commodity_id FROM supply_chain_nodes")

            for row in cur.fetchall():
                self.graph.add_node(row["id"], **NodeData(
                    node_id     = row["id"],
                    node_type   = row["node_type"],
                    name        = row["name"],
                    district_id = row["district_id"],
                    commodity_id= row["commodity_id"],
                ).__dict__)

            # Edges
            cur.execute("""
                SELECT source_node_id, target_node_id, process_type, retention_factor, link_confidence
                FROM supply_chain_edges
            """)
            for row in cur.fetchall():
                if row["source_node_id"] in self.graph and row["target_node_id"] in self.graph:
                    self.graph.add_edge(
                        row["source_node_id"],
                        row["target_node_id"],
                        process_type     = row["process_type"],
                        retention_factor = float(row["retention_factor"] or 1.0),
                        link_confidence  = float(row["link_confidence"] or 0.5),
                    )

        logger.info("Loaded %d nodes, %d edges", self.graph.number_of_nodes(), self.graph.number_of_edges())

    def attach_measurements(self, conn, commodity_id: int):
        """
        Pull actual enforcement measurements into node data.
        Uses average PPB from the last 12 months, usable records only.
        """
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    scn.id AS node_id,
                    AVG(er.raw_value_ppb) AS avg_ppb,
                    COUNT(*) AS n_tests
                FROM supply_chain_nodes scn
                JOIN enforcement_records er
                    ON er.district_id = scn.district_id
                    AND er.commodity_id = scn.commodity_id
                WHERE
                    scn.commodity_id = %s
                    AND er.confidence_score >= 0.75
                    AND er.is_duplicate = FALSE
                    AND er.test_date >= NOW() - INTERVAL '12 months'
                GROUP BY scn.id
            """, (commodity_id,))

            for row in cur.fetchall():
                nid = row["node_id"]
                if nid in self.graph.nodes:
                    self.graph.nodes[nid]["measured_ppb"] = float(row["avg_ppb"])
                    self.graph.nodes[nid]["n_tests"]       = row["n_tests"]
                    self.graph.nodes[nid]["source"]        = "measured"

    # --------------------------------------------------------
    # PROPAGATION
    # --------------------------------------------------------

    def propagate(self):
        """
        Topological traversal: propagate contamination estimates
        from source nodes (farms/mandis) to derived nodes (processors/brands).
        """
        if not nx.is_directed_acyclic_graph(self.graph):
            logger.error("Supply chain graph has cycles — cannot propagate")
            return

        for node_id in nx.topological_sort(self.graph):
            node = self.graph.nodes[node_id]

            if node["measured_ppb"] is not None and node["n_tests"] > 0:
                # We have direct measurements
                node["estimated_ppb"] = node["measured_ppb"]
                node["confidence"]    = min(0.90, 0.60 + 0.03 * min(10, node["n_tests"]))
                node["source"]        = "measured"
                continue

            # Collect incoming propagated estimates
            predecessors = list(self.graph.predecessors(node_id))
            if not predecessors:
                # Source node with no measurements
                node["confidence"] = 0.0
                continue

            propagated_ppbs  = []
            propagated_confs = []

            for pred_id in predecessors:
                pred = self.graph.nodes[pred_id]
                edge = self.graph.edges[pred_id, node_id]

                if pred["estimated_ppb"] is None:
                    continue

                retention = edge["retention_factor"]
                link_conf = edge["link_confidence"]

                propagated_ppb  = pred["estimated_ppb"] * retention
                combined_conf   = pred["confidence"] * link_conf
                propagated_ppbs.append(propagated_ppb)
                propagated_confs.append(combined_conf)

            if not propagated_ppbs:
                node["confidence"] = 0.0
                continue

            # Weighted average by confidence
            total_conf = sum(propagated_confs)
            if total_conf == 0:
                node["confidence"] = 0.0
                continue

            prior_ppb  = sum(p * c for p, c in zip(propagated_ppbs, propagated_confs)) / total_conf
            prior_conf = total_conf / len(propagated_confs)

            # Bayesian update if actual measurements exist
            if node["measured_ppb"] is not None:
                actual_weight  = min(ACTUAL_WEIGHT, 0.03 * node["n_tests"])
                prior_w        = 1.0 - actual_weight
                posterior_ppb  = prior_w * prior_ppb + actual_weight * node["measured_ppb"]
                posterior_conf = min(0.90, prior_conf + 0.05 * node["n_tests"])
                node["estimated_ppb"] = posterior_ppb
                node["confidence"]    = posterior_conf
                node["source"]        = "mixed"
            else:
                node["estimated_ppb"] = prior_ppb
                node["confidence"]    = min(MAX_CONF_NO_TESTS, prior_conf)
                node["source"]        = "propagated"

        logger.info("Propagation complete")

    # --------------------------------------------------------
    # QUERY
    # --------------------------------------------------------

    def get_estimate(self, node_id: int) -> Optional[NodeData]:
        if node_id not in self.graph.nodes:
            return None
        data = self.graph.nodes[node_id]
        return NodeData(**{k: data.get(k) for k in NodeData.__dataclass_fields__})

    def get_brand_estimate(self, brand_node_id: int) -> dict:
        """
        Return estimate + inference metadata for a brand node.
        This is what the API serves.
        """
        nd = self.get_estimate(brand_node_id)
        if nd is None:
            return {"error": "Node not found"}

        return {
            "estimated_ppb": nd.estimated_ppb,
            "confidence":    nd.confidence,
            "inference_type": (
                "direct_test"       if nd.source == "measured"   else
                "propagated"        if nd.source == "propagated" else
                "mixed"             if nd.source == "mixed"      else
                "insufficient_data"
            ),
            "label": (
                "Tested: based on direct enforcement records"
                if nd.source == "measured"
                else "Inferred from supply chain data, no direct test on this product"
            ),
        }

    def subgraph_for_display(self, node_id: int, depth: int = 3) -> list[dict]:
        """Return upstream subgraph for frontend animated diagram."""
        ancestors = nx.ancestors(self.graph, node_id)
        sub_nodes = list(ancestors) + [node_id]
        edges_out = []
        for src, tgt in self.graph.edges():
            if src in sub_nodes and tgt in sub_nodes:
                src_data = self.graph.nodes[src]
                tgt_data = self.graph.nodes[tgt]
                edges_out.append({
                    "source":           src,
                    "source_name":      src_data.get("name"),
                    "source_type":      src_data.get("node_type"),
                    "source_risk_ppb":  src_data.get("estimated_ppb"),
                    "target":           tgt,
                    "target_name":      tgt_data.get("name"),
                    "retention_factor": self.graph.edges[src, tgt].get("retention_factor"),
                })
        return edges_out
