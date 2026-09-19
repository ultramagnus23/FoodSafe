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
    """Recording stand-in for `gh`. `existing_issue` is the number of an open
    issue carrying our title ("" = none). `list_fail_times` makes that many
    `issue list` calls fail before one succeeds. `write_rc` is the exit code of
    issue create/comment."""

    def __init__(self, existing_issue="", label_rc=0, list_fail_times=0, write_rc=0, raise_on=None,
                 list_stdout=None):
        self.calls = []
        self.existing, self.label_rc, self.raise_on = existing_issue, label_rc, raise_on
        self.list_fail_times, self.write_rc, self.list_stdout = list_fail_times, write_rc, list_stdout

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        sub = " ".join(cmd[1:3])
        if self.raise_on and self.raise_on in sub:
            raise OSError("gh not found")
        if cmd[1:3] == ["label", "create"]:
            return subprocess.CompletedProcess(cmd, self.label_rc, "", "already exists" if self.label_rc else "")
        if cmd[1:3] == ["issue", "list"]:
            if self.list_fail_times > 0:
                self.list_fail_times -= 1
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 502")
            if self.list_stdout is not None:
                return subprocess.CompletedProcess(cmd, 0, self.list_stdout, "")
            issues = [{"number": int(self.existing), "title": A.TITLE}] if self.existing else []
            return subprocess.CompletedProcess(cmd, 0, json.dumps(issues), "")
        return subprocess.CompletedProcess(cmd, self.write_rc, "https://github.com/o/r/issues/1" if not self.write_rc else "",
                                           "HTTP 403" if self.write_rc else "")

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


def test_gh_failing_to_run_never_raises():
    # No exception may escape; an undelivered alert is a non-zero exit (below).
    for raise_on in ("label create", "issue list", "issue create"):
        A.main(env({"local_news": {"outcome": "failure"}}), FakeGh(raise_on=raise_on))


def test_failure_to_deliver_the_issue_is_visible_not_swallowed():
    # The original alerter died silently (`|| true`). A create or comment that
    # fails must turn the step red.
    assert A.main(env({"local_news": {"outcome": "failure"}}), FakeGh(write_rc=1)) == 1
    assert A.main(env({"local_news": {"outcome": "failure"}}), FakeGh(existing_issue="42", write_rc=1)) == 1
    assert A.main(env({"local_news": {"outcome": "failure"}}), FakeGh(raise_on="issue create")) == 1


def test_no_failures_exit_zero_even_if_gh_is_broken():
    assert A.main(env({"openfda": {"outcome": "success"}}), FakeGh(raise_on="label create", write_rc=1)) == 0


def test_a_transient_list_failure_is_retried_so_no_duplicate_is_opened():
    gh = FakeGh(existing_issue="42", list_fail_times=2)
    assert A.main(env({"local_news": {"outcome": "failure"}}), gh) == 0
    assert gh.verbs().count("issue list") == 3
    assert "issue create" not in gh.verbs()
    assert next(c for c in gh.calls if c[1:3] == ["issue", "comment"])[3] == "42"


def test_a_persistently_failing_lookup_still_alerts_rather_than_stay_silent():
    gh = FakeGh(existing_issue="42", list_fail_times=99)
    assert A.main(env({"local_news": {"outcome": "failure"}}), gh) == 0
    assert gh.verbs().count("issue list") == 3 and "issue create" in gh.verbs()


def test_lookup_matches_the_exact_title_and_does_not_use_search():
    # A different open issue with the label must not be commented on, and
    # `--search` (whose index lags) must not be used.
    other = json.dumps([{"number": 7, "title": "Something else"}])
    gh = FakeGh(list_stdout=other)
    A.main(env({"local_news": {"outcome": "failure"}}), gh)
    assert "issue create" in gh.verbs() and "issue comment" not in gh.verbs()
    listing = next(c for c in gh.calls if c[1:3] == ["issue", "list"])
    assert "--search" not in listing and "--label" in listing


def test_unparseable_or_oddly_shaped_list_output_is_handled():
    for out in ("not json", "{}", "null", '[{"title": 5}, 3, null]'):
        gh = FakeGh(list_stdout=out)
        assert A.main(env({"local_news": {"outcome": "failure"}}), gh) == 0
        assert "issue create" in gh.verbs()


def test_garbled_steps_json_is_ignored():
    gh = FakeGh()
    assert A.main({"STEPS_JSON": "{not json"}, gh) == 0 and gh.calls == []


def test_non_object_steps_json_is_ignored():
    for raw in ("[]", "null", "3", '"x"'):
        gh = FakeGh()
        assert A.main({"STEPS_JSON": raw}, gh) == 0 and gh.calls == []


def test_missing_steps_json_is_ignored():
    gh = FakeGh()
    assert A.main({}, gh) == 0 and gh.calls == []
