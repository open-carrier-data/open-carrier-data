# observed/

Unverified hints from phones: the test reports the OCD Check app uploads through the `OCD Check report` issue form. [community/README.md](../community/README.md) describes the path.

| Path | Contents |
|---|---|
| `reports/issue-N.json` | one valid report per issue, as submitted (`schemas/ocd-check-report.schema.json`), with its issue number, report date, SHA-256 hash, release, `"verification": "unverified"` and its status after the noise filters (`counted`, `held`, `superseded`, `duplicate`, `expired`) |
| `summary.json` | per device × carrier profile × stack × release entry: "reported, not checked by OCD", "contested", the held reports, and "re-tested by OCD", which only OCD's own phones set and which is empty here (`schemas/observed-summary.schema.json`) |

**Everything here is unverified.** A report only points at an entry of an OCD data release (`volte:on`, `apn:<row key>`, ...); it never carries a value. It never changes an OCD value, a file under `carriers/` or `generated/`, or a release, and it never makes a phone skip its own test: at most a phone tests that entry earlier. This folder is not a release asset. The files are written by `tools/observed_reports.py` from the report issues; do not edit them by hand. The `validate` check fails when a file breaks the schema or the privacy scan, or when `summary.json` is not what the reports give.
