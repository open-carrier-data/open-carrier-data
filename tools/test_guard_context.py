#!/usr/bin/env python3
"""guard_context.py: the base and the accept lines of validate's guard on
pull_request, merge_group and workflow_dispatch runs (rule decisions round 37,
items 3 and 4), with a stand-in API and a stand-in guard on small git
repositories."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard_context as gc

REPO = "open-carrier-data/open-carrier-data"
SHA = "a" * 40
BASE = "b" * 40
MAIN_HEAD = "c" * 40
OTHER = "d" * 40
DIGEST = "0123456789abcdef"
OTHER_DIGEST = "fedcba9876543210"
WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "validate.yml"

# A stand-in for check_phone_guard.py: prints its arguments, passes, or
# holds when STUB_HOLD is in the environment.
STUB_GUARD = '''
import json, os, sys
print("phone-level guard: STUB " + json.dumps(sys.argv[1:]))
sys.exit(1 if os.environ.get("STUB_HOLD") else 0)
'''


def pull(number: int, sha: str, body: str = "", repo: str = REPO, ref: str = "feature",
         state: str = "open", base: str = "main") -> dict:
    return {"number": number, "state": state, "body": body,
            "head": {"sha": sha, "ref": ref, "repo": {"full_name": repo}},
            "base": {"ref": base, "sha": MAIN_HEAD}}


class FakeApi:
    def __init__(self, routes: dict[str, object] | None = None, pulls: list | None = None):
        self.routes = dict(routes or {})
        self.pulls = pulls  # a list of answers to successive pulls?head= calls
        self.calls: list[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        if "/pulls?" in path:
            if not self.pulls:
                return []
            return self.pulls.pop(0) if len(self.pulls) > 1 else self.pulls[0]
        for prefix, answer in self.routes.items():
            if path.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise gc.ContextError(f"unexpected API call {path}")


def env(event: str, ref: str, sha: str = SHA) -> dict[str, str]:
    return {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "GITHUB_SHA": sha, "GITHUB_REPOSITORY": REPO}


COMPARE = {f"repos/{REPO}/compare/main...{SHA}": {"merge_base_commit": {"sha": BASE}}}


def no_sleep(_seconds: float) -> None:
    pass


class AcceptLines(unittest.TestCase):
    def test_whole_lines_only(self) -> None:
        body = (f"intro\r\nphone-guard-accept: {DIGEST}\r\n  phone-guard-accept: {OTHER_DIGEST}\n"
                f"phone-guard-accept: {DIGEST}0\nphone-guard-accept: {DIGEST}\n")
        self.assertEqual(gc.accept_lines(body), [DIGEST])
        self.assertEqual(gc.accept_lines(None), [])


class PullRequest(unittest.TestCase):
    def test_event_base_and_body(self) -> None:
        event = {"pull_request": {"number": 7, "base": {"sha": BASE}, "body": f"phone-guard-accept: {DIGEST}"}}
        api = FakeApi()
        context = gc.resolve(env("pull_request", "refs/pull/7/merge"), event, api)
        self.assertTrue(context["guard"])
        self.assertEqual((context["base"], context["pr"], context["accept"]), (BASE, 7, [DIGEST]))
        self.assertFalse(context["require_unchanged"])
        self.assertEqual(api.calls, [])


class MergeGroup(unittest.TestCase):
    def event(self, head_ref: str) -> dict:
        return {"merge_group": {"base_sha": BASE, "head_sha": SHA, "head_ref": head_ref, "base_ref": "refs/heads/main"}}

    def test_queued_pull_request_accepts(self) -> None:
        ref = f"refs/heads/gh-readonly-queue/main/pr-342-{BASE}"
        api = FakeApi({f"repos/{REPO}/pulls/342": pull(342, OTHER, f"phone-guard-accept: {DIGEST}\n")})
        context = gc.resolve(env("merge_group", ref), self.event(ref), api)
        self.assertTrue(context["guard"])
        self.assertEqual((context["base"], context["base_from"]), (BASE, "merge_group.base_sha"))
        self.assertEqual((context["pr"], context["accept"]), (342, [DIGEST]))
        self.assertEqual(api.calls, [f"repos/{REPO}/pulls/342"])

    def test_no_single_pull_request_fails_closed(self) -> None:
        for ref in ("refs/heads/gh-readonly-queue/main/pr-x-" + BASE, "refs/heads/feature",
                    f"refs/heads/gh-readonly-queue/main/pr-1-2-{BASE[:-1]}", ""):
            with self.subTest(ref=ref), self.assertRaises(gc.ContextError):
                gc.resolve(env("merge_group", ref or "refs/heads/x"), self.event(ref), FakeApi())

    def test_closed_or_unreadable_pull_request_fails_closed(self) -> None:
        ref = f"refs/heads/gh-readonly-queue/main/pr-9-{BASE}"
        for answer in (pull(9, OTHER, f"phone-guard-accept: {DIGEST}", state="closed"),
                       pull(9, OTHER, base="release"), {"message": "Not Found"},
                       gc.ContextError("gh api: HTTP 502")):
            with self.subTest(answer=str(answer)[:40]), self.assertRaises(gc.ContextError):
                gc.resolve(env("merge_group", ref), self.event(ref), FakeApi({f"repos/{REPO}/pulls/9": answer}))

    def test_missing_base_fails_closed(self) -> None:
        ref = f"refs/heads/gh-readonly-queue/main/pr-9-{BASE}"
        event = {"merge_group": {"head_ref": ref}}
        with self.assertRaises(gc.ContextError):
            gc.resolve(env("merge_group", ref), event, FakeApi({f"repos/{REPO}/pulls/9": pull(9, OTHER)}))


class Dispatch(unittest.TestCase):
    def test_main_runs_no_guard(self) -> None:
        context = gc.resolve(env("workflow_dispatch", "refs/heads/main"), {"inputs": {}}, FakeApi())
        self.assertFalse(context["guard"])
        self.assertIsNone(context["base"])

    def test_the_one_pull_request_at_the_run_sha_accepts(self) -> None:
        api = FakeApi(COMPARE, [[pull(5, SHA, f"phone-guard-accept: {DIGEST}")]])
        context = gc.resolve(env("workflow_dispatch", "refs/heads/feature"), {"inputs": {}}, api, no_sleep)
        self.assertTrue(context["guard"])
        self.assertEqual((context["base"], context["pr"], context["accept"]), (BASE, 5, [DIGEST]))
        self.assertFalse(context["require_unchanged"])
        self.assertIn(f"head=open-carrier-data:feature", api.calls[-1])

    def test_no_pull_request_accepts_nothing(self) -> None:
        context = gc.resolve(env("workflow_dispatch", "refs/heads/feature"), {}, FakeApi(COMPARE, [[]]), no_sleep)
        self.assertTrue(context["guard"])
        self.assertEqual((context["base"], context["pr"], context["accept"]), (BASE, None, []))
        self.assertTrue(context["require_unchanged"])

    def test_dispatch_inputs_never_accept(self) -> None:
        event = {"inputs": {"checks_only": "true", "simulate_today": f"phone-guard-accept: {DIGEST}",
                            "accept": DIGEST}}
        context = gc.resolve(env("workflow_dispatch", "refs/heads/feature"), event, FakeApi(COMPARE, [[]]), no_sleep)
        self.assertEqual(context["accept"], [])
        self.assertTrue(context["require_unchanged"])

    def test_other_heads_forks_and_bases_do_not_count(self) -> None:
        cases = {
            "fork": [pull(5, SHA, f"phone-guard-accept: {DIGEST}", repo="someone/open-carrier-data")],
            "other branch": [pull(5, SHA, f"phone-guard-accept: {DIGEST}", ref="feature-2")],
            "not into main": [pull(5, SHA, f"phone-guard-accept: {DIGEST}", base="release")],
            "closed": [pull(5, SHA, f"phone-guard-accept: {DIGEST}", state="closed")],
            "two at the sha": [pull(5, SHA, f"phone-guard-accept: {DIGEST}"), pull(6, SHA, "")],
        }
        for name, answer in cases.items():
            with self.subTest(name):
                context = gc.resolve(env("workflow_dispatch", "refs/heads/feature"), {},
                                     FakeApi(COMPARE, [answer]), no_sleep)
                self.assertEqual((context["pr"], context["accept"], context["require_unchanged"]), (None, [], True))

    def test_head_not_moved_yet_is_waited_for(self) -> None:
        sleeps: list[float] = []
        api = FakeApi(COMPARE, [[pull(5, OTHER, "")], [pull(5, OTHER, "")],
                                [pull(5, SHA, f"phone-guard-accept: {DIGEST}")]])
        context = gc.resolve(env("workflow_dispatch", "refs/heads/feature"), {}, api, sleeps.append)
        self.assertEqual((context["pr"], context["accept"]), (5, [DIGEST]))
        self.assertEqual(len(sleeps), 2)

    def test_a_pull_request_at_another_sha_never_accepts(self) -> None:
        sleeps: list[float] = []
        api = FakeApi(COMPARE, [[pull(5, OTHER, f"phone-guard-accept: {DIGEST}")]])
        context = gc.resolve(env("workflow_dispatch", "refs/heads/feature"), {}, api, sleeps.append)
        self.assertEqual((context["pr"], context["accept"], context["require_unchanged"]), (None, [], True))
        self.assertEqual(len(sleeps), gc.HEAD_ATTEMPTS - 1)

    def test_tag_has_no_pull_request(self) -> None:
        context = gc.resolve(env("workflow_dispatch", "refs/tags/data-2026.10"), {}, FakeApi(COMPARE), no_sleep)
        self.assertTrue(context["guard"])
        self.assertTrue(context["require_unchanged"])

    def test_no_merge_base_fails_closed(self) -> None:
        for answer in ({"message": "Not Found"}, gc.ContextError("gh api: HTTP 404")):
            with self.subTest(answer=str(answer)), self.assertRaises(gc.ContextError):
                gc.resolve(env("workflow_dispatch", "refs/heads/feature"), {},
                           FakeApi({f"repos/{REPO}/compare/main...{SHA}": answer}), no_sleep)


class OtherEvents(unittest.TestCase):
    def test_push_to_main_runs_no_guard(self) -> None:
        context = gc.resolve(env("push", "refs/heads/main"), {"before": OTHER}, FakeApi())
        self.assertFalse(context["guard"])

    def test_unknown_events_and_refs_fail(self) -> None:
        for name, ref in (("push", "refs/heads/feature"), ("pull_request_target", "refs/heads/main"),
                          ("schedule", "refs/heads/main")):
            with self.subTest(name=name, ref=ref), self.assertRaises(gc.ContextError):
                gc.resolve(env(name, ref), {}, FakeApi())


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class Guard(unittest.TestCase):
    """The guard step on a branch whose apns-conf.xml differs from its base."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "generated" / "android").mkdir(parents=True)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "test")
        self.apn = self.root / gc.APN_FILE
        self.apn.write_text('<apns version="8">\n<apn mcc="262" mnc="01" apn="web" type="default" />\n</apns>\n')
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        self.base = git(self.root, "rev-parse", "HEAD")
        git(self.root, "checkout", "-q", "-b", "feature")
        self.apn.write_text('<apns version="8">\n<apn mcc="262" mnc="01" apn="web2" type="default" />\n</apns>\n')
        git(self.root, "commit", "-q", "-am", "head")
        self.sha = git(self.root, "rev-parse", "HEAD")
        self.stub = Path(self.tmp.name) / "stub_guard.py"
        self.stub.write_text(STUB_GUARD)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def dispatch(self, pulls: list) -> dict:
        api = FakeApi({f"repos/{REPO}/compare/main...{self.sha}": {"merge_base_commit": {"sha": self.base}}},
                      [pulls])
        return gc.resolve(env("workflow_dispatch", "refs/heads/feature", self.sha), {}, api, no_sleep)

    def test_dispatch_without_pull_request_runs_the_guard_and_fails(self) -> None:
        status, output = gc.run_guard(self.dispatch([]), self.root, self.stub)
        self.assertEqual(status, 1)
        self.assertIn("phone-level guard: STUB", output)
        self.assertIn(f"--base-ref\", \"{self.base}\"", output)
        self.assertIn(f"guard base: {self.base} (the merge base", output)
        self.assertIn("nothing is accepted", output)
        self.assertNotIn("--accept", output)

    def test_dispatch_with_the_pull_request_passes_with_its_accept(self) -> None:
        context = self.dispatch([pull(5, self.sha, f"phone-guard-accept: {DIGEST}")])
        status, output = gc.run_guard(context, self.root, self.stub)
        self.assertEqual(status, 0)
        self.assertIn(f"\"--accept\", \"{DIGEST}\"", output)
        self.assertIn("pull request #5, read at run time", output)

    def test_dispatch_without_pull_request_passes_when_unchanged(self) -> None:
        context = self.dispatch([])
        git(self.root, "checkout", "-q", self.base)
        status, output = gc.run_guard(context, self.root, self.stub)
        self.assertEqual(status, 0, output)

    def test_a_hold_stays_a_hold(self) -> None:
        context = self.dispatch([pull(5, self.sha, "")])
        os.environ["STUB_HOLD"] = "1"
        try:
            status, _output = gc.run_guard(context, self.root, self.stub)
        finally:
            del os.environ["STUB_HOLD"]
        self.assertEqual(status, 1)

    def test_merge_group_runs_the_guard_against_base_sha(self) -> None:
        ref = f"refs/heads/gh-readonly-queue/main/pr-12-{self.base}"
        event = {"merge_group": {"base_sha": self.base, "head_sha": self.sha, "head_ref": ref}}
        api = FakeApi({f"repos/{REPO}/pulls/12": pull(12, OTHER, f"phone-guard-accept: {DIGEST}")})
        context = gc.resolve(env("merge_group", ref, self.sha), event, api)
        status, output = gc.run_guard(context, self.root, self.stub)
        self.assertEqual(status, 0)
        self.assertIn(f"guard base: {self.base} (merge_group.base_sha)", output)
        self.assertIn(f"\"--accept\", \"{DIGEST}\"", output)

    def test_unreadable_base_fails_closed(self) -> None:
        context = self.dispatch([pull(5, self.sha, "")])
        context["base"] = "e" * 40
        status, output = gc.run_guard(context, self.root, self.stub)
        self.assertEqual(status, 2)
        self.assertNotIn("STUB", output)

    def test_cli_resolve_and_guard(self) -> None:
        context = self.dispatch([])
        path = Path(self.tmp.name) / "context.json"
        path.write_text(json.dumps(context))
        result = subprocess.run([sys.executable, str(Path(gc.__file__)), "guard", "--context", str(path),
                                 "--root", str(self.root), "--guard-script", str(self.stub)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("phone-level guard: STUB", result.stdout)


class Workflow(unittest.TestCase):
    """validate.yml wires every base-relative step to the resolved base."""

    def test_wiring(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  merge_group:\n    types: [checks_requested]\n", text)
        self.assertIn("python3 tools/guard_context.py resolve", text)
        self.assertIn("python3 tools/guard_context.py guard", text)
        self.assertIn("if: ${{ !cancelled() && github.ref != 'refs/heads/main' }}", text)
        self.assertNotIn("github.event.pull_request.base.sha", text)
        self.assertNotIn("github.event.pull_request.body", text)
        self.assertNotIn("if: github.event_name == 'pull_request'", text)
        self.assertEqual(text.count("${{ steps.context.outputs.base }}"), 3)
        # The F5 read check, the profile ID check and the two answers' check
        # (rule round 45, items 1 and 4) also run on a push to main, against
        # the commit before it.
        self.assertEqual(text.count("${{ steps.context.outputs.base || github.event.before }}"), 3)


if __name__ == "__main__":
    unittest.main()
