#!/usr/bin/env python3
"""Release notes for a data release: what changed from the previous release
to the candidate (rule decisions of 2026-10-18, rounds 20 and 21).

usage: release_notes.py BASE_DIR HEAD_DIR [--tag TAG] [--base-name NAME]
       [--out PATH] [--json PATH] [--today YYYY-MM-DD]
       release_notes.py --repo REPO BASE_REF HEAD_REF [...]

BASE_DIR needs the four files under `generated/android/`; HEAD_DIR is a full
tree of the candidate, because the phone guard reads its generator and its
profiles. With `--repo`, the two refs are read from that git repository into
temporary trees; the repository's files are not touched.

The notes have these sections, in this order:
- "Needs review", only when an emergency lead is lost to Android's default,
  a network type is left without an emergency profile, or an APN set leaves
  a scope without one (round 21). The owner reads them before publishing;
- the window (`checks_through`, `stale_after`, days left) and the counts;
- the phone guard (`check_phone_guard.py`, run as a program): verdict, trips,
  digest and its report lines;
- IMS leads and emergency-named leads, every line, LTE, NR and IWLAN first;
- emergency APN rows: rows, omissions by reason, and every gained, lost and
  changed emergency lead with its label, never cut;
- internet, attach and MMS lead changes on the 7 hold types (counts, then up
  to LEAD_LIST_LIMIT lines each) and the "Reset to default" scopes;
- capability value changes, as counts;
- CarrierConfig (`diff_carrier_config.py`): the safety class in full, every
  other key as counts;
- profile IDs added and removed per MCC/MNC (counts; the full lists are in
  the JSON and in `release.json`);
- the pull requests in between, announced changes and the standing notice.

Exit 0 after writing the notes, 2 on any error (the guard failing included).
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import android_phone_model as phone  # noqa: E402
import check_phone_guard as guard  # noqa: E402
import diff_carrier_config  # noqa: E402

ANDROID = "generated/android"
BASE_FILES = ("apns-conf.xml", "carrier-config-list.xml", "lookup.json", "metadata.json")
LEAD_LIST_LIMIT = 50
EMERGENCY_OMISSIONS = (
    "emergency_types_left_out_unset_protocol",
    "emergency_types_left_out_combined",
    "emergency_types_left_out_not_vendor_stated",
    "emergency_types_left_out_apn_set",
)
IMS_CONDITIONS = ("ims lead", "emergency-named APN")
# Headings build_release.py requires (gate f).
REQUIRED_SECTIONS = (
    "## Phone guard",
    "## IMS leads",
    "## Emergency APN rows",
    "## CarrierConfig",
    "## Profile IDs",
)


class NotesError(Exception):
    pass


# Reading the files.

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def apn_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    rows = root.findall("apn")
    return {
        "apn_rows": len(rows),
        "emergency_rows": sum(1 for row in rows if "emergency" in row.get("type", "").split(",")),
    }


def config_counts(path: Path) -> dict[str, int]:
    """Blocks, key lines and safety-class lines of carrier-config-list.xml,
    as written (a key written twice counts twice)."""
    root = ET.parse(path).getroot()
    blocks = root.findall("carrier_config")
    names = [element.get("name") or "" for block in blocks for element in block]
    return {
        "carrier_config_blocks": len(blocks),
        "carrier_config_key_lines": len(names),
        "safety_class_lines": sum(1 for name in names if diff_carrier_config.safety_class(name)),
    }


def tree_counts(tree: Path) -> dict[str, Any]:
    android = tree / ANDROID
    metadata = load_json(android / "metadata.json")
    omissions = metadata.get("omissions", {})
    return {
        "profiles": len(load_json(android / "lookup.json")["profiles"]),
        **apn_counts(android / "apns-conf.xml"),
        "emergency_omissions": {key: omissions.get(key) for key in EMERGENCY_OMISSIONS},
        **config_counts(android / "carrier-config-list.xml"),
    }


# The comparisons.

def run_guard(base_xml: Path, head_xml: Path, head_tree: Path) -> dict[str, Any]:
    """check_phone_guard.py as a program, so that the notes print exactly what
    the guard decides. Exit 2, or no JSON, is an error."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "guard.json"
        done = subprocess.run(
            [sys.executable, str(TOOLS / "check_phone_guard.py"), str(base_xml), str(head_xml),
             "--generator", str(head_tree), "--report-json", str(report)],
            capture_output=True, text=True,
        )
        if done.returncode not in (0, 1) or not report.exists():
            raise NotesError(f"the phone guard failed (exit {done.returncode}): {done.stderr.strip()}")
        result = load_json(report)
    result["exit"] = done.returncode
    return result


def lead_changes(base_xml: Path, head_xml: Path) -> dict[str, Any]:
    """Internet, attach and MMS lead APN changes (case-folded) per scope on
    the 7 hold types, read through the phone model, and the scopes only one
    file has."""
    before, _ = phone.phone_state(guard.read_rows(base_xml), guard.HOLD_TYPES)
    after, _ = phone.phone_state(guard.read_rows(head_xml), guard.HOLD_TYPES)
    found: dict[str, dict[tuple[str, str, str], list[str]]] = {
        "internet": defaultdict(list), "attach": defaultdict(list), "MMS": defaultdict(list)}
    for scope in sorted(set(before) & set(after)):
        for name in guard.HOLD_TYPES:
            old_state, new_state = before[scope][name], after[scope][name]
            for role, index in (("internet", 0), ("attach", 2), ("MMS", 4)):
                old, new = old_state[index], new_state[index]
                old_apn = None if old is None else str(old[0])
                new_apn = None if new is None else str(new[0])
                if (old_apn or "").casefold() != (new_apn or "").casefold() or (old is None) != (new is None):
                    found[role][(guard.fmt(scope), old_apn or "none", new_apn or "none")].append(name)
    changes = {
        role: [{"scope": s, "old": o, "new": n, "types": types} for (s, o, n), types in sorted(items.items())]
        for role, items in found.items()
    }
    reset = sorted({item["scope"] for role in ("internet", "attach") for item in changes[role]})
    return {
        "changes": changes,
        "reset_to_default": reset,
        "scopes_added": sorted(guard.fmt(s) for s in set(after) - set(before)),
        "scopes_removed": sorted(guard.fmt(s) for s in set(before) - set(after)),
    }


def profile_changes(base_lookup: dict[str, Any], head_lookup: dict[str, Any]) -> dict[str, Any]:
    old = {p["profile_id"]: p for p in base_lookup["profiles"]}
    new = {p["profile_id"]: p for p in head_lookup["profiles"]}
    transitions: Counter = Counter()
    for profile_id in set(old) & set(new):
        before, after = old[profile_id].get("capabilities", {}), new[profile_id].get("capabilities", {})
        for key in set(before) | set(after):
            if before.get(key) != after.get(key):
                transitions[(key, before.get(key, "absent"), after.get(key, "absent"))] += 1
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "kept": len(set(old) & set(new)),
        "capability_changes": [
            {"capability": k, "old": o, "new": n, "profiles": c} for (k, o, n), c in sorted(transitions.items())
        ],
    }


def carrier_config_changes(base_xml: Path, head_xml: Path) -> dict[str, Any]:
    old, new = diff_carrier_config.read_blocks(base_xml), diff_carrier_config.read_blocks(head_xml)
    changes = diff_carrier_config.compare(old, new)
    return {"summary": diff_carrier_config.summary(old, new, changes),
            "safety_class_changes": sum(1 for item in changes if item["safety_class"]),
            "changes": len(changes)}


def is_gap(item: dict[str, Any]) -> bool:
    """An emergency lead line whose new value is no profile at all."""
    return item["new"].endswith("[network-type gap]")


def needs_review(watch: list[dict[str, Any]]) -> list[str]:
    """Round 21: a lost emergency lead puts the draft under "needs review".
    A network type or an APN set left with no emergency profile at all is the
    same phone outcome or worse, so it does too, and so does a gained or
    changed lead that is not equal to Android's default."""
    def scopes(items: list[dict[str, Any]]) -> int:
        return len({item["scope"] for item in items})

    lost = [i for i in watch if i["condition"] == "emergency lead lost"]
    gaps = [i for i in watch if i["condition"].startswith("emergency lead") and is_gap(i)]
    stranded = [i for i in watch if i["condition"].startswith("emergency profile missing under APN set")]
    # Correctness judge, round 20/21: a gained or changed emergency lead that
    # differs from Android's default (any label but `equal`) is also reviewed.
    moved = [i for i in watch if i["condition"] in ("emergency lead gained", "emergency lead changed")
             and not is_gap(i) and "[equal]" not in i["new"]]
    reasons = []
    if lost:
        reasons.append(f"emergency lead lost to Android's default (sos IPV4V6/IPV4V6): {scopes(lost)} scope(s)")
    if gaps:
        reasons.append(f"a network type left with no emergency profile: {scopes(gaps)} scope(s)")
    if moved:
        reasons.append(f"an emergency lead gained or changed away from Android's default: {scopes(moved)} scope(s)")
    if stranded:
        reasons.append(f"an APN set that leaves no emergency profile: {scopes(stranded)} scope(s)")
    return reasons


def compute(base: Path, head: Path, pull_requests: list[str] | None = None,
            announced: list[str] | None = None) -> dict[str, Any]:
    b, h = base / ANDROID, head / ANDROID
    for name in BASE_FILES:
        for tree in (b, h):
            if not (tree / name).is_file():
                raise NotesError(f"{tree / name} is missing")
    guard_result = run_guard(b / "apns-conf.xml", h / "apns-conf.xml", head)
    watch = guard_result.get("watch", [])
    base_meta, head_meta = load_json(b / "metadata.json"), load_json(h / "metadata.json")
    return {
        "base": {"data_digest": base_meta.get("data_digest"), "stale_after": base_meta.get("stale_after"),
                 "checks_through": base_meta.get("checks_through"), "counts": tree_counts(base)},
        "head": {"data_digest": head_meta.get("data_digest"), "stale_after": head_meta.get("stale_after"),
                 "checks_through": head_meta.get("checks_through"),
                 "apn_database_version": head_meta.get("target", {}).get("apn_database_version"),
                 "counts": tree_counts(head)},
        "guard": guard_result,
        "needs_review": needs_review(watch),
        "leads": lead_changes(b / "apns-conf.xml", h / "apns-conf.xml"),
        "profiles": profile_changes(load_json(b / "lookup.json"), load_json(h / "lookup.json")),
        "carrier_config": carrier_config_changes(b / "carrier-config-list.xml", h / "carrier-config-list.xml"),
        "pull_requests": pull_requests or [],
        "announced_changes": announced or [],
    }


# The text.

def first_lte(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (not set(item["types"]) & set(guard.WATCH_FIRST), item["scope"]))


def watch_block(items: list[dict[str, Any]]) -> list[str]:
    """Every item, one line each, per condition: never cut (round 21)."""
    lines: list[str] = []
    for condition in sorted({item["condition"] for item in items}):
        mine = first_lte([item for item in items if item["condition"] == condition])
        lines.append(f"{condition}: {len({item['scope'] for item in mine})} scope(s)")
        lines.extend(f"  {item['scope']}: {item['old']} -> {item['new']} ({','.join(item['types'])})"
                     for item in mine)
    return lines


def code(lines: list[str]) -> list[str]:
    return ["```", *(lines or ["(none)"]), "```"]


def labels_of(text: str) -> list[str]:
    found = re.search(r"\[([^\]]*)\]$", text)
    return [label.strip() for label in found.group(1).split(",")] if found else []


def days_left(stale_after: str | None, today: date) -> int | None:
    return None if not stale_after else (date.fromisoformat(stale_after) - today).days


def render(result: dict[str, Any], tag: str, base_name: str, head_name: str, today: date,
           age_gate: str | None = None) -> str:
    """AGE_GATE is build_release.py's verdict; the notes name it only when the
    gate did not simply pass (the round 24 waiver of the first release)."""
    head, base, g = result["head"], result["base"], result["guard"]
    watch = g.get("watch", [])
    out: list[str] = [f"# Open Carrier Data {tag}", ""]
    out += [f"- Commit: `{head_name}`", f"- Previous: `{base_name}`",
            f"- `data_digest`: `{head['data_digest']}`",
            f"- APN database version: {head.get('apn_database_version')}"]
    if age_gate and age_gate.startswith("waived"):
        out.append(f"- `age_gate`: {age_gate}. The candidate is younger than 72 hours. The age gate is waived "
                   "only for the first release, whose base is `first_base`; every later release must pass it.")
    elif age_gate and age_gate != "passed":
        out.append(f"- `age_gate`: {age_gate}")
    out.append("")
    out += ["Configured, not verified: no value was checked on a phone, and OCD never tests or places an "
            "emergency call. See \"Standing notice\" at the end.", ""]

    if result["needs_review"]:
        out += ["## Needs review", "",
                "The owner reads these before publishing the draft (gate g); the lines are listed in full "
                "under \"Emergency APN rows\".", ""]
        out += [f"- {reason}" for reason in result["needs_review"]] + [""]

    left = days_left(head["stale_after"], today)
    out += ["## Window and counts", "",
            f"`checks_through` {head['checks_through']}, `stale_after` {head['stale_after']}"
            + (f": {left} days after {today.isoformat()}." if left is not None else "."), "",
            "| Count | Previous | This release |", "| --- | ---: | ---: |"]
    for key in ("profiles", "apn_rows", "emergency_rows", "carrier_config_blocks", "carrier_config_key_lines",
                "safety_class_lines"):
        out.append(f"| {key} | {base['counts'].get(key)} | {head['counts'].get(key)} |")
    out.append("")

    out += ["## Phone guard", "",
            f"Verdict from the previous release to this one: **{g['verdict'].upper()}**, "
            f"{len(g.get('trips', []))} trip(s)" + (f", digest `{g['digest']}`." if g.get("digest") else "."), ""]
    out += code([guard.trip_line(trip) for trip in g.get("trips", [])] + [f"report: {line}" for line in g.get("report", [])])
    out.append("")

    ims = [item for item in watch if item["condition"].startswith(IMS_CONDITIONS)]
    out += ["## IMS leads", "",
            "The `ims` lead per scope and network type (the 7 hold types and IWLAN), and emergency-named APNs that "
            "become an internet or attach lead. Report only; every line.", ""]
    out += code(watch_block(ims)) + [""]

    emergency = [item for item in watch if item["condition"].startswith("emergency lead")
                 or item["condition"].startswith("emergency profile missing")]
    hc, bc = head["counts"], base["counts"]
    out += ["## Emergency APN rows", "",
            f"Rows typed `emergency` in `apns-conf.xml`: {bc['emergency_rows']} -> {hc['emergency_rows']}. "
            "A scope with no such row gets Android's own `sos` IPV4V6/IPV4V6 profile. The rule that decides "
            "which rows stay is round 21's (S1-A).", "",
            "| Emergency types left out (`metadata.json` omissions) | Previous | This release |",
            "| --- | ---: | ---: |"]
    for key in EMERGENCY_OMISSIONS:
        values = [counts["emergency_omissions"].get(key) for counts in (bc, hc)]
        out.append(f"| `{key}` | " + " | ".join("n/a" if v is None else str(v) for v in values) + " |")
    per_condition = Counter(item["condition"] for item in emergency)
    labels = Counter(label for item in emergency if item["condition"] in ("emergency lead gained",
                                                                           "emergency lead changed")
                     for label in labels_of(item["new"]))
    ipv4 = [item for item in emergency if "IPv4 only" in labels_of(item["new"])]
    gaps = [item for item in emergency if is_gap(item)]
    out += ["", "Emergency lead lines (scope and value changes): "
            + (", ".join(f"{c} {n}" for c, n in sorted(per_condition.items())) or "none") + ".",
            "Labels of gained and changed leads against Android's default: "
            + (", ".join(f"{label} {n}" for label, n in sorted(labels.items())) or "none") + ".",
            f"New IPv4-only leads: {len(ipv4)}. Network-type gaps: {len(gaps)}.", ""]
    out += code(watch_block(emergency)) + [""]

    leads = result["leads"]
    out += ["## Internet, attach and MMS leads", "",
            "Lead APN changes on the 7 hold types, read through Android's TelephonyProvider and "
            "DataProfileManager as `android_phone_model.py` models them. A phone keeps its preferred APN "
            "across an update; the new order applies to a new SIM or after \"Reset to default\".", ""]
    for role in ("internet", "attach", "MMS"):
        items = leads["changes"][role]
        out.append(f"{role}: {len({item['scope'] for item in items})} scope(s)")
    out.append(f"scopes added: {len(leads['scopes_added'])}, removed: {len(leads['scopes_removed'])}")
    out.append("")
    lines: list[str] = []
    for role in ("internet", "attach", "MMS"):
        items = leads["changes"][role]
        if not items:
            continue
        lines.append(f"{role} lead changed:")
        lines += [f"  {i['scope']}: {i['old']} -> {i['new']} ({','.join(i['types'])})"
                  for i in items[:LEAD_LIST_LIMIT]]
        if len(items) > LEAD_LIST_LIMIT:
            lines.append(f"  ... {len(items) - LEAD_LIST_LIMIT} more (release.json lists them all)")
    out += code(lines) + [""]
    reset = leads["reset_to_default"]
    out += [f"\"Reset to default\" brings the new internet or attach lead on {len(reset)} scope(s)"
            + (": " + ", ".join(reset[:LEAD_LIST_LIMIT]) if reset else "")
            + (f" and {len(reset) - LEAD_LIST_LIMIT} more (release.json lists them all)."
               if len(reset) > LEAD_LIST_LIMIT else "."), ""]

    profiles = result["profiles"]
    out += ["## Capability values", "",
            f"Value changes on the {profiles['kept']} profile IDs both releases have, as counts:", ""]
    out += code([f"{c['capability']}: {c['old']} -> {c['new']}: {c['profiles']}"
                 for c in profiles["capability_changes"]]) + [""]

    out += ["## CarrierConfig", "",
            "`carrier-config-list.xml` is a reference file, not supported for ROM application and not a release "
            "asset; its SHA-256 is in `release.json`. The safety class (emergency, e911, ecbm, WPS, TTY, RTT, "
            "`iwlan.*`) in full, every other key as counts:", ""]
    out += code(result["carrier_config"]["summary"]) + [""]

    added, removed = Counter(), Counter()
    for profile_id in profiles["added"]:
        added[profile_id.split(".")[1]] += 1
    for profile_id in profiles["removed"]:
        removed[profile_id.split(".")[1]] += 1
    out += ["## Profile IDs", "",
            f"{len(profiles['added'])} added and {len(profiles['removed'])} removed. A profile ID is a hash of the "
            "match set and changes when the match set does; key what you store by the SIM's facts and the "
            "release ([compatibility.md](https://github.com/open-carrier-data/open-carrier-data/blob/main/docs/"
            "compatibility.md)). `release.json` lists every ID.", ""]
    if added or removed:
        out += ["| MCC/MNC | Added | Removed |", "| --- | ---: | ---: |"]
        out += [f"| {code_} | {added[code_]} | {removed[code_]} |" for code_ in sorted(set(added) | set(removed))]
        out.append("")

    publishes = sum(1 for title in result["pull_requests"] if title.startswith("Update sanitized carrier data"))
    others = [title for title in result["pull_requests"] if not title.startswith("Update sanitized carrier data")]
    out += ["## Pull requests", "", f"{publishes} data publish(es), and:", ""]
    out += [f"- {title}" for title in others] or ["- none"]
    out.append("")

    out += ["## Announced changes", ""]
    out += [f"- {line}" for line in result["announced_changes"]] or ["None."]
    out.append("")

    out += ["## Standing notice", "",
            "- Values are configured, not verified: every value comes from a vendor or ROM table, and no profile "
            "was checked on a phone. A capability label says what tables configure, not what the operator, the "
            "plan or the phone model allows.",
            "- OCD never tests or places an emergency call. Switching VoLTE or Wi-Fi calling on changes how "
            "emergency calls are placed; where there is no 2G or 3G voice, or PTS or ACMA rules apply, confirm "
            "that your IMS stack places them over IMS.",
            "- `carrier-config-list.xml` is not for ROM application before its per-key safety review.",
            "- Keep `<apns version>` equal to your framework's `apns.xml`; a mismatch loads no APN at all.",
            "- Check `SHA256SUMS`, and do not ship after `stale_after`.",
            "- `profile_id` values change when match sets change.",
            "- There is no service level: one maintainer and one self-hosted runner.",
            ""]
    return "\n".join(out)


# Reading git refs.

def git(repo: Path, *args: str) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if done.returncode != 0:
        raise NotesError(f"git {' '.join(args)}: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def resolve(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()


def extract_files(repo: Path, commit: str, paths: list[str], dest: Path) -> None:
    for path in paths:
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git(repo, "show", f"{commit}:{path}"))


def extract_tree(repo: Path, commit: str, dest: Path) -> None:
    """The commit's tree, through `git archive`, into DEST."""
    import tarfile

    dest.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", commit],
                          stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(dest, filter="data")
    if proc.returncode != 0:
        raise NotesError(f"git archive {commit} failed")


def pull_request_titles(repo: Path, base: str, head: str) -> list[str]:
    text = git(repo, "log", "--first-parent", "--reverse", "--format=%s", f"{base}..{head}").decode()
    return [line for line in text.splitlines() if line]


def announced_changes(tree: Path) -> list[str]:
    """The items under "## Announced changes" in docs/compatibility.md."""
    path = tree / "docs" / "compatibility.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    found = re.search(r"^## Announced changes\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not found:
        return []
    return [line[2:].strip() for line in found.group(1).splitlines() if line.startswith("- ")]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--repo", type=Path, help="read BASE and HEAD as refs of this git repository")
    parser.add_argument("--tag", default="data-YYYY.MM (draft)")
    parser.add_argument("--base-name")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--today", type=date.fromisoformat)
    args = parser.parse_args(argv[1:])
    today = args.today or datetime.now(timezone.utc).date()
    with tempfile.TemporaryDirectory() as tmp:
        if args.repo:
            base_commit, head_commit = resolve(args.repo, args.base), resolve(args.repo, args.head)
            base_tree, head_tree = Path(tmp) / "base", Path(tmp) / "head"
            extract_files(args.repo, base_commit, [f"{ANDROID}/{name}" for name in BASE_FILES], base_tree)
            extract_tree(args.repo, head_commit, head_tree)
            prs = pull_request_titles(args.repo, base_commit, head_commit)
            base_name, head_name = f"{args.base_name or args.base} ({base_commit})", head_commit
        else:
            base_tree, head_tree = Path(args.base), Path(args.head)
            prs, base_name, head_name = [], args.base_name or args.base, args.head
        result = compute(base_tree, head_tree, prs, announced_changes(head_tree))
        text = render(result, args.tag, base_name, head_name, today)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


def run(argv: list[str]) -> int:
    """main, with any error, including a SystemExit other than --help, as exit 2."""
    try:
        return main(argv)
    except SystemExit as exc:
        if exc.code == 0 and ("-h" in argv or "--help" in argv):
            return 0
        print(f"release notes: ERROR exit {exc.code}", file=sys.stderr)
        return 2
    except BaseException as exc:
        print(f"release notes: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv))
