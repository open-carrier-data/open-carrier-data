## What Changed

Describe the schema, tooling, generator, or documentation change. Carrier
data changes are not accepted by hand. Report them through the issue forms.

## Why

Explain the problem this fixes.

## Safety Check

- [ ] I removed every private value listed in
      [SECURITY.md](https://github.com/open-carrier-data/open-carrier-data/blob/main/SECURITY.md).
- [ ] If this changes carrier behavior, I included evidence or linked a
      maintained source.

## Checks

Run the commands in the `validate` job of `.github/workflows/validate.yml`; the pull request check runs the same.

## Private tests (maintainers)

A change to `tools/`, `schemas/`, `.github/workflows/`, a validator, or a
generated file's format or path is tested against the private tools before
it merges (rule decisions round 37, item 5). In a private worktree at private
main, run

    CARRIER_DATA_PUBLIC_CHECKOUT=<this pull request's worktree> nice -n 19 ionice -c3 tools/run_private_tests.sh

(or the private repository's `tools/merge_public_pr.sh <number>`, which runs
it for those paths and writes this line) and put the result here:

private-tests: not run / passed / failed, against this head at private main <sha>

Data-only pull requests (the publisher, the report bot, the refresh bot)
skip it. The `private-tests` commit status is never required.
