# FoSCoS FBO/license search — investigation & status

**TL;DR:** the FoSCoS public "Commodity, Category Or Area Specific Search"
tool (`/advance-fbo-search`) — the citizen-facing lookup for licensed food
business operators — is **not** scrapable. It sits behind the exact same
`commonauth_readonly/commonapi/*` captcha/auth wall already documented for
the recall API in `docs/FSSAI_INGESTION.md`. The page itself loads, and the
search form renders in the DOM, but **the captcha image can never load for
an anonymous automated client** (`commonauth_readonly/commonapi/captcha`
returns 401 before any interaction), so there is no way to legitimately
complete the form. This is not a fixable scraper bug — it's the same
deliberate access-control tightening across all of FoSCoS's `commonapi`
surface, not just recalls. **This is not a viable real-data source for
locality-level FBO coverage.**

## What I tried

1. Confirmed the FoSCoS homepage (`https://foscos.fssai.gov.in/`) is a pure
   Angular SPA (static HTML fetch returns only `<app-root></app-root>` plus
   script tags — no server-rendered nav). No plain HTTP GET can find the
   FBO search link; the page has to be rendered.
2. Extracted the compiled Angular route table and API call names directly
   from the served JS bundles (`main.*.bundle.js`) via a plain HTTP GET —
   this is read-only, it's just parsing the same JS a browser downloads,
   not reverse-engineering any protected code. This is how the URL was
   found: the FBO/license search route is `advance-fbo-search`, with a
   near-identical companion route `advance-manufacturing-fbo-search`. Both
   call the same backend API, `getadvancesearchapplicationdetails`, under
   `webgateway/commonauth_readonly/commonapi/` — the identical path prefix
   already confirmed blocked for `getFoodRecallProductHomepage`.
3. Used a headless Playwright browser (read-only: page load + DOM read +
   network header inspection only, per this project's stated ethical
   boundary — no captcha bypass, no auth bypass, no PII) to load
   `https://foscos.fssai.gov.in/advance-fbo-search` and observe what
   actually happens for a normal anonymous visitor:
   - The page **loads successfully** (HTTP 200, `server: FoSCoS`).
   - The search form **renders**: License/Registration Category, State,
     District, Company Name, License/Registration No., Kind-of-Business
     type, Active/Inactive status, and a captcha field — this is a real,
     structured search UI with the fields you'd want (state/district/KOB
     filters would in principle let a query be narrowed to a pincode-level
     area).
   - But on page load, two calls to `commonauth_readonly/commonapi/*` fire
     immediately and **both return 401**:
     `commonauth_readonly/commonapi/captcha` (the endpoint that would
     serve the captcha image itself) and
     `commonauth_readonly/commonapi/getallsearchkoblist` (the
     Kind-of-Business dropdown values). Same response signature as the
     recall finding: empty body,
     `access-control-expose-headers: captcha`.
   - Because the captcha endpoint itself is 401, **there is no captcha
     image to solve** — not "a captcha blocks automated submission" but
     "the anonymous session can't even retrieve a captcha to begin with."
     Per the project's ethical boundary (no captcha/auth bypass), I did
     not fill in and submit the form — there was nothing legitimate left
     to submit; doing so would only reconfirm the same 401, not surface
     new information. `scripts/probe_fbo_license.py` encodes this same
     stop condition programmatically (it checks whether the captcha API
     is already 401 before attempting any form fill).

## What I found

| Check | Result |
| --- | --- |
| Is `/advance-fbo-search` reachable at all? | Yes — page loads (200), form renders in the DOM. |
| Does the form expose real search fields (state/district/pincode-adjacent filters)? | Yes — Category, State, District, Company Name, License No., KOB type, Active/Inactive. Structurally, this is exactly the kind of form that could yield locality-level FBO records if it worked. |
| Can an anonymous client obtain a captcha to submit the form? | **No.** `commonauth_readonly/commonapi/captcha` → 401 on load, before any user interaction. |
| Can an anonymous client get the KOB dropdown (a purely cosmetic list, no PII)? | **No.** `commonauth_readonly/commonapi/getallsearchkoblist` → 401. Mirrors the `getfinancialyeardropdown` finding from the recall probe — confirms (again) that FSSAI locked the **entire** `commonapi` surface, not a feature-specific gate. |
| Did any FBO/license data reach the client? | **No.** Zero records observed; the search API (`getadvancesearchapplicationdetails`) was never even called because the form can't be legitimately completed. |

## Conclusion

This is the same finding as the recall API, on a different feature: FoSCoS
gates **all** of `commonauth_readonly/commonapi/*` — captcha issuance
included — behind an anonymous-auth handshake that a plain browser/headless
session doesn't have. That handshake is out of scope to defeat (captcha/bot
protection on a government auth endpoint), consistent with this project's
stated boundary and with the `docs/FSSAI_INGESTION.md` recall finding.

**For the project's locality-level goal** (distinguishing e.g. Juhu vs Vile
Parle vs Churchgate within Mumbai, which no current data source in this
pipeline supports): FoSCoS's FBO search is structurally the *right* tool —
State/District/KOB/company filters are exactly what a locality-density
dataset would need, and if it worked, it would yield real FBO
names/addresses to geocode into localities even without any violation data.
But it is not currently usable. This closes off FoSCoS as a source for that
goal the same way the recall finding closed it off for enforcement data;
the realistic paths forward remain the ones already listed in
`docs/FSSAI_INGESTION.md` §"What remains" (RTI/bulk data request, or a
state-level portal that publishes structured FBO listings outside FoSCoS —
unchecked as of this investigation).

## Reproducing this finding

```bash
pip install playwright
python -m playwright install chromium
python scripts/probe_fbo_license.py
```

Appends one JSON line to `docs/foscos_fbo_search_access_log.jsonl` per run
(same log-per-run pattern as `scripts/probe_foscos.py` →
`docs/foscos_access_log.jsonl`), so if FSSAI's access model ever changes,
there's dated evidence of it rather than a single anecdote. First run
(2026-07-11 UTC) is already in the log and confirms the 401 findings above.
