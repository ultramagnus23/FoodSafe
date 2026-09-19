"""
Report failed steps of the scheduled ingest run as ONE rolling GitHub issue.

Why this exists: the workflow's old alert steps ran
`gh issue create --label ingest-failure || true`, but that label never existed,
so `gh` failed and the `|| true` swallowed it — the regression alerting the
launch checklist relies on had never fired once. Several continue-on-error
steps (local_news, loksabha_*, the evidence connectors) had no alert at all,
which is how a missing-dependency failure went unseen.

Behaviour:
  * reads the `steps` context (JSON) from $STEPS_JSON and finds steps whose
    outcome is 'failure' (a continue-on-error step keeps outcome=failure even
    though its conclusion is success — that is the point);
  * no failures -> does nothing;
  * ensures the label exists (idempotent);
  * if an open issue with the fixed title already exists (looked up by label,
    title matched exactly, retried on error), adds a comment (so a step
    failing for a week is one issue, not seven);
  * otherwise opens one.
Never raises. Exits 1 only when there were failures and the issue could not be
delivered (so a broken alerter is visible, not silent); exits 0 otherwise.

Env: GH_TOKEN, STEPS_JSON, RUN_URL, GITHUB_REPOSITORY.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

LABEL = "ingest-failure"
TITLE = "Ingest regression: scheduled ingest steps failing"

FRIENDLY = {
    "bootstrap_db": "Database schema sync",
    "openfda": "openFDA food enforcement",
    "agmarknet": "AGMARKNET districts/commodities",
    "fssai_recall": "FoSCoS recall scraper",
    "fssai_commissioners": "FSSAI commissioner directory",
    "fssai_labs": "FSSAI lab directories",
    "loksabha_qa": "Lok Sabha state enforcement",
    "loksabha_sampling": "Lok Sabha state sampling outcomes",
    "loksabha_pesticide": "Lok Sabha pesticide-residue (MPRNL) results",
    "fssai_annual_report": "FSSAI Annual Report metrics",
    "local_news": "Local news (5 metros)",
    "research_evidence": "OpenAlex evidence",
    "europepmc_evidence": "Europe PMC evidence",
    "aggregation": "Risk-score aggregation",
    "disease_burden": "Disease-burden estimates",
    "notifications": "Alert-subscription notifications",
}

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def failed_steps(steps: dict) -> list[str]:
    return sorted(k for k, v in steps.items() if isinstance(v, dict) and v.get("outcome") == "failure")


def describe(step_ids: list[str]) -> str:
    return "\n".join(f"- `{sid}` — {FRIENDLY.get(sid, 'see workflow')}" for sid in step_ids)


def _gh(runner: Runner, args: list[str]) -> "subprocess.CompletedProcess[str]":
    return runner(["gh", *args], capture_output=True, text=True, check=False)


def _find_open_issue(runner: Runner, repo_args: list[str], attempts: int = 3) -> Optional[str]:
    """Number of the open issue carrying our exact title, "" if there is none,
    None if the lookup itself kept failing.

    Lists by label (a plain filter) and matches the title here rather than using
    `--search`, whose index lags: an issue opened by yesterday's run may not be
    searchable yet, which would open a duplicate every day. A failed lookup is
    retried, and reported as None rather than "none found" so the caller can
    tell a transient error from an empty result.
    """
    for _ in range(attempts):
        res = _gh(runner, ["issue", "list", *repo_args, "--state", "open", "--label", LABEL,
                           "--limit", "100", "--json", "number,title"])
        if res.returncode != 0:
            continue
        try:
            issues = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if isinstance(issue, dict) and issue.get("title") == TITLE and str(issue.get("number", "")).isdigit():
                return str(issue["number"])
        return ""
    return None


def main(env: Optional[dict] = None, runner: Runner = subprocess.run) -> int:
    """0 = nothing to report or the report was delivered (or could not be
    attempted for a reason that is not a delivery failure); 1 = there were
    failed steps and the issue could not be created or commented on. Any
    exception is caught, so alerting can never crash the workflow -- but an
    undelivered alert IS surfaced as a red step, because a silent alerter is
    the failure this script exists to replace."""
    env = os.environ if env is None else env
    try:
        steps = json.loads(env.get("STEPS_JSON") or "{}")
    except json.JSONDecodeError as e:
        print(f"could not parse STEPS_JSON ({e}); not alerting")
        return 0
    if not isinstance(steps, dict):
        print(f"STEPS_JSON is a {type(steps).__name__}, not an object; not alerting")
        return 0

    failing = failed_steps(steps)
    if not failing:
        print("no failed steps; nothing to report")
        return 0

    repo = env.get("GITHUB_REPOSITORY", "")
    run_url = env.get("RUN_URL", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = (
        f"{today} — these steps of the scheduled ingest run failed (outcome=failure, including "
        f"continue-on-error steps whose green check hides it):\n\n{describe(failing)}\n\nRun: {run_url}\n\n"
        "An explained access gate (e.g. FoSCoS returning 401) is reported by the step as an expected "
        "outcome and does not appear here; a step listed here failed unexpectedly. See "
        "`pipeline_runs` / `/admin` and docs/FSSAI_INGESTION.md."
    )
    repo_args = ["--repo", repo] if repo else []

    try:
        # Idempotent; ignore 'already exists'.
        _gh(runner, ["label", "create", LABEL, *repo_args, "--color", "B60205",
                     "--description", "A scheduled ingest step failed unexpectedly"])

        existing = _find_open_issue(runner, repo_args)
        if existing:
            res = _gh(runner, ["issue", "comment", existing, *repo_args, "--body", body])
            what = f"comment on open issue #{existing}"
        else:
            # existing is "" (none open) or None (lookup kept failing). In the
            # second case a possible duplicate issue is the lesser evil: the
            # alternative is no alert at all.
            res = _gh(runner, ["issue", "create", *repo_args, "--title", TITLE, "--body", body, "--label", LABEL])
            what = "new issue" if existing == "" else "new issue (open-issue lookup failed, may duplicate)"
        if res.returncode != 0:
            print(f"::error::could not deliver alert ({what}), rc={res.returncode}: "
                  f"{(res.stderr or res.stdout or '').strip()[:300]}")
            return 1
        print(f"delivered alert as {what}: {(res.stdout or '').strip()[:200]}")
    except Exception as e:  # noqa: BLE001 — alerting must never crash the run
        print(f"::error::alerting failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
