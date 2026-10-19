#!/usr/bin/env python3
"""build_release.py on a small git repository with a stand-in generator.
The tree gates (validators, regeneration, xmllint) run on the real data in
the release workflow's own rehearsal; here they are covered by refusal
units, and the repository build skips them."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import build_release as release
from test_release_notes import MMS, SOS, WEB, write_tree

GOOD_STATE = {"candidate_on_main": True, "validate": "success", "publish_held": [], "stale_data": [],
              "release_exists": False}
BLOCK = [('mcc="262" mnc="01"', {"carrier_volte_available_bool": "true"})]
PROFILES = {"open.26201.aaaaaaaaaaaa": {"volte": "supported"}}


def git(repo: Path, *args: str, when: str | None = "2026-10-20T00:00:00Z") -> str:
    """WHEN None leaves the commit dates to git: the real time."""
    env = {**{k: v for k, v in os.environ.items() if k not in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")},
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


class RepoCase(unittest.TestCase):
    """A repository with a base commit and a candidate commit."""

    def make_repo(self, base_rows: list[str], head_rows: list[str], stale_after: str = "2027-06-30",
                  when: str | None = "2026-10-20T00:00:00Z") -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        for rows, digest, title in ((base_rows, "a", "Update sanitized carrier data (#1)"),
                                    (head_rows, "b", "Add a generator rule (#2)")):
            for child in self.repo.iterdir():
                if child.name != ".git":
                    shutil.rmtree(child)
            write_tree(self.repo, rows, PROFILES, BLOCK, stale_after=stale_after, digest=digest)
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-q", "-m", title, when=when)
        self.base = git(self.repo, "rev-parse", "HEAD~1")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.out = Path(self.tmp.name) / "out"

    def build(self, state: dict | None = None, now: datetime | None = None, rehearsal: bool = False,
              tag: str = "data-2026.11") -> tuple[int, list[str]]:
        now = now or datetime(2026, 11, 2, 6, tzinfo=timezone.utc)
        return release.build(self.repo, self.head, self.base, tag, self.out, state or GOOD_STATE, "#1",
                             now.date(), now, rehearsal, check_tree=False)


class BuildTests(RepoCase):
    def test_assets_match_the_commit_and_checksums_check(self) -> None:
        self.make_repo([WEB, SOS], [WEB, SOS])
        code, failed = self.build()
        self.assertEqual((code, failed), (0, []))
        names = sorted(path.name for path in self.out.iterdir())
        self.assertEqual(names, sorted(["apns-conf.xml", "lookup.json", "metadata.json", "carrier-variants.json",
                                        "release.json", "release-notes.md", "release-body.md", "SHA256SUMS"]))
        for asset, path, _ in release.ASSETS:
            shown = subprocess.run(["git", "-C", str(self.repo), "show", f"{self.head}:{path}"],
                                   check=True, capture_output=True).stdout
            self.assertEqual((self.out / asset).read_bytes(), shown, asset)
        if shutil.which("sha256sum"):
            subprocess.run(["sha256sum", "--quiet", "-c", "SHA256SUMS"], cwd=self.out, check=True)
        manifest = json.loads((self.out / "release.json").read_text())
        self.assertEqual(manifest["commit"], self.head)
        self.assertEqual(manifest["previous"], {"name": "#1", "commit": self.base})
        self.assertEqual(manifest["data_digest"], "sha256:" + "b" * 64)
        self.assertEqual(manifest["days_left"], (date(2027, 6, 30) - date(2026, 11, 2)).days)
        self.assertEqual([f["asset"] for f in manifest["files"]], [a for a, _, _ in release.ASSETS])
        self.assertEqual(manifest["reference_files"][0]["path"], "generated/android/carrier-config-list.xml")
        self.assertNotIn("carrier-config-list.xml", names)
        self.assertEqual(manifest["guard"]["verdict"], "pass")
        self.assertFalse(manifest["rehearsal"])
        self.assertEqual(manifest["needs_review"], [])
        self.assertEqual(manifest["age_gate"], "passed")
        self.assertNotIn("age_gate", (self.out / "release-notes.md").read_text())
        # The repository is untouched: no change, no tag.
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "tag"), "")

    def test_lost_emergency_lead_marks_the_draft(self) -> None:
        self.make_repo([WEB, SOS], [WEB])
        code, _ = self.build()
        self.assertEqual(code, 0)
        manifest = json.loads((self.out / "release.json").read_text())
        self.assertEqual(len(manifest["needs_review"]), 1)
        self.assertTrue((self.out / "release-notes.md").read_text().split("\n## ")[1].startswith("Needs review"))

    def assert_refused(self, reason: str, **kwargs) -> None:
        code, failed = self.build(**kwargs)
        self.assertEqual(code, 1)
        self.assertTrue(any(reason in line for line in failed), failed)
        self.assertFalse(self.out.exists() and any(self.out.iterdir()), "a refused candidate wrote assets")

    def test_refusals(self) -> None:
        self.make_repo([WEB, MMS], [WEB, MMS])
        self.assert_refused("publish-held", state={**GOOD_STATE, "publish_held": [301]})
        self.assert_refused("stale-data", state={**GOOD_STATE, "stale_data": [12]})
        self.assert_refused("validate is not green", state={**GOOD_STATE, "validate": "failure"})
        self.assert_refused("validate is not green", state={**GOOD_STATE, "validate": "missing"})
        self.assert_refused("not a commit of main", state={**GOOD_STATE, "candidate_on_main": False})
        self.assert_refused("exists", state={**GOOD_STATE, "release_exists": True})
        self.assert_refused("the state lacks validate",
                            state={k: v for k, v in GOOD_STATE.items() if k != "validate"})
        self.assert_refused("hours old", now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
        self.assert_refused("must be at least 30", now=datetime(2027, 6, 5, tzinfo=timezone.utc))

    def test_untraced_trip_is_refused(self) -> None:
        self.make_repo([WEB, MMS], [WEB])
        self.assert_refused("phone guard from the previous release is HOLD")

    def test_rehearsal_writes_and_names_the_failed_gates(self) -> None:
        self.make_repo([WEB, MMS], [WEB])
        code, failed = self.build(rehearsal=True, state={**GOOD_STATE, "stale_data": [12]})
        self.assertEqual(code, 1)
        manifest = json.loads((self.out / "release.json").read_text())
        self.assertTrue(manifest["rehearsal"])
        self.assertEqual(manifest["failed_gates"], failed)
        self.assertEqual(len(failed), 2)
        self.assertIn("(rehearsal)", (self.out / "release-notes.md").read_text().splitlines()[0])

    def test_bad_tag_and_full_output_directory(self) -> None:
        self.make_repo([WEB], [WEB])
        for tag in ("data-2026.13", "data-26.11", "v1.0", "data-2026.11.0", "data-2026.11-rc"):
            with self.assertRaises(release.ReleaseError):
                self.build(tag=tag)
        code, _ = self.build(tag="data-2026.11.1")
        self.assertEqual(code, 0)
        with self.assertRaises(release.ReleaseError):
            self.build()


class FirstReleaseAgeWaiverTests(RepoCase):
    """Round 24: the age gate is waived only for the first release, when the
    state carries first_base. These run on the real clock: the candidate is
    committed now, so it is seconds old."""

    def setUp(self) -> None:
        self.make_repo([WEB, SOS], [WEB, SOS], stale_after="2099-12-31", when=None)

    def build_now(self, state: dict) -> tuple[int, list[str]]:
        return release.build(self.repo, self.head, self.base, "data-2026.10", self.out, state, "#1",
                             check_tree=False)

    def test_young_candidate_without_first_base_is_refused(self) -> None:
        for state in (GOOD_STATE, {**GOOD_STATE, "first_base": ""}):
            code, failed = self.build_now(state)
            self.assertEqual(code, 1)
            self.assertEqual(len(failed), 1, failed)
            self.assertIn("hours old; it must be at least 72", failed[0])
            self.assertFalse(self.out.exists() and any(self.out.iterdir()), "a refused candidate wrote assets")

    def test_first_base_waives_the_age_gate_and_records_it(self) -> None:
        code, failed = self.build_now({**GOOD_STATE, "first_base": self.base})
        self.assertEqual((code, failed), (0, []))
        manifest = json.loads((self.out / "release.json").read_text())
        self.assertEqual(manifest["age_gate"], "waived, round 24")
        self.assertEqual(manifest["age_gate"], release.AGE_WAIVER)
        self.assertEqual(manifest["failed_gates"], [])
        self.assertFalse(manifest["rehearsal"])
        notes_text = (self.out / "release-notes.md").read_text()
        self.assertIn("- `age_gate`: waived, round 24.", notes_text)
        self.assertIn("- `age_gate`: waived, round 24.", (self.out / "release-body.md").read_text())
        self.assertEqual(release.MIN_CANDIDATE_AGE, timedelta(hours=72))

    def test_first_base_waives_only_the_age_gate(self) -> None:
        code, failed = self.build_now({**GOOD_STATE, "first_base": self.base, "stale_data": [12]})
        self.assertEqual(code, 1)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("stale-data", failed[0])

    def test_first_base_other_than_the_base_is_refused(self) -> None:
        code, failed = self.build_now({**GOOD_STATE, "first_base": self.head})
        self.assertEqual(code, 1)
        self.assertTrue(any("is not the base" in line for line in failed), failed)
        self.assertTrue(any("hours old" in line for line in failed), failed)

    def test_first_base_once_a_release_tag_exists_is_refused(self) -> None:
        git(self.repo, "tag", "data-2026.10", self.base)
        code, failed = self.build_now({**GOOD_STATE, "first_base": self.base})
        self.assertEqual(code, 1)
        self.assertTrue(any("release tag(s) exist: data-2026.10" in line for line in failed), failed)
        self.assertTrue(any("hours old" in line for line in failed), failed)


class UnitTests(unittest.TestCase):
    def test_guard_refusals(self) -> None:
        self.assertEqual(release.guard_refusals({"verdict": "pass", "trips": []}), [])
        self.assertTrue(release.guard_refusals({"verdict": "accepted", "trips": [{}], "digest": "0" * 16}))
        self.assertTrue(release.guard_refusals({"verdict": "hold", "trips": [{}], "digest": "0" * 16}))

    def test_freshness_refusals(self) -> None:
        self.assertEqual(release.freshness_refusals("2026-12-02", date(2026, 11, 2)), [])
        self.assertTrue(release.freshness_refusals("2026-12-01", date(2026, 11, 2)))
        self.assertTrue(release.freshness_refusals(None, date(2026, 11, 2)))

    def test_candidate_age(self) -> None:
        when = datetime(2026, 10, 20, tzinfo=timezone.utc)
        self.assertEqual(release.age_gate(when, when + timedelta(hours=72), False), ("passed", []))
        self.assertEqual(release.age_gate(when, when + timedelta(hours=72), True), ("passed", []))
        status, refusals = release.age_gate(when, when + timedelta(hours=71), False)
        self.assertEqual(status, "refused")
        self.assertTrue(refusals)
        self.assertEqual(release.age_gate(when, when + timedelta(hours=71), True), ("waived, round 24", []))

    def test_notes_refusals(self) -> None:
        text = "\n" + "\n".join(f"{s}\n" for s in release.notes.REQUIRED_SECTIONS)
        self.assertEqual(release.notes_refusals(text), [])
        self.assertTrue(release.notes_refusals(text.replace("## Emergency APN rows", "## Other")))

    def test_long_body_is_cut_with_balanced_fences(self) -> None:
        text = "# T\n\n```\n" + "x" * 80 + "\n" + ("line\n" * 30_000) + "```\n"
        body = release.body_text(text, "data-2026.11")
        self.assertLessEqual(len(body), release.BODY_LIMIT + 300)
        self.assertEqual(body.count("```") % 2, 0)
        self.assertIn("release-notes.md", body)
        self.assertEqual(release.body_text("short", "t"), "short")


if __name__ == "__main__":
    unittest.main()
