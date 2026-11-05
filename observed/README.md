# observed/

Phone results: the test reports people send from the OCD Android app through the `OCD Android report` issue form, kept as unverified hints. Every account takes this one path. [community/README.md](../community/README.md) describes it.

| Path | Contents |
|---|---|
| `reports/issue-N.json` | one valid report per issue, as submitted apart from a plan that failed its check (`schemas/ocd-check-report.schema.json`), with its issue number, report date, SHA-256 hash, release, `"verification": "unverified"` and its status after the noise filters (`counted`, `held`, `superseded`, `duplicate`, `expired`) |
| `summary.json` | every account's reports per device × carrier profile × stack × entry: "reported, not checked by OCD", "contested" and the held reports (`schemas/observed-summary.schema.json`). One report counts per account and cell, so a count is a count of distinct accounts. Its `retested_by_ocd` is always null, and leaves once the app without it is on the phones |
| `results.json` | the same results as device > carrier > plan, with dates and the count of accounts (`schemas/observed-results.schema.json`, [docs/data-model.md](../docs/data-model.md#results-tree)). Phones and ROM builds never read it |

**Reports are unverified.** A report only points at an entry of OCD's data at one commit of `main`, or of a data release for older app builds (`volte:on`, `apn:<row key>`, ...); it never carries a value. It never changes an OCD value, a file under `carriers/` or `generated/`, or a release, and it never makes a phone skip its own test: at most a phone tests that entry earlier. No result of any account is served on another phone. This folder is not a release asset.

The automatic weekly summaries of rule round 48 are not here and never come here. They have their own repository, because phones read this folder and `main` cannot be rewritten ([community/README.md](../community/README.md#the-automatic-week-report)).

The files are written by `tools/observed_reports.py` from the current report issues, so a deleted issue drops out at the next rebuild; do not edit them by hand. The `validate` check fails when a file breaks its schema or the privacy scan, when `summary.json` or `results.json` is not what the reports give, or when `results.json` enters the dataset manifest, the pull file list or the app's reads.
