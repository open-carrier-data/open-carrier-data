#!/usr/bin/env python3
"""Frozen carrier profile IDs (rule round 45, item 1).

A profile ID is assigned once and then kept. It is no longer recomputed from
the profile's SIM match set. This module is the one ID function every writer
and validator uses: the private sanitizer, the private side-file builders
(carrier identity, device records) and the public validator.

The registry is the committed tree: the live IDs in carriers/open plus every
retired ID in aliases/ids.json. Assignment for one build:

- A match set that covers exactly the same SIMs as a live profile keeps that
  profile's ID. "The same SIMs" is proved here, never decided by name or
  network: the two sets agree once list order, duplicates and letter case
  (SPN, GID and ICCID prefixes, the IMSI wildcard x) are normalised, the way
  every OCD matcher compares them.
- Any other carry-over to a changed match set needs a continuity entry that
  this module computes and a reviewer accepts (private
  state/id-continuity.json). A split or merge never carries an ID over.
- A new match set gets today's hash once: open.<mccmnc>.<first 12 hex digits
  of SHA-256 over the canonical match set>. A hash that equals a live or
  aliased ID is hashed again with a counter, so the ID keeps the form
  open.<mccmnc>.<12 hex> that OcdCarrierSettings requires. No suffix.
- A live ID that no profile of the build keeps is retired, never reused, and
  gets an aliases/ids.json entry of kind replaced, split, merge or withdrawn
  pointing at the profile or profiles a SIM of its old rule matches now. An
  alias is a redirect for links and saved reports; it never carries a value.

The canonical match-set hash (match_set_hash) is the hash part of today's
ID function over the normalised set. Every record keyed by a profile ID stores
the hash it was made under (records made before the freeze take it from their
profile ID, which then was that hash), and is served as a value only while
its profile's current hash is that hash.

Subcommands:

  check --root DIR [--base-ref SHA | --base-root DIR] [--require-aliases]
      The registry checks of one tree (alias entries, continued IDs, every ID
      named in a generated or side file), and against a base: every base ID
      still live or aliased, aliases only added, the same SIMs under the same
      ID, a new ID only in the issued form for a new match set.
  changes --root DIR (--base-ref SHA | --base-root DIR) [--json FILE]
      The dry-run list: IDs added and removed, kept IDs whose match set
      changed (old and new selectors) and new alias entries.

Only the standard library is used.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable


ID_RE = re.compile(r"^open\.([0-9]{5,6})\.([0-9a-f]{12})$")
ANY_ID_RE = re.compile(r"open\.[0-9]{5,6}\.[0-9a-f]{12}")
HASH_RE = re.compile(r"^[0-9a-f]{12}$")
ALIASES_PATH = "aliases/ids.json"
ALIASES_SCHEMA_VERSION = 1
ALIAS_KINDS = ("replaced", "split", "merge", "withdrawn")
CONTINUED_BASES = ("same_sims", "continuity_entry")
# The first day IDs were frozen. Records made before it take their match-set
# hash from their profile ID.
FREEZE_DATE = "2026-10-31"
# How many counters a check tries before it calls an ID not of the issued
# form. A 48-bit hash collides with one of a few thousand live IDs about once
# in 10^10 new IDs, so a counter above 1 never occurs in practice.
MAX_COUNTER = 64
SELECTOR_KEYS = (
    "gid1_prefixes",
    "gid2_prefixes",
    "iccid_prefixes",
    "imsi_prefix_patterns",
    "spn",
    "android_carrier_ids",
)
MATCH_KEYS = ("mccmnc",) + SELECTOR_KEYS
PREFIX_KEYS = ("gid1_prefixes", "gid2_prefixes", "iccid_prefixes")
ALIASES_DESCRIPTION = (
    "Retired carrier profile IDs (rule round 45, item 1). A profile ID is assigned once and kept; it is not "
    "recomputed from the match set. When a profile's SIMs change and the ID cannot carry over, the old ID is "
    "retired, never reused, and listed here with the profile or profiles a SIM of its old rule matches now, "
    "computed by tools/profile_ids.py, never mapped by hand. kind: replaced (one new profile took its SIMs), "
    "split (several new profiles took them), merge (one new profile took the SIMs of several retired IDs), "
    "withdrawn (no new profile took them; to names where they fall now, if anywhere). An alias is a redirect for "
    "links and saved reports; it never carries a value. continued lists the live IDs whose match set is no longer "
    "the one they were issued for: the same SIMs written differently (same_sims), or an accepted continuity "
    "entry (continuity_entry)."
)


class ProfileIdError(Exception):
    pass


# ---------------------------------------------------------------- the ID function


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def normalise_match(match: dict[str, Any]) -> dict[str, Any]:
    """The match set with each list sorted and without duplicates or empty
    lists. Every published match set is already in this form, so
    match_set_hash of a profile issued before the freeze is its ID's hash."""
    out: dict[str, Any] = {}
    for key in sorted(match):
        values = match[key]
        if isinstance(values, list):
            if not values:
                continue
            out[key] = sorted(set(values))
        else:
            out[key] = values
    return out


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def match_set_hash(match: dict[str, Any]) -> str:
    """The canonical match-set hash: the 12 hex digits today's ID function
    gives the normalised match set."""
    return sha12(canonical_json(normalise_match(match)))


def hash_id(match: dict[str, Any], counter: int = 0) -> str:
    """open.<first network code>.<12 hex>. Counter 0 is today's ID function
    (validate_public_carrier_data.canonical_profile_id); a counter above 0
    hashes the canonical match set followed by a newline and the counter."""
    normal = normalise_match(match)
    text = canonical_json(normal)
    if counter:
        text += f"\n{counter}"
    return f"open.{normal['mccmnc'][0]}.{sha12(text)}"


def issued_counter(profile_id: str, match: dict[str, Any]) -> int | None:
    """The counter whose hash gives PROFILE_ID for MATCH, or None."""
    found = ID_RE.fullmatch(profile_id)
    if not found or found.group(1) != str(normalise_match(match)["mccmnc"][0]):
        return None
    for counter in range(MAX_COUNTER):
        if hash_id(match, counter) == profile_id:
            return counter
    return None


def same_sims_key(match: dict[str, Any]) -> str:
    """Two match sets with one key cover exactly the same SIMs: list order,
    duplicates and letter case do not change which SIMs a rule matches
    (SPN compares ignoring case, GID and ICCID prefixes and the IMSI wildcard
    x too, in resolve_carrier_profiles.profile_matches and both Kotlin
    matchers)."""
    folded: dict[str, Any] = {}
    for key, values in match.items():
        if not isinstance(values, list) or not values:
            continue
        if key == "android_carrier_ids":
            folded[key] = sorted(set(values))
        else:
            folded[key] = sorted({str(value).casefold() for value in values})
    return canonical_json(folded)


def record_match_set_hash(stored: Any, profile_id: str) -> str | None:
    """The hash a record keyed by PROFILE_ID was made under: the one it
    stores, else (a record made before the freeze) its open ID's hash part.
    None for an ID without one (fill-only profiles, whose ID already
    changes with their rule)."""
    if isinstance(stored, str) and HASH_RE.fullmatch(stored):
        return stored
    found = ID_RE.fullmatch(profile_id)
    return found.group(2) if found else None


# ---------------------------------------------------------------- SIM coverage


def _prefix_implies(narrow: str, wide: str) -> bool:
    return narrow.casefold().startswith(wide.casefold())


def _imsi_implies(narrow: str, wide: str) -> bool:
    """Every IMSI matching NARROW matches WIDE (x is a wildcard)."""
    if len(wide) > len(narrow):
        return False
    for a, b in zip(narrow.casefold(), wide.casefold()):
        if b == "x":
            continue
        if a == "x" or a != b:
            return False
    return True


def _imsi_overlap(a: str, b: str) -> bool:
    return all(x == "x" or y == "x" or x == y for x, y in zip(a.casefold(), b.casefold()))


def _dimension_implies(key: str, narrow: list[Any], wide: list[Any]) -> bool:
    if not wide:
        return True
    if not narrow:
        return False
    if key in PREFIX_KEYS:
        return all(any(_prefix_implies(str(a), str(b)) for b in wide) for a in narrow)
    if key == "imsi_prefix_patterns":
        return all(any(_imsi_implies(str(a), str(b)) for b in wide) for a in narrow)
    if key == "spn":
        return {str(a).casefold() for a in narrow} <= {str(b).casefold() for b in wide}
    return set(narrow) <= set(wide)


def _dimension_overlap(key: str, a: list[Any], b: list[Any]) -> bool:
    if not a or not b:
        return True
    if key in PREFIX_KEYS:
        return any(_prefix_implies(str(x), str(y)) or _prefix_implies(str(y), str(x)) for x in a for y in b)
    if key == "imsi_prefix_patterns":
        return any(_imsi_overlap(str(x), str(y)) for x in a for y in b)
    if key == "spn":
        return bool({str(x).casefold() for x in a} & {str(y).casefold() for y in b})
    return bool(set(map(str, a)) & set(map(str, b)))


def rule_implies(narrow: dict[str, Any], wide: dict[str, Any]) -> bool:
    """Every SIM that matches NARROW also matches WIDE."""
    return all(_dimension_implies(key, narrow.get(key) or [], wide.get(key) or []) for key in MATCH_KEYS)


def rules_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Some SIM can match both rules."""
    return all(_dimension_overlap(key, a.get(key) or [], b.get(key) or []) for key in MATCH_KEYS)


def specificity(match: dict[str, Any]) -> int:
    return sum(bool(match.get(key)) for key in SELECTOR_KEYS)


def selector_text(match: dict[str, Any]) -> str:
    """A match set in one line, for dry runs and release notes."""
    parts = []
    for key in MATCH_KEYS:
        values = match.get(key) or []
        if values:
            parts.append(f"{key}={','.join(str(v) for v in values)}")
    return " ".join(parts)


# ---------------------------------------------------------------- the registry


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileIdError(f"{path}: cannot be read ({exc})") from exc


def empty_aliases() -> dict[str, Any]:
    return {"schema_version": ALIASES_SCHEMA_VERSION, "description": ALIASES_DESCRIPTION, "aliases": [], "continued": []}


def load_live(root: Path) -> dict[str, dict[str, Any]]:
    """profile ID -> match set of every profile file under ROOT/carriers/open."""
    live: dict[str, dict[str, Any]] = {}
    folder = root / "carriers" / "open"
    if not folder.is_dir():
        return live
    for path in sorted(folder.glob("*.json")):
        profile = read_json(path)
        profile_id = profile.get("profile_id")
        match = profile.get("match")
        if not isinstance(profile_id, str) or not isinstance(match, dict):
            raise ProfileIdError(f"{path}: needs profile_id and match")
        if profile_id in live:
            raise ProfileIdError(f"{path}: duplicate profile_id {profile_id}")
        live[profile_id] = match
    return live


def load_aliases(root: Path) -> dict[str, Any]:
    path = root / ALIASES_PATH
    if not path.is_file():
        return empty_aliases()
    document = read_json(path)
    if not isinstance(document, dict) or not isinstance(document.get("aliases"), list) or not isinstance(document.get("continued"), list):
        raise ProfileIdError(f"{path}: needs aliases and continued lists")
    return document


def load_continuity(path: Path | None) -> list[dict[str, Any]]:
    """The accepted continuity entries (private state/id-continuity.json)."""
    if path is None or not path.is_file():
        return []
    document = read_json(path)
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ProfileIdError(f"{path}: needs an entries list")
    for entry in entries:
        if not isinstance(entry, dict) or not ID_RE.fullmatch(str(entry.get("id", ""))) \
                or not HASH_RE.fullmatch(str(entry.get("from_match_set_hash", ""))) \
                or not HASH_RE.fullmatch(str(entry.get("to_match_set_hash", ""))):
            raise ProfileIdError(f"{path}: an entry holds id, from_match_set_hash and to_match_set_hash")
    return entries


def exact_key(match: dict[str, Any]) -> str:
    """The match set as published, normalised for order and duplicates."""
    return canonical_json(normalise_match(match))


class Registry:
    """The IDs of the previous tree and the assignment of one build."""

    def __init__(self, live: dict[str, dict[str, Any]], aliases: dict[str, Any] | None = None,
                 continuity: Iterable[dict[str, Any]] = ()) -> None:
        self.live = dict(live)
        self.aliases_document = aliases or empty_aliases()
        self.aliases = {item["id"]: item for item in self.aliases_document.get("aliases", [])}
        self.continued = {item["id"]: item for item in self.aliases_document.get("continued", [])}
        self.by_key: dict[str, str] = {}
        self.by_exact: dict[str, str] = {}
        for profile_id, match in sorted(self.live.items()):
            key = same_sims_key(match)
            if key in self.by_key:
                raise ProfileIdError(f"{profile_id} and {self.by_key[key]} cover the same SIMs")
            self.by_key[key] = profile_id
            self.by_exact[exact_key(match)] = profile_id
        self.continuity = list(continuity)
        # exact match set -> ID, and which exact match set holds a live ID's SIMs.
        self.assigned: dict[str, str] = {}
        self.key_owner: dict[str, str] = {}
        self.issued: dict[str, str] = {}
        self.applied_continuity: dict[str, dict[str, Any]] = {}

    @classmethod
    def load(cls, root: Path, continuity: Path | None = None) -> "Registry":
        return cls(load_live(root), load_aliases(root), load_continuity(continuity))

    def taken(self, profile_id: str) -> bool:
        return profile_id in self.live or profile_id in self.aliases or profile_id in self.issued

    def published_id(self, match: dict[str, Any]) -> str:
        """For the builders that read a tree the sanitizer already wrote (the
        carrier-identity table, the device records): the ID of the profile
        published with exactly this match set, else the hash a new match set
        would get, which names no published profile."""
        return self.by_exact.get(exact_key(match)) or hash_id(match)

    def plan(self, matches: Iterable[dict[str, Any]]) -> None:
        """Decide, before any ID is handed out, which of the build's match
        sets keeps each live ID and which continuity entries apply.

        Where two match sets of the build cover one live profile's SIMs (they
        differ only in letter case the merge keeps apart), the one written as
        the live profile is written keeps the ID, else the first in order; the
        other gets a new ID. An accepted continuity entry applies only to the
        relationship this module computes for this build, so nobody maps an
        ID by hand: its ID is live with the match set it names, no match set
        of the build covers that ID's SIMs any more, and the match set with
        the hash it names is the one new match set that takes the old rule's
        SIMs (a replacement, never a split or merge)."""
        exacts = {exact_key(match): match for match in matches}
        by_same: dict[str, list[str]] = {}
        for exact, match in exacts.items():
            by_same.setdefault(same_sims_key(match), []).append(exact)
        for key, group in by_same.items():
            live_id = self.by_key.get(key)
            if live_id is not None and key not in self.key_owner:
                live_exact = exact_key(self.live[live_id])
                self.key_owner[key] = live_exact if live_exact in group else min(group)
        fresh = {exact: match for exact, match in exacts.items() if same_sims_key(match) not in self.by_key}
        retiring = {pid: match for pid, match in self.live.items() if same_sims_key(match) not in by_same}

        def takers(old: dict[str, Any]) -> list[str]:
            return [exact for exact in alias_targets(old, exacts) if exact in fresh]

        for entry in self.continuity:
            old = retiring.get(entry["id"])
            if old is None or match_set_hash(old) != entry["from_match_set_hash"]:
                continue
            took = takers(old)
            if len(took) != 1 or took[0] in self.assigned or match_set_hash(fresh[took[0]]) != entry["to_match_set_hash"]:
                continue
            if any(took[0] in takers(other) for pid, other in retiring.items() if pid != entry["id"]):
                continue
            self.assigned[took[0]] = entry["id"]
            self.applied_continuity[entry["id"]] = entry

    def assign(self, match: dict[str, Any]) -> str:
        """The build's ID for MATCH: the live ID of the same SIMs, an accepted
        continuity entry's ID, or a new hash, hashed again with a counter
        while it equals a live, retired or already issued ID."""
        exact = exact_key(match)
        found = self.assigned.get(exact)
        if found is not None:
            return found
        key = same_sims_key(match)
        live_id = self.by_key.get(key)
        if live_id is not None and self.key_owner.setdefault(key, exact) == exact:
            found = live_id
        else:
            counter = 0
            while True:
                candidate = hash_id(match, counter)
                if not self.taken(candidate):
                    break
                counter += 1
            found = candidate
            self.issued[found] = exact
        self.assigned[exact] = found
        return found

    def finish(self, new_live: dict[str, dict[str, Any]], today: date) -> tuple[dict[str, Any], dict[str, Any]]:
        """(aliases/ids.json, report) once the build's profiles are known."""
        day = today.isoformat()
        retired = sorted(set(self.live) - set(new_live))
        new_ids = {pid for pid in new_live if pid not in self.live}
        targets_of = {pid: alias_targets(self.live[pid], new_live) for pid in retired}
        taken_by: dict[str, list[str]] = {}
        for pid, targets in targets_of.items():
            for target in targets:
                if target in new_ids:
                    taken_by.setdefault(target, []).append(pid)
        entries = []
        proposals = []
        for pid in retired:
            targets = targets_of[pid]
            fresh = [t for t in targets if t in new_ids]
            if not fresh:
                kind = "withdrawn"
            elif len(fresh) > 1:
                kind = "split"
            elif len(taken_by.get(fresh[0], [])) > 1:
                kind = "merge"
            else:
                kind = "replaced"
            entries.append({
                "id": pid, "kind": kind, "to": targets, "match": normalise_match(self.live[pid]),
                "match_set_hash": match_set_hash(self.live[pid]), "retired_on": day,
            })
            if kind == "replaced":
                new_match = new_live[fresh[0]]
                proposals.append({
                    "id": pid, "from_match_set_hash": match_set_hash(self.live[pid]),
                    "to_match_set_hash": match_set_hash(new_match), "replaced_by": fresh[0],
                    "old_match": normalise_match(self.live[pid]), "new_match": normalise_match(new_match),
                    "old_sims_all_kept": rule_implies(self.live[pid], new_match),
                    "new_sims_all_old": rule_implies(new_match, self.live[pid]),
                })
        aliases = {item["id"]: item for item in self.aliases_document.get("aliases", [])}
        for entry in entries:
            if entry["id"] in aliases:
                raise ProfileIdError(f"{entry['id']} is retired twice")
            aliases[entry["id"]] = entry
        continued = []
        kept_changed = []
        for pid in sorted(new_live):
            match = new_live[pid]
            previous = self.continued.get(pid)
            if pid in self.live and match_set_hash(self.live[pid]) != match_set_hash(match):
                basis = "continuity_entry" if pid in self.applied_continuity else "same_sims"
                kept_changed.append({"id": pid, "basis": basis, "old_match": normalise_match(self.live[pid]),
                                     "new_match": normalise_match(match)})
                continued.append({"id": pid, "basis": basis, "match_set_hash": match_set_hash(match),
                                  "from_match_set_hash": match_set_hash(self.live[pid]), "since": day})
            elif issued_counter(pid, match) is None:
                if previous is None:
                    raise ProfileIdError(f"{pid} is not the hash of its match set and no continued entry explains it")
                continued.append(previous)
        document = {
            "schema_version": ALIASES_SCHEMA_VERSION,
            "description": ALIASES_DESCRIPTION,
            "aliases": [aliases[key] for key in sorted(aliases)],
            "continued": continued,
        }
        applied = set(self.applied_continuity)
        report = {
            "registry_ids": len(self.live) + len(self.aliases),
            "kept": len(set(self.live) & set(new_live)),
            "new_ids": sorted(new_ids),
            "new_ids_with_counter": sorted(pid for pid in new_ids if issued_counter(pid, new_live[pid]) not in (0, None)),
            "retired": retired,
            "new_aliases": entries,
            "kept_ids_with_changed_match_set": kept_changed,
            "continuity_proposals": proposals,
            "continuity_applied": sorted(applied),
            "continuity_not_applied": sorted(e["id"] for e in self.continuity if e["id"] not in applied),
        }
        return document, report


def dimensions(match: dict[str, Any]) -> frozenset[str]:
    return frozenset(key for key in MATCH_KEYS if match.get(key))


def alias_targets(old: dict[str, Any], new_live: dict[str, dict[str, Any]]) -> list[str]:
    """The profiles a SIM of the old rule provably matches in the new data:
    the most specific profiles that cover every SIM of the old rule, and every
    profile that takes part of its SIMs, being narrower than the old rule or
    overlapping it on the same selectors. A rule on other selectors (an SPN
    rule against a GID rule) is not counted: whether such a SIM matches it
    depends on fields the old rule does not name."""
    covering = []
    partial = []
    for pid, match in new_live.items():
        if not rules_overlap(old, match):
            continue
        if rule_implies(old, match):
            covering.append(pid)
        elif rule_implies(match, old) or dimensions(match) == dimensions(old):
            partial.append(pid)
    best: list[str] = []
    if covering:
        top = max(specificity(new_live[pid]) for pid in covering)
        best = [pid for pid in covering if specificity(new_live[pid]) == top]
    return sorted(set(best) | set(partial))


def dump_aliases(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_aliases(root: Path, document: dict[str, Any]) -> None:
    path = root / ALIASES_PATH
    text = dump_aliases(document)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- checks


def alias_document_problems(document: dict[str, Any], live: dict[str, dict[str, Any]]) -> list[str]:
    """aliases/ids.json against the live tree, beyond its schema."""
    out: list[str] = []
    where = ALIASES_PATH
    if document.get("schema_version") != ALIASES_SCHEMA_VERSION:
        out.append(f"{where}: schema_version must be {ALIASES_SCHEMA_VERSION}")
    aliases = document.get("aliases", [])
    ids = [item.get("id") for item in aliases if isinstance(item, dict)]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        out.append(f"{where}: aliases are sorted by id, each id once")
    registry = set(live) | set(ids)
    for item in aliases:
        if not isinstance(item, dict) or set(item) != {"id", "kind", "to", "match", "match_set_hash", "retired_on"}:
            out.append(f"{where}: an alias holds exactly id, kind, to, match, match_set_hash and retired_on")
            continue
        pid = item["id"]
        if not ID_RE.fullmatch(str(pid)):
            out.append(f"{where}: {pid!r} is not an open.<mccmnc>.<12 hex> ID")
        if pid in live:
            out.append(f"{where}: {pid} is live and aliased")
        if item["kind"] not in ALIAS_KINDS:
            out.append(f"{where}: {pid}: kind is one of {', '.join(ALIAS_KINDS)}")
        if not isinstance(item["to"], list) or item["to"] != sorted(set(item["to"])):
            out.append(f"{where}: {pid}: to is a sorted list of distinct IDs")
        else:
            for target in item["to"]:
                if target not in registry:
                    out.append(f"{where}: {pid} points at {target}, which is neither live nor aliased")
            if item["kind"] in ("replaced", "merge") and not item["to"]:
                out.append(f"{where}: {pid}: a {item['kind']} alias names its target")
        if not isinstance(item["match"], dict) or not item["match"].get("mccmnc"):
            out.append(f"{where}: {pid}: match is the retired match set")
        elif item["match_set_hash"] != match_set_hash(item["match"]):
            out.append(f"{where}: {pid}: match_set_hash is not the hash of match")
        if not isinstance(item["retired_on"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["retired_on"]):
            out.append(f"{where}: {pid}: retired_on is a date")
    seen = set()
    for item in document.get("continued", []):
        if not isinstance(item, dict) or set(item) != {"id", "basis", "match_set_hash", "from_match_set_hash", "since"}:
            out.append(f"{where}: a continued entry holds exactly id, basis, match_set_hash, from_match_set_hash and since")
            continue
        pid = item["id"]
        if pid in seen:
            out.append(f"{where}: {pid} is continued twice")
        seen.add(pid)
        if pid not in live:
            out.append(f"{where}: continued {pid} is not live")
            continue
        if item["basis"] not in CONTINUED_BASES:
            out.append(f"{where}: continued {pid}: basis is one of {', '.join(CONTINUED_BASES)}")
        if item["match_set_hash"] != match_set_hash(live[pid]):
            out.append(f"{where}: continued {pid}: match_set_hash is not the hash of its current match set")
    for pid, match in sorted(live.items()):
        if pid not in seen and issued_counter(pid, match) is None:
            out.append(f"carriers/open: {pid} is not the issued hash of its match set and no continued entry explains it")
    return out


def referenced_ids(root: Path) -> dict[str, set[str]]:
    """Every open profile ID a generated file or side file names, by file.
    Structured fields only: the evidence index's would-be IDs of withdrawn
    profiles and the prose of F5 reads are not references."""
    found: dict[str, set[str]] = {}

    def scan_text(rel: str) -> None:
        path = root / rel
        if path.is_file():
            found[rel] = set(ANY_ID_RE.findall(path.read_text(encoding="utf-8")))

    for rel in ("generated/index.json", "generated/android/lookup.json", "generated/android/metadata.json",
                "generated/android/apns-conf.xml", "generated/android/carrier-config-list.xml",
                "generated/operators/carrier-identity.json", "generated/devices/carrier-variants.json",
                "generated/devices/device-records.json", "generated/ocd-dataset/profiles.json",
                "generated/ocd-dataset/group-a-reads.json", "generated/ocd-dataset/group-a-pending.json",
                "generated/ocd-dataset/apn-index.json", "devices/records/measured.json"):
        scan_text(rel)
    evidence = root / "generated/evidence-index.json"
    if evidence.is_file():
        document = read_json(evidence)
        found["generated/evidence-index.json"] = {
            str(p.get("profile_id")) for p in document.get("profiles", []) if isinstance(p, dict)
        }
    for path in sorted((root / "devices/records/reads/group-a").glob("*.json")):
        document = read_json(path)
        found[path.relative_to(root).as_posix()] = {
            p for p in document.get("profiles", []) if isinstance(p, str) and ID_RE.fullmatch(p)
        }
    return found


def schema_problems(root: Path, document: dict[str, Any]) -> list[str]:
    """aliases/ids.json against schemas/profile-id-aliases.schema.json, with
    the public validator's schema checker (imported here: it imports this
    module)."""
    schema_path = root / "schemas" / "profile-id-aliases.schema.json"
    if not schema_path.is_file():
        return []
    import validate_public_carrier_data as validator

    schema = read_json(schema_path)
    problem = validator.schema_problem(document, schema, schema, "$")
    return [f"{ALIASES_PATH}: does not match schemas/profile-id-aliases.schema.json: {problem}"] if problem else []


def tree_problems(root: Path, require_aliases: bool = False) -> list[str]:
    live = load_live(root)
    if require_aliases and not (root / ALIASES_PATH).is_file():
        return [f"{ALIASES_PATH} is missing"]
    document = load_aliases(root)
    out = schema_problems(root, document) + alias_document_problems(document, live)
    if (root / ALIASES_PATH).is_file() and (root / ALIASES_PATH).read_text(encoding="utf-8") != dump_aliases(document):
        out.append(f"{ALIASES_PATH}: is not written as tools/profile_ids.py writes it (indent 2, sorted keys, a final newline)")
    registry = set(live) | {item.get("id") for item in document.get("aliases", []) if isinstance(item, dict)}
    for rel, ids in sorted(referenced_ids(root).items()):
        missing = sorted(i for i in ids if i not in registry)
        if missing:
            out.append(f"{rel}: names {len(missing)} profile ID(s) the registry does not hold, for example {missing[0]}")
    return out


def base_problems(base: Path, head: Path) -> list[str]:
    """HEAD against BASE: no ID lost, aliases only added, the same SIMs under
    the same ID, and a new ID only for a new match set, in the issued form."""
    base_live, head_live = load_live(base), load_live(head)
    base_aliases, head_aliases = load_aliases(base), load_aliases(head)
    base_alias = {item["id"]: item for item in base_aliases.get("aliases", [])}
    head_alias = {item["id"]: item for item in head_aliases.get("aliases", [])}
    head_continued = {item["id"]: item for item in head_aliases.get("continued", [])}
    out: list[str] = []
    for pid in sorted(set(base_live) - set(head_live) - set(head_alias)):
        out.append(f"{pid} left carriers/open without an entry in {ALIASES_PATH}")
    for pid, item in sorted(base_alias.items()):
        if head_alias.get(pid) != item:
            out.append(f"{ALIASES_PATH}: the entry of {pid} was removed or changed; entries are only added")
    base_by_key = {same_sims_key(match): pid for pid, match in base_live.items()}
    taken = set(base_live) | set(base_alias)
    for pid, match in sorted(head_live.items()):
        key = same_sims_key(match)
        before = base_by_key.get(key)
        if before is not None and before != pid:
            out.append(f"{pid} covers the same SIMs as {before} on the base; it must keep the ID {before}")
            continue
        if pid in base_live:
            if same_sims_key(base_live[pid]) != key:
                entry = head_continued.get(pid)
                if entry is None or entry.get("basis") != "continuity_entry" or entry.get("match_set_hash") != match_set_hash(match):
                    out.append(f"{pid} kept its ID for other SIMs without an accepted continuity entry in {ALIASES_PATH}")
            continue
        if pid in base_alias:
            out.append(f"{pid} was retired on the base and is never reused")
            continue
        counter = issued_counter(pid, match)
        if counter is None:
            out.append(f"{pid} is new but not the issued hash of its match set")
            continue
        for lower in range(counter):
            if hash_id(match, lower) not in taken:
                out.append(f"{pid} uses counter {counter}, but {hash_id(match, lower)} was free")
                break
    return out


def id_changes(base: Path, head: Path) -> dict[str, Any]:
    """The dry-run list between two trees."""
    base_live, head_live = load_live(base), load_live(head)
    base_alias = {item["id"] for item in load_aliases(base).get("aliases", [])}
    head_aliases = load_aliases(head).get("aliases", [])
    kept_changed = [
        {"id": pid, "old": selector_text(base_live[pid]), "new": selector_text(head_live[pid])}
        for pid in sorted(set(base_live) & set(head_live))
        if canonical_json(normalise_match(base_live[pid])) != canonical_json(normalise_match(head_live[pid]))
    ]
    return {
        "added": sorted(set(head_live) - set(base_live)),
        "removed": sorted(set(base_live) - set(head_live)),
        "kept": len(set(base_live) & set(head_live)),
        "kept_with_changed_match_set": kept_changed,
        "new_aliases": [
            {"id": item["id"], "kind": item["kind"], "to": item["to"], "match": selector_text(item["match"])}
            for item in head_aliases if item["id"] not in base_alias
        ],
    }


def change_lines(changes: dict[str, Any], limit: int = 50) -> list[str]:
    lines = [f"profile IDs: {len(changes['added'])} added, {len(changes['removed'])} removed, {changes['kept']} kept"]
    kept = changes["kept_with_changed_match_set"]
    lines.append(f"kept IDs whose match set changed: {len(kept)}")
    lines += [f"  {item['id']}: {item['old']} -> {item['new']}" for item in kept[:limit]]
    aliases = changes["new_aliases"]
    lines.append(f"new alias entries: {len(aliases)}")
    lines += [f"  {item['id']} ({item['match']}) {item['kind']} -> {', '.join(item['to']) or 'none'}" for item in aliases[:limit]]
    for name, items in (("kept IDs", kept), ("alias entries", aliases)):
        if len(items) > limit:
            lines.append(f"  ... {len(items) - limit} more {name}")
    return lines


# ---------------------------------------------------------------- base trees


def extract_base(repo: Path, ref: str, dest: Path) -> Path:
    """carriers/open and aliases/ of REF, through git archive, into DEST."""
    paths = ["carriers/open"]
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{ref}:{ALIASES_PATH}"], capture_output=True).returncode == 0:
        paths.append("aliases")
    dest.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", ref, *paths], stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(dest, filter="data")
    if proc.returncode != 0:
        raise ProfileIdError(f"git archive {ref} failed")
    return dest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "changes"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, default=Path("."))
        p.add_argument("--base-ref")
        p.add_argument("--base-root", type=Path)
        if name == "check":
            p.add_argument("--require-aliases", action="store_true")
        else:
            p.add_argument("--json", type=Path)
            p.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv[1:])
    with tempfile.TemporaryDirectory() as tmp:
        base = args.base_root
        if args.base_ref:
            base = extract_base(args.root, args.base_ref, Path(tmp) / "base")
        if args.command == "check":
            problems = tree_problems(args.root, args.require_aliases)
            if base is not None:
                problems += base_problems(base, args.root)
            for line in problems[:200]:
                print(line, file=sys.stderr)
            if problems:
                print(f"profile IDs: {len(problems)} problem(s)", file=sys.stderr)
                return 1
            live = load_live(args.root)
            aliases = load_aliases(args.root)
            print(f"profile IDs: valid, {len(live)} live, {len(aliases['aliases'])} aliased, "
                  f"{len(aliases['continued'])} continued" + (" (checked against the base)" if base is not None else ""))
            return 0
        if base is None:
            parser.error("changes needs --base-ref or --base-root")
        changes = id_changes(base, args.root)
        print("\n".join(change_lines(changes, args.limit)))
        if args.json:
            args.json.write_text(json.dumps(changes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except ProfileIdError as exc:
        print(f"profile IDs: ERROR {exc}", file=sys.stderr)
        sys.exit(2)
