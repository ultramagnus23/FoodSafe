"""
EU RASFF Window -> notifications about food of Indian origin, with the measured
hazard values.

The European Commission's Rapid Alert System for Food and Feed publishes, through
an unauthenticated public API behind its RASFF Window site, every notification an
EU/EEA authority raises about a food or feed consignment — including the hazard
found, the analytical result, the legal limit, the product, the action taken and
the country of origin. Filtered to origin = India this is the one source in the
project with real *measured concentrations against legal limits* for Indian food
(2019 -> today, ~2,200 notifications), published by an official regulator.

What it is NOT (also stored in api/source_registry.py, shown next to the data):
consignments checked at the EU border or on the EU market, chosen by risk-based
targeting — a record of what EU authorities found in Indian exports, not a sample
of food eaten in India and not a prevalence estimate.

Two endpoints (no key, no captcha):
  POST .../backend/public/notification/search/consolidated/   list, filterable
       by origin country. India's id in the filter is 5118 (its
       countryNetworkOrganizationId; the ISO code is rejected by the API).
  GET  .../backend/public/notification/view/id/{id}/en/       one notification:
       hazards, product, measures. Some notifications have no public detail
       (HTTP 401/404); those keep their list-level fields and `has_detail=false`.

Correct-by-construction rules, like the Parliament parsers:
  * a record is kept only if India is among its origin countries (the list
    filter is trusted but checked);
  * numbers are parsed only when unambiguous ('0.26', '5,0', '42±13' -> 42);
    censored values ('>150000') keep their qualifier; ranges, 'nd', text and
    anything else become NULL rather than a guess;
  * the exceedance ratio is computed only when the result and the limit are in
    the same, comparable unit;
  * detail pages carry a named contact person at the notifying authority; that
    is personal data, never read or stored.

Bounded per run (`limit` = max detail fetches) so the first backfill spreads
over a few daily runs instead of one long one; the list (23 requests) is fetched
every run and only new notifications are fetched in detail.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.rasff")

BASE = "https://webgate.ec.europa.eu/rasff-window/backend/public"
SEARCH_URL = f"{BASE}/notification/search/consolidated/"
DETAIL_URL = BASE + "/notification/view/id/{id}/en/"
USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
INDIA_NETWORK_ID = 5118
INDIA_ISO = "IN"
PAGE_SIZE = 100
DETAIL_WORKERS = 4
DEFAULT_DETAIL_LIMIT = 400
RECENT_DAYS = 60      # notifications this recent are re-tried for a missing detail

_REPLACEMENT = "\ufffd"   # the API returns U+FFFD where '±' / 'µ' should be


class RasffUnavailable(RuntimeError):
    """The RASFF list endpoint could not be read: an outage, not 'no notifications'."""


# ---------------------------------------------------------------- pure parsing

def parse_date(s: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime((s or "").strip()[:10], "%d-%m-%Y").date()
    except ValueError:
        return None


_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_UNCERTAINTY_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:±|Â±|\+/-|\+-|" + _REPLACEMENT + r")\s*\d+(?:[.,]\d+)?$")
_QUALIFIER_RE = re.compile(r"^([<>]=?)\s*(\d+(?:[.,]\d+)?)$")


def _to_decimal(raw: str) -> Optional[Decimal]:
    # '1,000' could be one thousand or 1.000: with a non-zero integer part and
    # exactly three digits after the comma the notifying authority's convention
    # is unknowable, so it is refused rather than guessed. '0,125' and '5,0' are
    # unambiguous decimals.
    if re.fullmatch(r"[1-9]\d*,\d{3}", raw):
        return None
    try:
        v = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return v if v.is_finite() and v >= 0 else None


def parse_result(raw: Optional[str]) -> tuple[Optional[Decimal], str]:
    """(value, qualifier) with qualifier in {'=', '<', '>'}; (None, '') if the
    text is not a single unambiguous number. '42±13' is 42 (the uncertainty is
    dropped, not folded in), '5,0' is 5.0 (decimal comma), '>150000' keeps its '>'."""
    t = (raw or "").strip()
    if not t:
        return None, ""
    if _NUMBER_RE.match(t):
        v = _to_decimal(t)
        return (v, "=") if v is not None else (None, "")
    m = _UNCERTAINTY_RE.match(t)
    if m:
        return _to_decimal(m.group(1)), "="
    m = _QUALIFIER_RE.match(t)
    if m:
        v = _to_decimal(m.group(2))
        return (v, m.group(1)[0]) if v is not None else (None, "")
    return None, ""


COMPARABLE_UNITS = {"mg/kg", "ug/kg", "mg/l", "ug/l", "%"}


def normalise_unit(u: Optional[str]) -> Optional[str]:
    """'mg/kg - ppm' -> 'mg/kg'; 'U+FFFDg/kg - ppb' (a mangled µ) -> 'ug/kg'. Anything
    else is kept as printed so it is visible, and simply never compared."""
    t = (u or "").strip()
    if not t:
        return None
    low = t.lower()
    if "ppb" in low or re.match(rf"^[µu{_REPLACEMENT}Âμ]{{1,2}}g/(kg|l)\b", low):
        return "ug/l" if "/l" in low else "ug/kg"
    if "ppm" in low and "mg/kg" in low:
        return "mg/kg"
    if low.startswith("mg/kg") and "dry" not in low:
        return "mg/kg"
    if low.startswith("mg/l"):
        return "mg/l"
    return t


def compare_to_limit(value: Optional[Decimal], qualifier: str, unit: Optional[str],
                     limit: Optional[Decimal], limit_unit: Optional[str]) -> tuple[Optional[Decimal], Optional[bool]]:
    """(exceedance_ratio, exceeds_limit). The ratio needs an exact result and the
    same comparable unit on both sides; a censored result can still say 'exceeds'
    when it is at/above the limit ('>150000' vs 100000) or 'does not' ('<0.01' vs 0.05)."""
    if value is None or limit is None or not unit or unit != limit_unit or unit not in COMPARABLE_UNITS:
        return None, None
    if limit == 0:      # zero tolerance ('not permitted'): any detected amount exceeds it; no meaningful ratio
        return None, (value > 0) if qualifier == "=" else None
    if qualifier == "=":
        return (value / limit).quantize(Decimal("0.0001")), value > limit
    if qualifier == ">":
        return None, True if value >= limit else None
    if qualifier == "<":
        return None, False if value <= limit else None
    return None, None


def _hazard_row(h: dict) -> Optional[dict]:
    name = (h.get("name") or "").strip()
    if not name:
        return None
    category = ((h.get("hazardCategory") or {}).get("description") or "").strip() or None
    # "Aflatoxin B1  - mycotoxins" -> "Aflatoxin B1"
    label = re.sub(r"\s+-\s+" + re.escape(category or "") + r"\s*$", "", name).strip() if category else name
    value, qualifier = parse_result(h.get("analyticalResult"))
    unit = normalise_unit(h.get("unit"))
    limit, _ = parse_result(h.get("maxPermittedLvlQuantities"))
    limit_unit = normalise_unit(h.get("maxPermittedLvlUnit"))
    ratio, exceeds = compare_to_limit(value, qualifier, unit, limit, limit_unit)
    return {
        "hazard": label, "hazard_category": category,
        "result_raw": (h.get("analyticalResult") or "").strip() or None,
        "result_value": value, "result_qualifier": qualifier or None, "result_unit": unit,
        "limit_value": limit, "limit_unit": limit_unit,
        "exceedance_ratio": ratio, "exceeds_limit": exceeds,
        "sampling_date": parse_date(h.get("samplingDate")),
    }


def parse_notification(listed: dict, detail: Optional[dict]) -> Optional[dict]:
    """One row for rasff_notifications (+ hazards). None if the record is not
    India-origin or is malformed — the caller counts these, never inserts them."""
    try:
        nid = int(listed["notifId"])
    except (KeyError, TypeError, ValueError):
        return None
    origins = sorted({(o or {}).get("isoCode") for o in listed.get("originCountries") or [] if (o or {}).get("isoCode")})
    if INDIA_ISO not in origins:
        return None
    validated = parse_date(listed.get("ecValidationDate"))
    if validated is None:
        return None

    def desc(o):
        return ((o or {}).get("description") or "").strip() or None

    row = {
        "notif_id": nid,
        "reference": (listed.get("reference") or "").strip() or None,
        "validation_date": validated,
        "subject": (listed.get("subject") or "").strip() or None,
        "notifying_country": ((listed.get("notifyingCountry") or {}).get("isoCode")),
        "origin_countries": origins,
        "classification": desc(listed.get("notificationClassification")),
        "risk_decision": desc(listed.get("riskDecision")),
        "product_category": desc(listed.get("productCategory")),
        "product_type": desc(listed.get("productType")),
        "basis": None, "product_name": None, "actions_taken": [], "distribution": None,
        "has_detail": False, "hazards": [],
    }
    if detail and int(detail.get("id") or 0) == nid:
        product = detail.get("product") or {}
        row["has_detail"] = True
        row["basis"] = desc(detail.get("notificationBasis"))
        row["product_name"] = (product.get("description") or "").strip() or None
        row["distribution"] = desc(product.get("distributionStatus"))
        row["actions_taken"] = sorted({desc(m.get("actionTaken")) for m in product.get("measures") or [] if desc(m.get("actionTaken"))})
        if not row["risk_decision"]:
            row["risk_decision"] = ((detail.get("risk") or {}).get("riskDecision") or None)
        row["hazards"] = [r for r in (_hazard_row(h) for h in product.get("hazards") or []) if r]
    return row


# ---------------------------------------------------------------- HTTP

def _request(req: urllib.request.Request, attempts: int = 3):
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):     # deterministic: do not retry
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — timeouts, resets
            last = e
        time.sleep(1.5 * (i + 1))
    raise last  # type: ignore[misc]


def fetch_list_page(page: int) -> dict:
    body = {
        "parameters": {"pageNumber": page, "itemsPerPage": PAGE_SIZE},
        "notificationReference": None, "subjectSearch": None, "notifyingCountry": None,
        "originCountry": [INDIA_NETWORK_ID], "distributionCountry": None, "notificationType": None,
        "notificationStatus": None, "notificationClassification": None, "notificationBasis": None,
        "actionTaken": None, "hazardCategory": None, "productCategory": None, "riskDecision": None,
    }
    req = urllib.request.Request(SEARCH_URL, data=json.dumps(body).encode(),
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
    return _request(req)


def fetch_all_listed() -> list[dict]:
    """Every India-origin notification (list level). Raises RasffUnavailable if the
    first page cannot be read; a later failing page is an error too, since silently
    returning half the list would look like 'nothing new'."""
    out: list[dict] = []
    page = 1
    while True:
        try:
            d = fetch_list_page(page)
        except Exception as e:  # noqa: BLE001
            raise RasffUnavailable(f"RASFF list page {page} failed: {e}") from e
        out += d.get("notifications") or []
        if page >= int(d.get("totalPages") or 0):
            return out
        page += 1
        time.sleep(0.3)


def fetch_detail(nid: int) -> Optional[dict]:
    """None when the notification has no public detail (401/403/404)."""
    req = urllib.request.Request(DETAIL_URL.format(id=nid), headers={"User-Agent": USER_AGENT})
    try:
        return _request(req)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return None
        raise


# ---------------------------------------------------------------- database

def known_state(conn) -> dict[int, tuple[bool, bool]]:
    """notif_id -> (has_detail, detail_was_attempted) for everything already stored."""
    with conn.cursor() as cur:
        cur.execute("SELECT notif_id, has_detail, detail_checked_at IS NOT NULL FROM rasff_notifications")
        return {int(r[0]): (bool(r[1]), bool(r[2])) for r in cur.fetchall()}


def mark_detail_unavailable(conn, nid: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE rasff_notifications SET detail_checked_at = NOW() WHERE notif_id = %s", (nid,))
    conn.commit()


def upsert_notification(conn, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO rasff_notifications
                 (notif_id, reference, validation_date, subject, notifying_country, origin_countries,
                  classification, risk_decision, product_category, product_type, basis, product_name,
                  actions_taken, distribution, has_detail, detail_checked_at, source_url, fetched_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       CASE WHEN %s THEN NOW() ELSE NULL END, %s, NOW())
               ON CONFLICT (notif_id) DO UPDATE SET
                 reference=EXCLUDED.reference, validation_date=EXCLUDED.validation_date, subject=EXCLUDED.subject,
                 notifying_country=EXCLUDED.notifying_country, origin_countries=EXCLUDED.origin_countries,
                 classification=EXCLUDED.classification, risk_decision=EXCLUDED.risk_decision,
                 product_category=EXCLUDED.product_category, product_type=EXCLUDED.product_type,
                 basis=EXCLUDED.basis, product_name=EXCLUDED.product_name, actions_taken=EXCLUDED.actions_taken,
                 distribution=EXCLUDED.distribution, has_detail=EXCLUDED.has_detail,
                 detail_checked_at=COALESCE(EXCLUDED.detail_checked_at, rasff_notifications.detail_checked_at),
                 fetched_at=NOW()""",
            (row["notif_id"], row["reference"], row["validation_date"], row["subject"], row["notifying_country"],
             row["origin_countries"], row["classification"], row["risk_decision"], row["product_category"],
             row["product_type"], row["basis"], row["product_name"], row["actions_taken"], row["distribution"],
             row["has_detail"], row["has_detail"], f"https://webgate.ec.europa.eu/rasff-window/screen/notification/{row['notif_id']}"),
        )
        # Replace the hazards only when we hold the detail: a list-only refresh
        # must not wipe hazards stored earlier.
        if row["has_detail"]:
            cur.execute("DELETE FROM rasff_hazards WHERE notif_id = %s", (row["notif_id"],))
            for h in row["hazards"]:
                cur.execute(
                    """INSERT INTO rasff_hazards
                         (notif_id, hazard, hazard_category, result_raw, result_value, result_qualifier, result_unit,
                          limit_value, limit_unit, exceedance_ratio, exceeds_limit, sampling_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row["notif_id"], h["hazard"], h["hazard_category"], h["result_raw"], h["result_value"],
                     h["result_qualifier"], h["result_unit"], h["limit_value"], h["limit_unit"],
                     h["exceedance_ratio"], h["exceeds_limit"], h["sampling_date"]),
                )
    conn.commit()


def plan_detail_fetches(listed: list[dict], known: dict[int, tuple[bool, bool]],
                        today: Optional[date] = None) -> list[int]:
    """Which notifications need a detail fetch this run, newest first: never
    stored, stored but detail never attempted (the backfill queue), or attempted
    without a result but recent enough that it may since have been published."""
    today = today or date.today()
    todo = []
    for n in listed:
        try:
            nid = int(n["notifId"])
        except (KeyError, TypeError, ValueError):
            continue
        validated = parse_date(n.get("ecValidationDate"))
        has_detail, attempted = known.get(nid, (False, False))
        if not attempted:
            todo.append((validated or date.min, nid))
        elif not has_detail and validated and (today - validated).days <= RECENT_DAYS:
            todo.append((validated, nid))
    todo.sort(reverse=True)
    return [nid for _, nid in todo]


def run(limit: int = DEFAULT_DETAIL_LIMIT) -> dict:
    summary = {"listed": 0, "not_india_or_malformed": 0, "new_notifications": 0, "detail_fetched": 0,
               "detail_unavailable": 0, "detail_errors": 0, "hazards_stored": 0, "backlog_remaining": 0,
               "inserted": 0}
    listed = fetch_all_listed()
    summary["listed"] = len(listed)
    conn = pg_connect()
    try:
        known = known_state(conn)
        # Rows inserted below at list level are 'detail never attempted', so the
        # plan (made after) picks them up newest-first, a capped batch per run.
        by_id: dict[int, dict] = {}
        for n in listed:
            try:
                by_id[int(n["notifId"])] = n
            except (KeyError, TypeError, ValueError):
                summary["not_india_or_malformed"] += 1
        # 1) list-level rows for notifications we have never seen (cheap, no detail needed)
        for nid, n in by_id.items():
            if nid in known:
                continue
            row = parse_notification(n, None)
            if row is None:
                summary["not_india_or_malformed"] += 1
                continue
            upsert_notification(conn, row)
            known[nid] = (False, False)
            summary["new_notifications"] += 1
            summary["inserted"] += 1
        # 2) detail for the newest ones first, up to the per-run cap
        todo = plan_detail_fetches(listed, known)
        batch, summary["backlog_remaining"] = todo[:limit], max(0, len(todo) - limit)
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            results = list(pool.map(_safe_detail, batch))
        for nid, (status, detail) in zip(batch, results):
            if status == "error":
                summary["detail_errors"] += 1
                continue
            if status == "none":
                mark_detail_unavailable(conn, nid)
                summary["detail_unavailable"] += 1
                continue
            row = parse_notification(by_id[nid], detail)
            if row is None:
                summary["not_india_or_malformed"] += 1
                continue
            upsert_notification(conn, row)
            summary["detail_fetched"] += 1
            summary["hazards_stored"] += len(row["hazards"])
    finally:
        conn.close()
    if summary["inserted"] == 0 and summary["detail_fetched"] == 0 and summary["backlog_remaining"] == 0:
        summary["note"] = "nothing new: no India-origin RASFF notification the database does not already hold"
    return summary


def _safe_detail(nid: int) -> tuple[str, Optional[dict]]:
    try:
        d = fetch_detail(nid)
        time.sleep(0.15)
        return ("ok", d) if d is not None else ("none", None)
    except Exception as e:  # noqa: BLE001
        logger.warning("RASFF detail %s failed: %s", nid, e)
        return "error", None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description="Ingest India-origin EU RASFF notifications")
    ap.add_argument("--limit", type=int, default=DEFAULT_DETAIL_LIMIT, help="max detail fetches this run")
    args = ap.parse_args()
    summary = run(args.limit)
    print("\n=== RASFF INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
