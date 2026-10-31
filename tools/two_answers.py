#!/usr/bin/env python3
"""Two answers per feature (rule round 45, item 4): depends_on and for_you.

A profile's `capabilities` stay what they are: the configure answer, what the
phone should be set up to try, byte-identical (the rename to `configure`
waits for the full rewrite of a later step). Two sibling maps join them:

- `depends_on`, only for a capability whose value is `conditional`: why the
  value is not single. `device` where generated/devices/carrier-variants.json
  records an on and an off on different devices of one software stack,
  `firmware` where it records one device on and off under different stacks
  (its own firmware against a LineageOS or AOSP tree), `sources_disagree`
  where the evidence index records a conflict of source families, and
  `sources_disagree` alone where nothing records another basis. `ims_stack`
  needs a record keyed by IMS stack that backs a capability; none does yet.
- `for_you`, only where an admitted statement that has not lapsed
  (generated/operators/statements.json) gives a state: whether this
  customer has the feature, as the brand states it. `ended` gives `ended`,
  `not_offered` gives `not_offered`, `offered` gives `depends_on_plan`;
  `included`, `free_option` and `paid_option` come only from a statement
  whose status says exactly that. A network-wide statement reaches every
  profile all of whose network codes it names. A brand's statement reaches a
  profile only when the carrier-identity table maps that profile to that
  brand alone: the profile has a selector, only that brand's entry lists it,
  and no other entry's selector shares its SIMs without being narrower. On a
  network where host-only brands ride (no source gives them a selector, so
  no phone tells their SIMs from the host's), the plain profile gets at most
  `depends_on_plan` with the reason `brand_not_tellable` and the brands'
  names, never the host's or one brand's own state or option text. A
  missing `for_you` means unknown. Nothing here comes from a single SIM, an
  account read or a field record, and nothing here feeds `capabilities`,
  CarrierConfig, APN rows, the OCD dataset or a test decision.

The private publisher derives both with this module, in the device-records
step, and writes them into the profile files; the generator copies them into
generated/android/lookup.json.

Subcommands:

  derive --root DIR [--json FILE]
      Print the counts (and write every value) this module derives from the
      published files of ROOT.
  check --root DIR [--base-ref SHA | --base-root DIR]
      Every profile's depends_on and for_you are exactly what this module
      derives from ROOT's published files; lookup.json repeats them. Against
      a base: a tree whose base carries them carries them too, and a profile
      whose for_you or depends_on changed while its capability evidence did
      not keeps its capabilities byte-identical.

Only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Any

import profile_ids

CAPABILITY_OF_SERVICE = {
    "mms": "mms",
    "volte": "volte",
    "vonr": "vonr",
    "wifi_calling": "vowifi",
    "wifi_calling_abroad": "wifi_calling_roaming",
    "esim": "esim",
}
REASONS = ("sources_disagree", "device", "firmware", "ims_stack")
STATES = ("included", "free_option", "paid_option", "not_offered", "ended", "depends_on_plan")
STATE_OF_STATUS = {
    "ended": "ended",
    "not_offered": "not_offered",
    "offered": "depends_on_plan",
    "included": "included",
    "free_option": "free_option",
    "paid_option": "paid_option",
}
BRAND_NOT_TELLABLE = "brand_not_tellable"
FIELDS = ("depends_on", "for_you")
STATEMENTS = "generated/operators/statements.json"
IDENTITY = "generated/operators/carrier-identity.json"
EVIDENCE = "generated/evidence-index.json"
VARIANTS = "generated/devices/carrier-variants.json"
LOOKUP = "generated/android/lookup.json"


class TwoAnswersError(Exception):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TwoAnswersError(f"{path}: cannot be read ({exc})") from exc


def dump_profile(profile: dict[str, Any]) -> str:
    """A profile file as the sanitizer writes it."""
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------- depends_on


def device_reasons(records: list[dict[str, Any]]) -> set[str]:
    """device and firmware from one capability's device records."""
    by_stack: dict[str, set[str]] = {}
    by_device: dict[str, set[str]] = {}
    for record in records:
        state = str(record.get("state"))
        by_stack.setdefault(str(record.get("stack")), set()).add(state)
        for device in record.get("devices", []):
            by_device.setdefault(str(device), set()).add(state)
    out = set()
    if any(len(states) > 1 for states in by_stack.values()):
        out.add("device")
    if any(len(states) > 1 for states in by_device.values()):
        out.add("firmware")
    return out


def depends_on_of(profile: dict[str, Any], evidence: dict[str, Any] | None,
                  variants: dict[str, list[dict[str, Any]]] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    conflicts = {
        item.get("key") for item in (evidence or {}).get("conflicts", [])
        if isinstance(item, dict) and item.get("section") == "capabilities" and item.get("kind") == "conflict"
    }
    for key, value in sorted((profile.get("capabilities") or {}).items()):
        if value != "conditional":
            continue
        reasons = device_reasons((variants or {}).get(key, []))
        if key in conflicts:
            reasons.add("sources_disagree")
        out[key] = sorted(reasons or {"sources_disagree"})
    return out


# ---------------------------------------------------------------- for_you


def live_statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The published statements that state something: admitted (only those
    are published), not lapsed, a status other than unknown, about a feature
    OCD has a capability for."""
    return [
        s for s in document.get("statements", [])
        if isinstance(s, dict) and "lapsed" not in s and s.get("status") in STATE_OF_STATUS
        and s.get("service") in CAPABILITY_OF_SERVICE and s.get("scope") in ("network", "brand")
    ]


class Identity:
    """The carrier-identity table, as for_you reads it."""

    def __init__(self, document: dict[str, Any], live: dict[str, dict[str, Any]]) -> None:
        self.entries = [e for e in document.get("entries", []) if isinstance(e, dict)]
        self.listing: dict[str, list[dict[str, Any]]] = {}
        self.selectors: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for entry in self.entries:
            for selector in entry.get("selectors", []):
                pid = selector.get("profile_id")
                if pid in live:
                    self.listing.setdefault(pid, []).append(entry)
                    self.selectors.append((entry, live[pid]))
        self.host_only = [e for e in self.entries if e.get("host_only")]

    def host_only_on(self, codes: list[str]) -> list[dict[str, Any]]:
        return [e for e in self.host_only if set(codes) & set(e.get("host_networks", []))]

    def brand_alone(self, profile_id: str, match: dict[str, Any]) -> dict[str, Any] | None:
        """The one entry the table maps this profile to, or None: the profile
        has a selector, only that entry lists it, and no other entry has a
        selector on the same selectors that shares some of its SIMs while
        being neither narrower (whose SIMs get that narrower profile) nor
        wider (whose SIMs that also match this profile get this one). A SIM
        such a crossing rule also matches could be either brand's at equal
        specificity, so neither brand's statement may speak for it (congstar
        and fraenk share GID1 44). A rule on other selectors does not count:
        whether a SIM matches both depends on fields neither rule names."""
        if not any(match.get(key) for key in profile_ids.SELECTOR_KEYS):
            return None
        listing = {e["key"]: e for e in self.listing.get(profile_id, [])}
        if len(listing) != 1:
            return None
        [entry] = listing.values()
        for other, rule in self.selectors:
            if other["key"] == entry["key"] or not profile_ids.rules_overlap(rule, match):
                continue
            if profile_ids.rule_implies(rule, match) or profile_ids.rule_implies(match, rule):
                continue
            if profile_ids.dimensions(rule) != profile_ids.dimensions(match):
                continue
            return None
        return entry


def for_you_of(profile: dict[str, Any], statements: list[dict[str, Any]], identity: Identity) -> dict[str, dict[str, Any]]:
    profile_id = profile["profile_id"]
    match = profile["match"]
    codes = [str(code) for code in match["mccmnc"]]
    plain = not any(match.get(key) for key in profile_ids.SELECTOR_KEYS)
    riding = identity.host_only_on(codes) if plain else []
    brand = identity.brand_alone(profile_id, match)
    hosts = identity.listing.get(profile_id, []) if plain else []
    out: dict[str, dict[str, Any]] = {}
    for capability in sorted(set(CAPABILITY_OF_SERVICE.values())):
        about = [s for s in statements if CAPABILITY_OF_SERVICE[s["service"]] == capability and set(codes) <= set(s["mccmnc"])]
        network = [s for s in about if s["scope"] == "network"]
        if network:
            states = {STATE_OF_STATUS[s["status"]] for s in network}
            if len(states) == 1:
                out[capability] = {"state": states.pop(), "statements": sorted(s["id"] for s in network)}
            continue
        brands = [s for s in about if s["scope"] == "brand"]
        if riding:
            keys = {e["key"] for e in hosts} | {e["key"] for e in riding}
            behind = [s for s in brands if s.get("identity_key") in keys]
            if behind:
                names = sorted({e["name"] for e in hosts} | {e["name"] for e in riding})
                out[capability] = {"state": "depends_on_plan", "reason": BRAND_NOT_TELLABLE, "brands": names,
                                   "statements": sorted(s["id"] for s in behind)}
            continue
        if brand is None:
            continue
        own = [s for s in brands if s.get("identity_key") == brand["key"] and not s.get("host_only")]
        states = {STATE_OF_STATUS[s["status"]] for s in own}
        if len(states) == 1:
            out[capability] = {"state": states.pop(), "statements": sorted(s["id"] for s in own)}
    return out


# ---------------------------------------------------------------- derive, apply, check


def load_profiles(root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    out = {}
    for path in sorted((root / "carriers" / "open").glob("*.json")):
        profile = read_json(path)
        out[profile["profile_id"]] = (path, profile)
    return out


def derive(root: Path, variants_profiles: dict[str, Any] | None = None,
           profiles: dict[str, tuple[Path, dict[str, Any]]] | None = None) -> dict[str, dict[str, Any]]:
    """profile ID -> {depends_on, for_you}, each present only when not empty.
    VARIANTS_PROFILES is carrier-variants.json's profiles map (the builder
    passes the one it is about to write); else ROOT's file is read."""
    profiles = profiles if profiles is not None else load_profiles(root)
    evidence = {item["profile_id"]: item for item in read_json(root / EVIDENCE).get("profiles", [])} \
        if (root / EVIDENCE).is_file() else {}
    if variants_profiles is None:
        variants_profiles = read_json(root / VARIANTS).get("profiles", {}) if (root / VARIANTS).is_file() else {}
    statements = live_statements(read_json(root / STATEMENTS)) if (root / STATEMENTS).is_file() else []
    identity_document = read_json(root / IDENTITY) if (root / IDENTITY).is_file() else {"entries": []}
    identity = Identity(identity_document, {pid: p["match"] for pid, (_, p) in profiles.items()})
    out: dict[str, dict[str, Any]] = {}
    for pid, (_, profile) in profiles.items():
        fields = {
            "depends_on": depends_on_of(profile, evidence.get(pid), variants_profiles.get(pid)),
            "for_you": for_you_of(profile, statements, identity),
        }
        out[pid] = {name: value for name, value in fields.items() if value}
    return out


def apply(root: Path, derived: dict[str, dict[str, Any]],
          profiles: dict[str, tuple[Path, dict[str, Any]]] | None = None) -> list[Path]:
    """Write the derived fields into ROOT's profile files; returns the files
    that changed. The capabilities object of every file stays byte-identical:
    a change there stops the write."""
    profiles = profiles if profiles is not None else load_profiles(root)
    changed = []
    for pid, (path, profile) in sorted(profiles.items()):
        before = json.dumps(profile.get("capabilities"), sort_keys=True)
        updated = {key: value for key, value in profile.items() if key not in FIELDS}
        updated.update(derived.get(pid, {}))
        if json.dumps(updated.get("capabilities"), sort_keys=True) != before:
            raise TwoAnswersError(f"{pid}: deriving for_you and depends_on changed capabilities")
        text = dump_profile(updated)
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed.append(path)
    return changed


def counts(derived: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_state: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    not_tellable = 0
    for fields in derived.values():
        for item in fields.get("for_you", {}).values():
            by_state[item["state"]] = by_state.get(item["state"], 0) + 1
            not_tellable += item.get("reason") == BRAND_NOT_TELLABLE
        for reasons in fields.get("depends_on", {}).values():
            for reason in reasons:
                by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "profiles_with_depends_on": sum(1 for f in derived.values() if "depends_on" in f),
        "depends_on_values": sum(len(f.get("depends_on", {})) for f in derived.values()),
        "depends_on_by_reason": dict(sorted(by_reason.items())),
        "profiles_with_for_you": sum(1 for f in derived.values() if "for_you" in f),
        "for_you_values": sum(len(f.get("for_you", {})) for f in derived.values()),
        "for_you_by_state": dict(sorted(by_state.items())),
        "for_you_brand_not_tellable": not_tellable,
    }


def evidence_key(item: dict[str, Any] | None) -> str:
    """What a profile's capabilities rest on in the evidence index."""
    item = item or {}
    gates = [g for g in item.get("quality_gates", []) if isinstance(g, dict) and g.get("section") == "capabilities"]
    conflicts = [c for c in item.get("conflicts", []) if isinstance(c, dict) and c.get("section") == "capabilities"]
    return json.dumps([item.get("capability_sources"), item.get("capability_basis"), gates, conflicts], sort_keys=True)


def tree_problems(root: Path) -> list[str]:
    profiles = load_profiles(root)
    derived = derive(root, profiles=profiles)
    out: list[str] = []
    present = sum(1 for _, p in profiles.values() if any(name in p for name in FIELDS))
    if present == 0:
        return []  # not written yet: the first publish after round 45 writes them
    for pid, (path, profile) in sorted(profiles.items()):
        for name in FIELDS:
            if profile.get(name) != derived.get(pid, {}).get(name):
                out.append(f"{path.relative_to(root)}: {name} is not what tools/two_answers.py derives from the published files")
    lookup_path = root / LOOKUP
    if lookup_path.is_file():
        for index, record in enumerate(read_json(lookup_path).get("profiles", [])):
            pid = record.get("profile_id")
            if pid not in profiles:
                continue
            for name in FIELDS + ("capabilities",):
                if record.get(name) != profiles[pid][1].get(name):
                    out.append(f"{LOOKUP}: profiles[{index}].{name} is not its profile's")
    return out


def base_problems(base: Path, head: Path) -> list[str]:
    """HEAD against BASE (round 45, item 4: for_you never feeds capabilities)."""
    base_profiles, head_profiles = load_profiles(base), load_profiles(head)
    out: list[str] = []
    if any(any(n in p for n in FIELDS) for _, p in base_profiles.values()) and \
            not any(any(n in p for n in FIELDS) for _, p in head_profiles.values()):
        out.append("the base carries depends_on and for_you and this tree carries none")
    base_evidence = {i["profile_id"]: i for i in read_json(base / EVIDENCE).get("profiles", [])} if (base / EVIDENCE).is_file() else {}
    head_evidence = {i["profile_id"]: i for i in read_json(head / EVIDENCE).get("profiles", [])} if (head / EVIDENCE).is_file() else {}
    for pid in sorted(set(base_profiles) & set(head_profiles)):
        old, new = base_profiles[pid][1], head_profiles[pid][1]
        if all(old.get(n) == new.get(n) for n in FIELDS):
            continue
        if evidence_key(base_evidence.get(pid)) != evidence_key(head_evidence.get(pid)):
            continue
        if json.dumps(old.get("capabilities"), sort_keys=True) != json.dumps(new.get("capabilities"), sort_keys=True):
            out.append(f"{pid}: capabilities changed with for_you or depends_on while their evidence did not")
    return out


def extract_base(repo: Path, ref: str, dest: Path) -> Path:
    paths = ["carriers/open"] + [p for p in (EVIDENCE,) if subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{ref}:{p}"], capture_output=True).returncode == 0]
    dest.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", ref, *paths], stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(dest, filter="data")
    if proc.returncode != 0:
        raise TwoAnswersError(f"git archive {ref} failed")
    return dest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("derive")
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--json", type=Path)
    p = sub.add_parser("check")
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--base-ref")
    p.add_argument("--base-root", type=Path)
    args = parser.parse_args(argv[1:])
    if args.command == "derive":
        derived = derive(args.root)
        print(json.dumps(counts(derived), indent=2, sort_keys=True))
        if args.json:
            args.json.write_text(json.dumps(derived, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        base = args.base_root
        if args.base_ref:
            base = extract_base(args.root, args.base_ref, Path(tmp) / "base")
        problems = tree_problems(args.root)
        if base is not None:
            problems += base_problems(base, args.root)
    for line in problems[:200]:
        print(line, file=sys.stderr)
    if problems:
        print(f"two answers: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("two answers: valid" + (" (checked against the base)" if base is not None else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except TwoAnswersError as exc:
        print(f"two answers: ERROR {exc}", file=sys.stderr)
        sys.exit(2)
