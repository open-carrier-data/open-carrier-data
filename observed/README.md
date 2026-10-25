# observed/

Phone results: the test reports the OCD Check app uploads through the `OCD Check report` issue form, kept as unverified hints. [community/README.md](../community/README.md) describes the path.

| Path | Contents |
|---|---|
| `reports/issue-N.json` | one valid report per issue, as submitted (`schemas/ocd-check-report.schema.json`, or for an `ocd-device-record` issue of the owner's account the measured record, `schemas/device-records.schema.json`), with its issue number, report date, SHA-256 hash, release, tester (`owner` for the owner's account, else `outside`), `"verification": "unverified"` and its status after the noise filters (`counted`, `held`, `superseded`, `duplicate`, `expired`) |
| `summary.json` | the reports of every account but the owner's, per device × carrier profile × stack × entry: "reported, not checked by OCD", "contested" and the held reports; its "re-tested by OCD" is always null (`schemas/observed-summary.schema.json`) |

**People's reports are unverified.** A report only points at an entry of OCD's data at one commit of `main`, or of a data release for older app builds (`volte:on`, `apn:<row key>`, ...); it never carries a value. It never changes an OCD value, a file under `carriers/` or `generated/`, or a release, and it never makes a phone skip its own test: at most a phone tests that entry earlier. This folder is not a release asset.

**The owner's results are measured records** (rule round 30, item 4). The OCD Check owner build sends each as one `ocd-device-record` issue from the owner's account; the bot writes them into `devices/records/measured.json`, and `tools/ocd_dataset.py` into `generated/devices/device-records.json`, where the owner's phones of the same device, ROM line and IMS stack serve them. Round 29's `observed/retested.json` is folded into them. A correction opens a source-review issue.

The files are written by `tools/observed_reports.py` from the report issues; do not edit them by hand. The `validate` check fails when a file breaks its schema or the privacy scan, or when `summary.json` or `devices/records/measured.json` is not what the reports give.
