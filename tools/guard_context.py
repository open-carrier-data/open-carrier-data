#!/usr/bin/env python3
"""The base and the phone-guard-accept lines of validate's base-relative steps.

Rule decisions round 37, items 3 and 4: validate never passes on a ref other
than main without the phone-level guard, and every step that compares with a
base (the guard, the F5 read check, the OCD dataset's base manifest and the
CarrierConfig report) uses the same base.

- pull_request: the pull request's base commit. The accept lines come from
  the event's body, as before.
- merge_group: merge_group.base_sha. The accept lines come only from the body
  of the one pull request the gh-readonly-queue ref names, read through the
  API at run time. A ref that names no single pull request, or a pull request
  that is not open, fails the run, and nothing is accepted.
- workflow_dispatch on a ref other than main: the merge base of the run's
  commit and main (main's head whenever the branch is current). The accept
  lines come only from the body of the one open pull request of this
  repository into main whose head is that ref and whose head SHA is the
  run's SHA, read through the API at run time. Without exactly one such pull
  request nothing is accepted, and an apns-conf.xml that differs from the
  base's fails.
- push to main and workflow_dispatch on main: no guard, as before.

Accept lines never come from a dispatch input or any other run parameter.

  resolve  writes the context as JSON (--out) and the step outputs
  guard    runs tools/check_phone_guard.py for that context
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

TOOLS = Path(__file__).resolve().parent
APN_FILE = "generated/android/apns-conf.xml"
MAIN = "main"
MAIN_REF = f"refs/heads/{MAIN}"
SHA_RE = re.compile(r"[0-9a-f]{40}")
# The same lines validate always took: a whole line, 16 hex digits.
ACCEPT_RE = re.compile(r"^phone-guard-accept: ([0-9a-f]{16})$", re.M)
# GitHub's merge queue ref: gh-readonly-queue/<base branch>/pr-<number>-<base sha>.
QUEUE_REF_RE = re.compile(
    r"refs/heads/gh-readonly-queue/(?P<branch>[^\s]+)/pr-(?P<number>[1-9][0-9]*)-(?P<sha>[0-9a-f]{40})")
# GitHub moves a pull request's head a few seconds after a push, and a
# dispatch sent right after the push (the report bot's, the refresh bot's)
# can start first. Only a pull request already open on the ref is waited for.
HEAD_ATTEMPTS = 7
HEAD_WAIT_SECONDS = 10

Api = Callable[[str], Any]


class ContextError(Exception):
    pass


def gh_api(path: str) -> Any:
    out = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json", path],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise ContextError(f"gh api {path}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def accept_lines(body: str | None) -> list[str]:
    return list(dict.fromkeys(ACCEPT_RE.findall((body or "").replace("\r", ""))))


def dispatch_pull_request(repo: str, ref: str, sha: str, api: Api,
                          sleep: Callable[[float], None] = time.sleep) -> dict[str, Any] | None:
    """The one open pull request of REPO into main whose head is REF at SHA,
    or None."""
    if not ref.startswith("refs/heads/"):
        return None
    branch = ref[len("refs/heads/"):]
    owner = repo.split("/", 1)[0]
    head = quote(f"{owner}:{branch}", safe=":/")
    for attempt in range(HEAD_ATTEMPTS):
        pulls = api(f"repos/{repo}/pulls?state=open&per_page=100&head={head}")
        same = [p for p in pulls
                if p.get("state") == "open"
                and ((p.get("head") or {}).get("repo") or {}).get("full_name") == repo
                and p["head"].get("ref") == branch
                and (p.get("base") or {}).get("ref") == MAIN]
        matching = [p for p in same if p["head"].get("sha") == sha]
        if len(matching) == 1:
            return matching[0]
        if matching or not same:
            return None
        if attempt + 1 < HEAD_ATTEMPTS:
            sleep(HEAD_WAIT_SECONDS)
    return None


def resolve(env: dict[str, str], event: dict[str, Any], api: Api,
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    name = env.get("GITHUB_EVENT_NAME", "")
    ref = env.get("GITHUB_REF", "")
    sha = env.get("GITHUB_SHA", "")
    repo = env.get("GITHUB_REPOSITORY", "")
    context: dict[str, Any] = {
        "event": name, "ref": ref, "sha": sha, "guard": False, "base": None, "base_from": None,
        "pr": None, "accept": [], "accept_from": None, "require_unchanged": False,
    }
    if not SHA_RE.fullmatch(sha):
        raise ContextError(f"GITHUB_SHA {sha!r} is not a commit SHA")
    if name == "push":
        if ref != MAIN_REF:
            raise ContextError(f"validate runs on push only for main, not {ref}")
        return context
    if name == "pull_request":
        pr = event.get("pull_request") or {}
        number = pr.get("number")
        context.update(guard=True, base=(pr.get("base") or {}).get("sha"),
                       base_from="the pull request's base commit", pr=number,
                       accept=accept_lines(pr.get("body")),
                       accept_from=f"the body of pull request #{number} in the event")
    elif name == "merge_group":
        group = event.get("merge_group") or {}
        head_ref = group.get("head_ref") or ""
        match = QUEUE_REF_RE.fullmatch(head_ref)
        if not match:
            raise ContextError(f"the merge group ref {head_ref!r} names no single pull request; "
                               "nothing is accepted and the run fails closed")
        number = int(match["number"])
        pr = api(f"repos/{repo}/pulls/{number}")
        if not isinstance(pr, dict) or pr.get("number") != number:
            raise ContextError(f"pull request #{number} of the merge group could not be read; "
                               "nothing is accepted and the run fails closed")
        if pr.get("state") != "open":
            raise ContextError(f"pull request #{number} of the merge group is {pr.get('state')}, not open; "
                               "nothing is accepted and the run fails closed")
        if (pr.get("base") or {}).get("ref") != match["branch"]:
            raise ContextError(f"pull request #{number} does not target {match['branch']}; "
                               "nothing is accepted and the run fails closed")
        context.update(guard=True, base=group.get("base_sha"), base_from="merge_group.base_sha", pr=number,
                       accept=accept_lines(pr.get("body")),
                       accept_from=f"the body of pull request #{number}, read at run time")
    elif name == "workflow_dispatch":
        if ref == MAIN_REF:
            return context
        compare = api(f"repos/{repo}/compare/{MAIN}...{sha}")
        base = ((compare or {}).get("merge_base_commit") or {}).get("sha") if isinstance(compare, dict) else None
        context.update(guard=True, base=base, base_from=f"the merge base of the run's commit and {MAIN}")
        pr = dispatch_pull_request(repo, ref, sha, api, sleep)
        if pr is None:
            context.update(require_unchanged=True,
                           accept_from=f"none: no single open pull request of {repo} into {MAIN} has "
                                       f"{ref} as its head at {sha[:12]}")
        else:
            context.update(pr=pr["number"], accept=accept_lines(pr.get("body")),
                           accept_from=f"the body of pull request #{pr['number']}, read at run time")
    else:
        raise ContextError(f"validate does not run on {name!r}")
    if not SHA_RE.fullmatch(str(context["base"] or "")):
        raise ContextError(f"no base commit for {name} on {ref} (got {context['base']!r}); the run fails closed")
    return context


def git_show(root: Path, revision: str, path: str) -> bytes | None:
    shown = subprocess.run(["git", "-C", str(root), "show", f"{revision}:{path}"], capture_output=True)
    return shown.stdout if shown.returncode == 0 else None


def run_guard(context: dict[str, Any], root: Path, guard_script: Path, report_json: Path | None = None) -> tuple[int, str]:
    """(exit status, output) of the phone-level guard for CONTEXT."""
    if not context.get("guard"):
        return 0, f"phone-level guard: not run, {context.get('event')} on {context.get('ref')}\n"
    base = context["base"]
    lines = [f"guard base: {base} ({context['base_from']})",
             f"accept lines: {len(context['accept'])}, from {context['accept_from']}"]
    base_bytes = git_show(root, base, APN_FILE)
    head_xml = root / APN_FILE
    if base_bytes is None or not head_xml.is_file():
        lines.append(f"error: {APN_FILE} could not be read at the base {base} or in the checkout; the guard fails closed")
        return 2, "\n".join(lines) + "\n"
    with tempfile.TemporaryDirectory(prefix="guard-context-") as scratch:
        base_xml = Path(scratch) / "base-apns-conf.xml"
        base_xml.write_bytes(base_bytes)
        command = [sys.executable, str(guard_script), str(base_xml), str(head_xml),
                   "--generator", str(root), "--base-ref", base]
        for digest in context["accept"]:
            command += ["--accept", digest]
        if report_json is not None:
            command += ["--report-json", str(report_json)]
        result = subprocess.run(command, capture_output=True, text=True)
    status = result.returncode
    output = "\n".join(lines) + "\n" + result.stdout + result.stderr
    if context.get("require_unchanged") and base_bytes != head_xml.read_bytes():
        output += (f"error: {context['accept_from']}; nothing is accepted, and this ref's {APN_FILE} differs "
                   "from the base's, so validate fails (rule decisions round 37, item 3)\n")
        status = status or 1
    return status, output


def write_outputs(context: dict[str, Any], path: str | None) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"guard={'true' if context['guard'] else 'false'}\n")
        handle.write(f"base={context['base'] or ''}\n")
        handle.write(f"pr={context['pr'] or ''}\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rs = sub.add_parser("resolve")
    rs.add_argument("--out", type=Path, required=True)
    gd = sub.add_parser("guard")
    gd.add_argument("--context", type=Path, required=True)
    gd.add_argument("--root", type=Path, default=TOOLS.parent)
    gd.add_argument("--guard-script", type=Path, default=TOOLS / "check_phone_guard.py")
    gd.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv[1:])
    try:
        if args.command == "resolve":
            event_path = os.environ.get("GITHUB_EVENT_PATH")
            event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
            context = resolve(dict(os.environ), event, gh_api)
            args.out.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            write_outputs(context, os.environ.get("GITHUB_OUTPUT"))
            print(f"{context['event']} on {context['ref']}: guard {'runs' if context['guard'] else 'does not run'}"
                  + (f", base {context['base']} ({context['base_from']}), {len(context['accept'])} accept line(s)"
                     f" from {context['accept_from']}" if context["guard"] else ""))
            return 0
        context = json.loads(args.context.read_text(encoding="utf-8"))
        status, output = run_guard(context, args.root.resolve(), args.guard_script, args.report_json)
        sys.stdout.write(output)
        return status
    except (ContextError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
