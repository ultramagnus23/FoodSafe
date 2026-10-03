"""
Codex Alimentarius pesticide maximum residue limits (CXLs) and JMPR acceptable
daily intakes, from the FAO/WHO Codex online pesticide database's own JSON feed
(the data behind fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/).

  index   https://www.fao.org/jsoncodexpest/jsonrequest/pesticides/index.html
  detail  https://www.fao.org/jsoncodexpest/jsonrequest/pesticides/details.html?id=N&lang=en

Each detail record carries the pesticide's ADI (set by the FAO/WHO Joint
Meeting on Pesticide Residues, JMPR), its residue definition, and every MRL with
its commodity (name + Codex classification code) and its step. Only adopted
Codex MRLs (step code 'CXL') are loaded; draft steps are not law anywhere.

-> food_standards           (jurisdiction 'CODEX', pesticide_mrl)
-> hazard_reference_values  (body 'JMPR', value_type 'ADI')

Codex MRLs are recommendations to governments for international trade; many
countries (India included) adopt or reference them, which is why a gap between
a national limit and the Codex one is meaningful.

The feed is hand-made JSON that sometimes has trailing commas; they are removed
before parsing. A pesticide whose detail cannot be fetched fails the run (the
index says it exists, so a silent omission would under-report Codex coverage).

Run: python -m pipeline.sources.standards_codex [--dry-run]
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
from decimal import Decimal, InvalidOperation
from typing import Optional

from pipeline.sources.standards_common import StandardRow, clean_text, hazard_key, replace_snapshot, summarise

logger = logging.getLogger("foodsafe.standards_codex")

INDEX_URL = "https://www.fao.org/jsoncodexpest/jsonrequest/pesticides/index.html"
DETAIL_URL = "https://www.fao.org/jsoncodexpest/jsonrequest/pesticides/details.html?id={id}&lang=en"
PAGE_URL = "https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/pesticide-detail/en/?p_id={id}"
DB_URL = "https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/en/"
USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
PARSER_VERSION = "codex-pestres-1"


class CodexUnavailable(RuntimeError):
    """The Codex pesticide feed could not be read — an outage, not 'no limits'."""


def loads_lenient(text: str) -> dict:
    """The feed's JSON is template-generated: trailing commas, raw control
    characters (line breaks) inside strings, and unescaped double quotes inside
    values ('... and "oxychlordane" (fat-soluble).'). The template writes one
    `"key": "value",` per line, so a value's inner quotes are escaped line by line
    — only when the plain parse fails."""
    t = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        return json.loads(t, strict=False)
    except json.JSONDecodeError:
        pass
    fixed = []
    for line in t.split("\n"):
        m = re.match(r'^(\s*"[A-Za-z0-9_]+"\s*:\s*")(.*)("\s*,?\s*)$', line)
        if m:
            inner = re.sub(r'(?<!\\)"', r'\\"', m.group(2))
            line = m.group(1) + inner + m.group(3)
        fixed.append(line)
    return json.loads("\n".join(fixed), strict=False)


REQUEST_PAUSE_S = 0.4     # between detail requests, per worker: FAO rate-limits bursts (HTTP 429)


def _retry_after(e: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait after a 429: the server's Retry-After when it gives one
    (capped), else 15, 30, 60, 120 s."""
    try:
        return min(float(e.headers.get("Retry-After", "")), 180.0)
    except (TypeError, ValueError):
        return 15.0 * 2 ** attempt


def _get(url: str, attempts: int = 5) -> dict:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            if body.lstrip().startswith("<"):
                raise ValueError("HTML error page instead of JSON")
            return loads_lenient(body)
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(_retry_after(e, i) if e.code == 429 else 2 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise CodexUnavailable(f"{url}: {last}")


def _dec(s: Optional[str]) -> Optional[Decimal]:
    try:
        v = Decimal((s or "").strip())
    except InvalidOperation:
        return None
    return v if v.is_finite() and v >= 0 else None


def index_ids(index: dict) -> list[tuple[str, str]]:
    out = []
    for p in (index.get("pesticides") or {}).get("pesticide") or []:
        name = clean_text(((p.get("name") or {}).get("en")))
        pid = str(p.get("id") or "").strip()
        if name and pid:
            out.append((pid, name))
    return out


def detail_rows(pid: str, d: dict) -> tuple[list[StandardRow], Optional[dict]]:
    """One pesticide's detail -> (CXL rows, ADI record or None)."""
    name = clean_text(d.get("pesticide"))
    rows = []
    mrls = (d.get("mrls") or {}).get("mrl") or []
    if isinstance(mrls, dict):
        mrls = [mrls]
    for m in mrls:
        step = ((m.get("step") or {}).get("stepCode") or "").strip()
        if step != "CXL":
            continue
        comm = m.get("commodity") or {}
        raw = (m.get("mrl") or "").strip()
        lod = (m.get("lod") or "").strip()
        flags = [x for x in (lod, (m.get("fatPh") or "").strip(), (m.get("sourceOfRes") or "").strip()) if x]
        value = _dec(raw)
        rows.append(StandardRow(
            jurisdiction="CODEX", standard_type="pesticide_mrl", hazard_raw=name, hazard_class="pesticide",
            food_raw=clean_text(comm.get("name")), food_code=clean_text(comm.get("commCode")) or None,
            limit_raw=(raw + (" " + " ".join(flags) if flags else "")).strip(),
            limit_value=value, limit_unit="mg/kg", parse_status="exact" if value is not None else "not_numeric",
            at_loq="*" in lod, limit_basis="fat basis" if "fat" in (m.get("fatPh") or "").lower() else None,
            note=clean_text(m.get("footnote")) or None,
            legal_reference=f"Codex MRL (CXL), adopted CAC {m.get('cacYear') or '?'}; JMPR {m.get('jmpr') or '?'}",
            source_url=PAGE_URL.format(id=pid),
            extra={"ccpr": m.get("ccpr"), "cac_year": m.get("cacYear")},
        ))
    adi = None
    adi_raw = clean_text(d.get("adi"))
    if adi_raw:
        upper = adi_raw.split("-")[-1] if re.fullmatch(r"0\s*-\s*[\d.]+", adi_raw) else adi_raw
        unit = clean_text(d.get("adiUnit")) or None
        note = clean_text(d.get("adiNote"))
        year = re.search(r"\((\d{4})\)", note or "")
        adi = {"hazard_key": hazard_key(name), "value": _dec(upper.strip()), "unit": unit,
               "raw_text": f"{adi_raw} {unit or ''}".strip() + (f" — {note}" if note else ""),
               "year": int(year.group(1)) if year else None, "source_url": PAGE_URL.format(id=pid)}
    return rows, adi


def fetch_all(workers: int = 2) -> tuple[list[StandardRow], list[dict], dict]:
    ids = index_ids(_get(INDEX_URL))
    if len(ids) < 50:
        raise CodexUnavailable(f"index lists only {len(ids)} pesticides")

    def one(pid_name):
        pid, _ = pid_name
        d = _get(DETAIL_URL.format(id=pid))
        time.sleep(REQUEST_PAUSE_S)
        return pid, d

    rows: list[StandardRow] = []
    adis: list[dict] = []
    with ThreadPoolExecutor(workers) as ex:
        for pid, d in ex.map(one, ids):
            r, a = detail_rows(pid, d)
            rows += r
            if a and a["hazard_key"]:
                adis.append(a)
    return rows, adis, {"pesticides_in_index": len(ids), "with_adi": len(adis)}


def load_adis(conn, adis: list[dict]) -> int:
    from psycopg2.extras import execute_batch
    with conn.cursor() as cur:
        execute_batch(cur,
            """INSERT INTO hazard_reference_values (hazard_key, body, value_type, value, unit, raw_text, year,
                                                    source_ref, source_url)
               VALUES (%s,'JMPR','ADI',%s,%s,%s,%s,'Codex online pesticide database (JMPR evaluation)',%s)
               ON CONFLICT (hazard_key, body, value_type) DO UPDATE SET value=EXCLUDED.value, unit=EXCLUDED.unit,
                 raw_text=EXCLUDED.raw_text, year=EXCLUDED.year, source_url=EXCLUDED.source_url, loaded_at=NOW()""",
            [(a["hazard_key"], a["value"], a["unit"], a["raw_text"], a["year"], a["source_url"]) for a in adis],
            page_size=500)
    conn.commit()
    return len(adis)


def run(dry_run: bool = False) -> dict:
    rows, adis, info = fetch_all()
    info.update(summarise(rows))
    if dry_run:
        return {**info, "inserted": 0, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = replace_snapshot(conn, "CODEX", {"pesticide_mrl"}, rows,
                               document_title="Codex online pesticide database — adopted MRLs (CXL)",
                               document_url=DB_URL, document_version=time.strftime("%Y-%m-%d"),
                               document_sha256=None, parser_version=PARSER_VERSION)
        res["adis_loaded"] = load_adis(conn, adis)
    finally:
        conn.close()
    return {**info, **res}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    print(run(ap.parse_args().dry_run))


if __name__ == "__main__":
    main()
