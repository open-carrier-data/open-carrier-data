# devices/records/

The side files of the OCD dataset's records. `generated/devices/device-records.json` itself stays an empty role: no result of any account is served on another phone (rule round 47, item 2), so nothing writes a record there and `validate` refuses one. Readers still expect the file, so it stays.

| Path | Contents | Written by |
| --- | --- | --- |
| `keys.json` | the type and IMS stack fork of each key the records use, so a record's key keeps its type | a reviewed pull request |
| `reads/r-<16 hex>.json` | a second-agent read of one group A record: the reader, the time, the sources read, the findings and the verdict | the reading agent, never the record's builder |
| `reads/f5/<lines digest>.json` | an independent agent's F5 read of one held emergency-line change (round 29's `x1s-ocd-f5-read.v1`): kept as the record of the read; `tools/f5_read.py backfill --agent-reads` and the private publisher take such a read in place of a hold | the reading agent, never the builder |
| `reads/group-a/<key>.<12 hex>.json` | a round 31 group A read (`ocd-group-a-read/2`): of one non-Google group A value for its profiles, source families, ROM family and IMS stack, or of a key (whether it changes only what is shown or logged) | the reading agent, never the value's builder |

A group A record is served only when its `second_agent_read` names a read here whose verdict is `proceed` and whose record key, key and value are the record's. The read of `r:937a114148bf73b8` (the S20's emergency bearer-wait key, a record that left at step 8) says `hold`. Records never hold a phone number, IMSI, ICCID, IMEI, SIP URI or IP address. [docs/ocd-dataset.md](../../docs/ocd-dataset.md#records-by-cell-rule-round-31) explains the records.
