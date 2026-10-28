# devices/records/

The sources of `generated/devices/device-records.json`, OCD's per-device records for the owner's devices (rule round 30, item 4). `tools/ocd_dataset.py generate` writes that file from them, and `validate` checks both.

| Path | Contents | Written by |
| --- | --- | --- |
| `configured/<codename>.json` | `configured_device` records: a device's fixes, valid for every carrier, such as the S20's five | a reviewed pull request |
| `measured.json` | the owner's measured records, one per record key, each dropped 90 days after its last measurement | `tools/observed_reports.py rebuild`, from issues of the owner's account only |
| `keys.json` | the type and IMS stack fork of each key the records use, so a record's key keeps its type | a reviewed pull request |
| `reads/r-<16 hex>.json` | a second-agent read of one group A record: the reader, the time, the sources read, the findings and the verdict | the reading agent, never the record's builder |
| `reads/group-a/<key>.<12 hex>.json` | a round 31 group A read (`ocd-group-a-read/2`): of one non-Google group A value for its profiles, source families, ROM family and IMS stack, or of a key (whether it changes only what is shown or logged) | the reading agent, never the value's builder |

Rule round 31 keys records by cell and ends the device-only kind: `validate` refuses a record without a carrier key and a `configured_device` record, except the S20's five in `configured/x1s.json`, which leave once the build with the restored device override has passed on the phone (implementation order step 8). New measured records follow [`schemas/cell-records.schema.json`](../../schemas/cell-records.schema.json).

A group A record is served only when its `second_agent_read` names a read here whose verdict is `proceed` and whose record key, key and value are the record's. The read of `r:937a114148bf73b8` (the S20's emergency bearer-wait key) says `hold`, so that record carries no `second_agent_read` and is not served. Records never hold a phone number, IMSI, ICCID, IMEI, SIP URI or IP address. [docs/ocd-dataset.md](../../docs/ocd-dataset.md#records-by-cell-rule-round-31) explains the records.
