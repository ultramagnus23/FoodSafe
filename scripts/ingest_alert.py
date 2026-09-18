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
  * if an open issue with the fixed title already exists, adds a comment (so a
    step failing for a week is one issue, not seven);
  * otherwise opens one.
Never raises: alerting must not turn a green run red.

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
    "fssai_annual_report": "FSSAI Annual Report metrics",
    "local_news": "Local news (5 metros)",
    "research_evidence": "OpenAlex evidence",
    "europepmc_evidence": "Europe PMC evidence",
}

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def failed_steps(steps: dict) -> list[str]:
    return sorted(k for k, v in steps.items() if isinstance(v, dict) and v.get("outcome") == "failure")


def describe(step_ids: list[str]) -> str:
    return "\n".join(f"- `{sid}` — {FRIENDLY.get(sid, 'see workflow')}" for sid in step_ids)


def _gh(runner: Runner, args: list[str]) -> "subprocess.CompletedProcess[str]":
    return runner(["gh", *args], capture_output=True, text=True, check=False)


def main(env: Optional[dict] = None, runner: Runner = subprocess.run) -> int:
    env = os.environ if env is None else env
    try:
        steps = json.loads(env.get("STEPS_JSON") or "{}")
    except json.JSONDecodeError as e:
        print(f"could not parse STEPS_JSON ({e}); not alerting")
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

        found = _gh(runner, ["issue", "list", *repo_args, "--state", "open", "--label", LABEL,
                             "--search", f'"{TITLE}" in:title', "--json", "number", "--jq", ".[0].number // empty"])
        existing = (found.stdout or "").strip()
        if found.returncode == 0 and existing.isdigit():
            res = _gh(runner, ["issue", "comment", existing, *repo_args, "--body", body])
            print(f"commented on open issue #{existing} (rc={res.returncode})")
        else:
            res = _gh(runner, ["issue", "create", *repo_args, "--title", TITLE, "--body", body, "--label", LABEL])
            print(f"opened new issue (rc={res.returncode}): {(res.stdout or res.stderr or '').strip()[:200]}")
    except Exception as e:  # noqa: BLE001 — alerting must never fail the run
        print(f"alerting failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
