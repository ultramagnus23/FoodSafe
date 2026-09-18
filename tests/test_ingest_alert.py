"""
Tests for scripts/ingest_alert.py. `gh` is replaced by a recording fake, so no
network and no issues are created. The behaviours that matter: it must alert on
a continue-on-error step that failed (outcome=failure), stay silent on a clean
run, never duplicate an already-open issue, and never fail the workflow.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ingest_alert as A  # noqa: E402


class FakeGh:
    def __init__(self, existing_issue="", label_rc=0, list_rc=0, raise_on=None):
        self.calls = []
        self.existing, self.label_rc, self.list_rc, self.raise_on = existing_issue, label_rc, list_rc, raise_on

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        sub = " ".join(cmd[1:3])
        if self.raise_on and self.raise_on in sub:
            raise OSError("gh not found")
        if cmd[1:3] == ["label", "create"]:
            return subprocess.CompletedProcess(cmd, self.label_rc, "", "already exists" if self.label_rc else "")
        if cmd[1:3] == ["issue", "list"]:
            return subprocess.CompletedProcess(cmd, self.list_rc, self.existing, "")
        return subprocess.CompletedProcess(cmd, 0, "https://github.com/o/r/issues/1", "")

    def verbs(self):
        return [" ".join(c[1:3]) for c in self.calls]


def env(steps):
    return {"STEPS_JSON": json.dumps(steps), "RUN_URL": "https://example/run/1", "GITHUB_REPOSITORY": "o/r"}


def test_failed_steps_reads_outcome_not_conclusion():
    # A continue-on-error step is conclusion=success but outcome=failure.
    steps = {"local_news": {"outcome": "failure", "conclusion": "success"},
             "openfda": {"outcome": "success", "conclusion": "success"},
             "agmarknet": {"outcome": "skipped", "conclusion": "skipped"}}
    assert A.failed_steps(steps) == ["local_news"]


def test_clean_run_makes_no_gh_calls():
    gh = FakeGh()
    assert A.main(env({"openfda": {"outcome": "success"}}), gh) == 0
    assert gh.calls == []


def test_a_failure_with_no_open_issue_creates_the_label_and_one_issue():
    gh = FakeGh(existing_issue="")
    assert A.main(env({"local_news": {"outcome": "failure"}, "openfda": {"outcome": "success"}}), gh) == 0
    assert gh.verbs() == ["label create", "issue list", "issue create"]
    create = next(c for c in gh.calls if c[1:3] == ["issue", "create"])
    assert A.LABEL in create and A.TITLE in create
    body = create[create.index("--body") + 1]
    assert "`local_news`" in body and "Local news" in body and "openfda" not in body


def test_an_open_issue_gets_a_comment_not_a_duplicate():
    gh = FakeGh(existing_issue="42")
    A.main(env({"fssai_recall": {"outcome": "failure"}}), gh)
    assert "issue create" not in gh.verbs()
    comment = next(c for c in gh.calls if c[1:3] == ["issue", "comment"])
    assert comment[3] == "42"


def test_several_failed_steps_are_listed_together():
    gh = FakeGh()
    A.main(env({"local_news": {"outcome": "failure"}, "loksabha_sampling": {"outcome": "failure"}}), gh)
    body = next(c for c in gh.calls if c[1:3] == ["issue", "create"])
    body = body[body.index("--body") + 1]
    assert "`local_news`" in body and "`loksabha_sampling`" in body


def test_unknown_step_ids_still_appear():
    assert "`brand_new_step`" in A.describe(["brand_new_step"])


def test_label_already_existing_does_not_stop_the_alert():
    gh = FakeGh(label_rc=1)
    A.main(env({"local_news": {"outcome": "failure"}}), gh)
    assert "issue create" in gh.verbs()


def test_gh_failing_to_run_never_fails_the_workflow():
    for raise_on in ("label create", "issue list", "issue create"):
        assert A.main(env({"local_news": {"outcome": "failure"}}), FakeGh(raise_on=raise_on)) == 0


def test_garbled_steps_json_is_ignored():
    gh = FakeGh()
    assert A.main({"STEPS_JSON": "{not json"}, gh) == 0 and gh.calls == []


def test_missing_steps_json_is_ignored():
    gh = FakeGh()
    assert A.main({}, gh) == 0 and gh.calls == []
