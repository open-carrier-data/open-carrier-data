# Data rights and reuse

The software and documentation in this repo are licensed under Apache-2.0. The carrier data has its own statement.

## The data is facts

Every published value is a fact about a mobile network: a network code, an APN name, an MMSC address, a CarrierConfig value, a capability. The project derives these facts from its sources and normalizes them into its own format. It builds its own profiles, indexes, and generated files from them. Copyright does not protect single facts like these.

The project publishes no vendor files. This repo holds no source's raw files, packages, or responses.

## The project's own rights

The Open Carrier Data contributors waive their own rights in the published data under the Creative Commons CC0 1.0 Universal Public Domain Dedication. The waiver covers any copyright or database right they hold in the profiles, the indexes, and the generated files.

## The source terms on record

`generated/evidence-index.json` records the terms each source family states, as `source_snapshots[].license_expression`. The value is a fact about the source: `Apache-2.0`, `CC-PD`, or `NOASSERTION` when the source states none. [SOURCES.md](SOURCES.md) describes each source family.

A consumer can take only profiles whose sources all carry an open license. On 2026-10-03, 431 profiles rest only on Apache-2.0 or public-domain sources. To print the current count, run:

```bash
python3 -c 'import json; e=json.load(open("generated/evidence-index.json")); lic={s["source_name"]: s["license_expression"] for s in e["source_snapshots"]}; alias={"aosp": ["aosp_carrier_config", "aosp_carrier_ids"], "lineageos_device_overlays": ["lineageos_device_carrier_overlays"]}; print(sum(all(lic.get(n) in ("Apache-2.0", "CC-PD") for s in p["sources"] for n in alias.get(s, [s])) for p in e["profiles"]))'
```

The CC0 1.0 legal text is at `https://creativecommons.org/publicdomain/zero/1.0/legalcode`.

This page states the project's position. It is not legal advice for your use.
