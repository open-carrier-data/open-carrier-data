#!/usr/bin/env python3
"""Tests for digest_chain.py and the refresh bot's use of it."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import digest_chain as tool
import generate_android_outputs
from validate_carrier_variants import VARIANTS_PATH, canonical_bytes

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/refresh-generated.yml"
OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64
VARIANTS = {
    "based_on_data_digest": OLD,
    "description": "Configuration, not a test result. Größe",
    "profiles": {"open.00101.000000000000": {"volte": [{"state": "on", "devices": ["x"]}]}},
    "schema_version": 1,
}


def write_tree(root: Path, metadata: str, manifest: str, variants: dict | None) -> None:
    for path, data in ((tool.METADATA_PATH, {"data_digest": metadata}), (tool.MANIFEST_PATH, {"data_digest": manifest})):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(data), encoding="utf-8")
    if variants is not None:
        (root / VARIANTS_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / VARIANTS_PATH).write_bytes(canonical_bytes(variants))


class Base(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)


class Stamp(Base):
    def test_the_digest_moves_and_no_other_byte(self) -> None:
        write_tree(self.root, NEW, NEW, VARIANTS)
        before = (self.root / VARIANTS_PATH).read_bytes()
        self.assertEqual(tool.problems(self.root), [f"{VARIANTS_PATH}: names {OLD}, {tool.METADATA_PATH} names {NEW}"])
        self.assertTrue(tool.stamp(self.root))
        after = (self.root / VARIANTS_PATH).read_bytes()
        self.assertEqual(after, before.replace(OLD.encode(), NEW.encode()))
        self.assertEqual(after, canonical_bytes(json.loads(after)))
        self.assertEqual(tool.problems(self.root), [])

    def test_a_file_in_step_is_not_written(self) -> None:
        write_tree(self.root, OLD, OLD, VARIANTS)
        path = self.root / VARIANTS_PATH
        path.write_bytes(path.read_bytes() + b" ")  # would not survive a rewrite
        self.assertFalse(tool.stamp(self.root))
        self.assertTrue(path.read_bytes().endswith(b"\n "))

    def test_no_records_file_is_no_error(self) -> None:
        write_tree(self.root, NEW, NEW, None)
        self.assertFalse(tool.stamp(self.root))
        self.assertEqual(tool.problems(self.root), [])

    def test_a_bad_metadata_digest_stamps_nothing(self) -> None:
        for bad in ("", "sha256:xyz", OLD[:-1]):
            write_tree(self.root, bad, NEW, VARIANTS)
            with self.assertRaises(tool.DigestChainError):
                tool.stamp(self.root)
            self.assertEqual(json.loads((self.root / VARIANTS_PATH).read_bytes())["based_on_data_digest"], OLD)

    def test_a_records_file_without_the_field_is_refused(self) -> None:
        write_tree(self.root, NEW, NEW, {"profiles": {}})
        with self.assertRaises(tool.DigestChainError):
            tool.stamp(self.root)


class Check(Base):
    def test_a_stale_manifest_is_a_gap_that_stamping_does_not_hide(self) -> None:
        write_tree(self.root, NEW, OLD, VARIANTS)
        tool.stamp(self.root)
        self.assertEqual(tool.problems(self.root), [f"{tool.MANIFEST_PATH}: names {OLD}, {tool.METADATA_PATH} names {NEW}"])

    def test_the_command_exits_by_the_chain(self) -> None:
        def run(command: str) -> int:
            return subprocess.run(
                [sys.executable, str(ROOT / "tools/digest_chain.py"), command, "--root", str(self.root)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode

        write_tree(self.root, NEW, NEW, VARIANTS)
        self.assertEqual(run("check"), 1)
        self.assertEqual(run("stamp"), 0)
        self.assertEqual(run("check"), 0)
        (self.root / tool.METADATA_PATH).unlink()
        self.assertEqual(run("stamp"), 1)
        self.assertEqual(run("check"), 1)


class TheCheckout(unittest.TestCase):
    def test_the_published_tree_is_on_one_digest(self) -> None:
        self.assertEqual(tool.problems(ROOT), [])

    def test_the_tool_stays_out_of_the_digest(self) -> None:
        # Else a change here would move every published digest.
        self.assertNotIn("digest_chain.py", generate_android_outputs.DIGEST_TOOLS)

    def test_no_stamp_is_needed_on_the_published_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path in (tool.METADATA_PATH, tool.MANIFEST_PATH, VARIANTS_PATH):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, root / path)
            self.assertFalse(tool.stamp(root))


class RefreshBot(unittest.TestCase):
    """The workflow's script, as text: the bot has no other test bed, and its
    live runs need a push to main."""

    def setUp(self) -> None:
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def at(self, needle: str) -> int:
        self.assertEqual(self.text.count(needle), 1, needle)
        return self.text.index(needle)

    def test_the_chain_is_stamped_and_checked_before_anything_is_committed(self) -> None:
        generator = self.at("python3 tools/generate_android_outputs.py carriers generated")
        dataset = self.at("python3 tools/ocd_dataset.py generate --root .")
        stamped = self.at("python3 tools/digest_chain.py stamp --root .")
        checked = self.at("python3 tools/digest_chain.py check --root .")
        committed = self.at('git commit -q -m "Regenerate generated/ on main')
        self.assertLess(generator, stamped)
        self.assertLess(dataset, checked)
        self.assertLess(stamped, checked)
        self.assertLess(checked, committed)

    def test_a_stamp_or_check_that_fails_stops_the_bot_for_that_branch(self) -> None:
        for command in ("stamp", "check"):
            start = self.at(f"python3 tools/digest_chain.py {command} --root .")
            self.assertTrue(self.text[start:].split("\n", 2)[1].strip().startswith("|| finish stopped"), command)


if __name__ == "__main__":
    unittest.main()
