#!/usr/bin/env python3
"""The class (a) list of one checkout (rule decisions round 32, D8, rule 6).

usage: credential_fill_ins.py CHECKOUT [--json PATH]

A phone sends a username, password, auth type or MTU that a lower-ranked row
of a stored group writes where the group's best row sets none, because
TelephonyProvider stores such rows as one row and the generator writes the
best row last (change 17). Class (a) is such a fill-in on an internet, attach
or MMS lead where no current vendor backs the filling row and one backs the
best row. This prints, per scope and role, the APN, the filled-in fields, the
sources of the filling rows, whether the lead sends them or only stores them,
and the network types, then the rows rule 1 left out of apns-conf.xml.

CHECKOUT is a public checkout: its generated/android/apns-conf.xml, read with
`android_phone_model`, and its generator's records of its carriers/ and
generated/evidence-index.json (`check_phone_guard.class_a_list`). Each
publish pull request and each release's notes carry this list. It changes
nothing and never fails a publish: exit 0 after printing, 2 on an error.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_phone_guard as guard  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--json", type=Path, help="also write the list as JSON")
    args = parser.parse_args(argv[1:])
    result = guard.class_a_list(args.checkout.resolve())
    for line in result["lines"]:
        print(line)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BaseException as exc:  # report, never a crash trace in a pull request body
        print(f"credential_fill_ins: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
