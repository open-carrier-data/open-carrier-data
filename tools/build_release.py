#!/usr/bin/env python3
"""Assemble the assets of a data release from one `main` commit, after its
gates (rule decisions of 2026-10-18, rounds 20 and 21).

usage: build_release.py --repo REPO --candidate SHA --base REF --tag TAG
       --state STATE_JSON --out DIR [--base-name NAME] [--today YYYY-MM-DD]
       [--rehearsal]

The candidate's tree is read with `git archive` into a temporary directory;
the repository's files are never touched. BASE is the previous release's tag
(for the first release, the commit it is compared with).

Gates. Any failure refuses the candidate:
- the state of the repository at the cut (STATE_JSON, which the release
  workflow gathers from GitHub): the candidate is on `main`, its `validate`
  check is green, no `publish-held` pull request and no `stale-data` issue
  is open, and no release or tag named TAG exists;
- the candidate is at least MIN_CANDIDATE_AGE old, except for the first
  release (AGE_WAIVER, round 24): only when STATE_JSON carries `first_base`,
  which the release workflow sets only while no `data-*` release exists, it
  equals BASE, and the repository has no `data-*` tag. `release.json` and the
  notes then record `age_gate: waived, round 24`;
- (a) the candidate's three validators pass with `--freshness fail`;
- (b) regenerating `generated/` from `carriers/` changes no byte;
- (c) `<apns version>` and `metadata.json` both name APN_DATABASE_VERSION,
  and `xmllint` accepts `apns-conf.xml` against LineageOS's `apns-conf.xsd`;
- (d) `stale_after` is at least MIN_DAYS_LEFT days after the cut;
- `carrier-variants.json` was built on the candidate's `data_digest`;
- (e) the phone guard from BASE to the candidate passes with no trip;
- (f) the notes carry every section of release_notes.REQUIRED_SECTIONS.

Publishing the draft is gate (g), the owner's. This tool never creates a
tag or a release.

Output, in DIR (which must be empty or absent): the four ASSETS, each
byte-identical to `git show CANDIDATE:PATH`, `release.json`,
`release-notes.md`, `release-body.md` (the notes, cut to fit a GitHub
release body when they are longer, the full notes being an asset) and
`SHA256SUMS` over the other files, which `sha256sum -c SHA256SUMS` checks.
Nothing is written when a gate fails, except with `--rehearsal`, which
writes everything with `"rehearsal": true` and the failed gates in
`release.json`. The release workflow never passes `--rehearsal`.

Exit 0 when every gate passes, 1 when one fails, 2 on any error.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import release_notes as notes  # noqa: E402

TAG_RE = re.compile(r"data-(?P<year>20[0-9]{2})\.(?P<month>0[1-9]|1[0-2])(?:\.(?P<fix>[1-9][0-9]*))?")
# Asset name, path in the tree, tier. apns-conf.xml becomes "supported" for
# ROMs only after the owner's S20 has built and booted a release once with
# its APN list loaded (round 20); a docs pull request then changes its tier
# here and in docs/releases.md.
ASSETS = (
    ("apns-conf.xml", "generated/android/apns-conf.xml", "rom, pending the S20 boot check"),
    ("lookup.json", "generated/android/lookup.json", "supported"),
    ("metadata.json", "generated/android/metadata.json", "supported"),
    ("carrier-variants.json", "generated/devices/carrier-variants.json", "supported as information"),
)
# In the tagged tree and in release.json, never an asset (round 20: not before
# the per-key safety review S1).
REFERENCE_FILES = (("generated/android/carrier-config-list.xml", "reference"),)
SCHEMAS = {
    "lookup.json": "schemas/android-lookup.schema.json",
    "metadata.json": "schemas/android-metadata.schema.json",
    "carrier-variants.json": "schemas/carrier-variants.schema.json",
}
MIN_CANDIDATE_AGE = timedelta(hours=72)
# Round 24: the first release may be younger than MIN_CANDIDATE_AGE. The
# waiver needs the state's `first_base`, which release.yml refuses once any
# data-* release exists, so it can fire for the first release only. It is not
# an input, does not touch the clock and skips no other gate.
AGE_WAIVER = "waived, round 24"
MIN_DAYS_LEFT = 30
APN_DATABASE_VERSION = 8
STATE_KEYS = ("candidate_on_main", "validate", "publish_held", "stale_data", "release_exists")
# GitHub refuses a release body over 125,000 characters.
BODY_LIMIT = 120_000


class ReleaseError(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_tag(tag: str) -> None:
    if not TAG_RE.fullmatch(tag):
        raise ReleaseError(f"tag {tag!r} is not data-YYYY.MM or data-YYYY.MM.N")


def state_refusals(state: dict[str, Any], commit_time: datetime, now: datetime) -> list[str]:
    """The repository-state gates. A missing key refuses: the gate fails closed."""
    missing = [key for key in STATE_KEYS if key not in state]
    if missing:
        return [f"the state lacks {', '.join(missing)}"]
    refusals = []
    if state["candidate_on_main"] is not True:
        refusals.append("the candidate is not a commit of main")
    if state["validate"] != "success":
        refusals.append(f"validate is not green on the candidate ({state['validate']})")
    if state["publish_held"]:
        refusals.append(f"publish-held pull request(s) open: {', '.join(f'#{n}' for n in state['publish_held'])}")
    if state["stale_data"]:
        refusals.append(f"stale-data issue(s) open: {', '.join(f'#{n}' for n in state['stale_data'])}")
    if state["release_exists"] is not False:
        refusals.append("a release or tag with this name exists")
    return refusals


def first_release_refusals(repo: Path, state: dict[str, Any], base: str) -> tuple[bool, list[str]]:
    """Whether this is the first release, which the age waiver needs: the
    state names `first_base` (release.yml sets it only while no data-*
    release exists), it is the base, and no data-* tag exists. A `first_base`
    that does not hold refuses the candidate."""
    first_base = state.get("first_base") or ""
    if not first_base:
        return False, []
    refusals = []
    if first_base != base:
        refusals.append(f"first_base {first_base} is not the base {base}")
    tags = notes.git(repo, "tag", "--list", "data-*").decode().split()
    if tags:
        refusals.append(f"first_base is set, but release tag(s) exist: {', '.join(tags)}")
    return not refusals, refusals


def age_gate(commit_time: datetime, now: datetime, first_release: bool) -> tuple[str, list[str]]:
    """The candidate is at least MIN_CANDIDATE_AGE old, or this is the first
    release (AGE_WAIVER). Returns what release.json records and the refusals."""
    age = now - commit_time
    if age >= MIN_CANDIDATE_AGE:
        return "passed", []
    if first_release:
        return AGE_WAIVER, []
    return "refused", [f"the candidate is {age.total_seconds() / 3600:.1f} hours old; it must be at least "
                       f"{MIN_CANDIDATE_AGE.total_seconds() / 3600:.0f}"]


def freshness_refusals(stale_after: str | None, today: date) -> list[str]:
    if not stale_after:
        return ["metadata.json has no stale_after"]
    left = (date.fromisoformat(stale_after) - today).days
    if left < MIN_DAYS_LEFT:
        return [f"stale_after {stale_after} is {left} days after {today}; it must be at least {MIN_DAYS_LEFT}"]
    return []


def guard_refusals(guard: dict[str, Any]) -> list[str]:
    """Gate (e): the guard from the previous release passes with no trip.
    An accepted trip on main does not carry over to the cumulative pair: a
    trip here needs a judged ruling before a release, not an input."""
    if guard.get("verdict") != "pass" or guard.get("trips"):
        return [f"the phone guard from the previous release is {str(guard.get('verdict')).upper()} with "
                f"{len(guard.get('trips', []))} trip(s), digest {guard.get('digest')}"]
    return []


def notes_refusals(text: str) -> list[str]:
    missing = [section for section in notes.REQUIRED_SECTIONS if f"\n{section}\n" not in text]
    return [f"the notes lack {', '.join(missing)}"] if missing else []


def run(command: list[str], cwd: Path) -> tuple[int, str]:
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes())
            for path in sorted(root.rglob("*")) if path.is_file()}


def tree_refusals(tree: Path, today: date | None) -> list[str]:
    """Gates (a) to (c) and the device-records digest on an extracted tree.
    Gate (b) runs last, because it regenerates files inside TREE."""
    refusals = []
    when = ["--today", today.isoformat()] if today else []
    python = sys.executable
    for command in (
        [python, "tools/validate_public_carrier_data.py", "carriers", "generated/index.json", "--freshness", "fail"],
        [python, "tools/validate_device_catalog.py", "generated/devices", "--freshness", "fail"],
        [python, "tools/validate_carrier_variants.py", ".", "--freshness", "fail", "--require"],
    ):
        code, output = run(command + when, tree)
        if code != 0:
            refusals.append(f"{command[1]} failed: {output.splitlines()[-1] if output else code}")
    metadata = notes.load_json(tree / "generated/android/metadata.json")
    version = metadata.get("target", {}).get("apn_database_version")
    xml_version = notes.ET.parse(tree / "generated/android/apns-conf.xml").getroot().get("version")
    if version != APN_DATABASE_VERSION or xml_version != str(APN_DATABASE_VERSION):
        refusals.append(f"the APN database version is {version} in metadata.json and {xml_version} in "
                        f"apns-conf.xml; the target is {APN_DATABASE_VERSION}")
    if shutil.which("xmllint") is None:
        refusals.append("xmllint is not installed")
    else:
        code, output = run(["xmllint", "--noout", "--schema", "tools/lineageos/apns-conf.xsd",
                            "generated/android/apns-conf.xml"], tree)
        if code != 0:
            refusals.append(f"xmllint rejects apns-conf.xml: {output.splitlines()[-1] if output else code}")
    variants = tree / "generated/devices/carrier-variants.json"
    if variants.exists() and notes.load_json(variants).get("based_on_data_digest") != metadata.get("data_digest"):
        refusals.append("carrier-variants.json was built on another data_digest")
    before = tree_hashes(tree / "generated")
    code, output = run([python, "tools/generate_android_outputs.py", "carriers", "generated",
                        "--apn-version", str(APN_DATABASE_VERSION)], tree)
    if code != 0:
        refusals.append(f"regeneration failed: {output.splitlines()[-1] if output else code}")
    elif tree_hashes(tree / "generated") != before:
        changed = sorted(set(before.items()) ^ set(tree_hashes(tree / "generated").items()))
        refusals.append(f"regeneration changes generated/: {sorted({name for name, _ in changed})}")
    return refusals


def file_entry(repo: Path, commit: str, path: str, tier: str, asset: str | None) -> dict[str, Any]:
    data = notes.git(repo, "show", f"{commit}:{path}")
    entry: dict[str, Any] = {"path": path, "tier": tier, "bytes": len(data), "sha256": sha256(data)}
    if asset:
        entry = {"asset": asset, **entry}
    if path.endswith(".json"):
        version = json.loads(data).get("schema_version")
        if version is not None:
            entry["schema_version"] = version
    schema = SCHEMAS.get(asset or "")
    if schema:
        try:
            entry["schema"] = {"path": schema, "sha256": sha256(notes.git(repo, "show", f"{commit}:{schema}"))}
        except notes.NotesError:
            entry["schema"] = None
    return entry


def manifest(repo: Path, commit: str, commit_time: datetime, tag: str, base_name: str, base: str,
             result: dict[str, Any], gates: list[str], rehearsal: bool, today: date,
             now: datetime, age: str) -> dict[str, Any]:
    head = result["head"]
    guard = result["guard"]
    leads = result["leads"]
    return {
        "schema_version": 1,
        "tag": tag,
        "commit": commit,
        "commit_date": commit_time.isoformat(),
        "previous": {"name": base_name, "commit": base},
        "cut_at": now.replace(microsecond=0).isoformat(),
        "rehearsal": rehearsal,
        "failed_gates": gates,
        "age_gate": age,
        "data_digest": head["data_digest"],
        "checks_through": head["checks_through"],
        "stale_after": head["stale_after"],
        "days_left": notes.days_left(head["stale_after"], today),
        "apn_database_version": head["apn_database_version"],
        "files": [file_entry(repo, commit, path, tier, asset) for asset, path, tier in ASSETS],
        "reference_files": [file_entry(repo, commit, path, tier, None) for path, tier in REFERENCE_FILES],
        "counts": head["counts"],
        "guard": {
            "verdict": guard["verdict"],
            "trips": guard.get("trips", []),
            "digest": guard.get("digest"),
            "watch": {condition: len({i["scope"] for i in guard.get("watch", []) if i["condition"] == condition})
                      for condition in sorted({i["condition"] for i in guard.get("watch", [])})},
        },
        "needs_review": result["needs_review"],
        "reset_to_default": leads["reset_to_default"],
        "lead_changes": leads["changes"],
        "profile_ids": {"added": result["profiles"]["added"], "removed": result["profiles"]["removed"]},
        "announced_changes": result["announced_changes"],
    }


def body_text(text: str, tag: str) -> str:
    if len(text) <= BODY_LIMIT:
        return text
    cut = text[:BODY_LIMIT].rsplit("\n", 1)[0]
    if cut.count("```") % 2:
        cut += "\n```"
    return cut + (f"\n\n**The notes are longer than a release body allows. `release-notes.md`, an asset of "
                  f"{tag}, has them in full.**\n")


def write_assets(repo: Path, commit: str, out: Path, release: dict[str, Any], text: str, tag: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for asset, path, _ in ASSETS:
        (out / asset).write_bytes(notes.git(repo, "show", f"{commit}:{path}"))
    (out / "release.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    (out / "release-notes.md").write_text(text, encoding="utf-8")
    (out / "release-body.md").write_text(body_text(text, tag), encoding="utf-8")
    names = [asset for asset, _, _ in ASSETS] + ["release.json", "release-notes.md"]
    (out / "SHA256SUMS").write_text(
        "".join(f"{sha256((out / name).read_bytes())}  {name}\n" for name in sorted(names)), encoding="utf-8")
    verify(repo, commit, out)


def verify(repo: Path, commit: str, out: Path) -> None:
    """Every asset equals `git show`, and SHA256SUMS checks."""
    for asset, path, _ in ASSETS:
        if (out / asset).read_bytes() != notes.git(repo, "show", f"{commit}:{path}"):
            raise ReleaseError(f"{asset} differs from {commit}:{path}")
    for line in (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if sha256((out / name).read_bytes()) != digest:
            raise ReleaseError(f"SHA256SUMS does not check for {name}")


def build(repo: Path, candidate: str, base_ref: str, tag: str, out: Path, state: dict[str, Any],
          base_name: str | None = None, today: date | None = None, now: datetime | None = None,
          rehearsal: bool = False, check_tree: bool = True) -> tuple[int, list[str]]:
    """Run the gates and, when they pass (or for a rehearsal), write the
    assets. Returns the exit code and the failed gates."""
    check_tag(tag)
    if out.exists() and any(out.iterdir()):
        raise ReleaseError(f"{out} is not empty")
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    commit = notes.resolve(repo, candidate)
    base = notes.resolve(repo, base_ref)
    commit_time = datetime.fromisoformat(notes.git(repo, "show", "-s", "--format=%cI", commit).decode().strip())
    failed = state_refusals(state, commit_time, now)
    first_release, refusals = first_release_refusals(repo, state, base)
    failed += refusals
    age, refusals = age_gate(commit_time, now, first_release)
    failed += refusals
    with tempfile.TemporaryDirectory() as tmp:
        base_tree, head_tree = Path(tmp) / "base", Path(tmp) / "head"
        notes.extract_files(repo, base, [f"{notes.ANDROID}/{name}" for name in notes.BASE_FILES], base_tree)
        notes.extract_tree(repo, commit, head_tree)
        result = notes.compute(base_tree, head_tree, notes.pull_request_titles(repo, base, commit),
                               notes.announced_changes(head_tree))
        failed += freshness_refusals(result["head"]["stale_after"], today)
        failed += guard_refusals(result["guard"])
        if check_tree:
            failed += tree_refusals(head_tree, today)
    name = f"{base_name or base_ref} ({base})"
    text = notes.render(result, tag + (" (rehearsal)" if rehearsal else ""), name, commit, today, age)
    failed += notes_refusals(text)
    if failed and not rehearsal:
        return 1, failed
    release = manifest(repo, commit, commit_time, tag, base_name or base_ref, base, result, failed, rehearsal,
                       today, now, age)
    write_assets(repo, commit, out, release, text, tag)
    return (1 if failed else 0), failed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--base", required=True, help="the previous release's tag, or for the first one its base commit")
    parser.add_argument("--base-name", help="how the notes name the base, for example a pull request")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--rehearsal", action="store_true", help="write the assets even when a gate fails")
    args = parser.parse_args(argv[1:])
    state = json.loads(args.state.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    code, failed = build(args.repo, args.candidate, args.base, args.tag, args.out, state, args.base_name,
                         args.today or now.date(), now, args.rehearsal)
    if failed:
        print(f"build_release: {'REHEARSAL, ' if args.rehearsal else ''}{len(failed)} gate(s) failed:")
        for line in failed:
            print(f"  {line}")
    else:
        print("build_release: every gate passed")
    if not failed or args.rehearsal:
        print(f"build_release: assets written to {args.out}")
    return code


def run_main(argv: list[str]) -> int:
    """main, with any error, including a SystemExit other than --help, as exit 2."""
    try:
        return main(argv)
    except SystemExit as exc:
        if exc.code == 0 and ("-h" in argv or "--help" in argv):
            return 0
        print(f"build_release: ERROR exit {exc.code}", file=sys.stderr)
        return 2
    except BaseException as exc:
        print(f"build_release: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run_main(sys.argv))
