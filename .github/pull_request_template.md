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
