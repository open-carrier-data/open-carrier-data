# Data rights and reuse

The software and documentation in this repo are licensed under Apache-2.0. The carrier data needs its own statement because it is assembled from upstream sources with different terms.

## What the project waives

The Open Carrier Data contributors may hold copyright or database rights in the neutral carrier profiles, the indexes, and the generated data. To that extent, they waive those rights under the Creative Commons CC0 1.0 Universal Public Domain Dedication.

## What the waiver cannot grant

The waiver grants nothing the project does not own. Upstream rights, database rights, trademarks, patents, contracts, and service terms may still apply.

Per-source terms are in `generated/evidence-index.json` under `source_snapshots[].license_expression`. Sources recorded as `NOASSERTION` (Apple carrier bundles, Google CarrierSettings and TheMuppets snapshots, LineageOS device overlays, Google's device list) and Samsung firmware facts are published only as normalized facts, never as source files; you must decide whether your use is permitted. On 2026-10-03, 439 profiles rest only on Apache-2.0 or public-domain sources. To print the current count, run:

```bash
python3 -c 'import json; e=json.load(open("generated/evidence-index.json")); lic={s["source_name"]: s["license_expression"] for s in e["source_snapshots"]}; alias={"aosp": ["aosp_carrier_config", "aosp_carrier_ids"], "lineageos_device_overlays": ["lineageos_device_carrier_overlays"]}; print(sum(all(lic.get(n) in ("Apache-2.0", "CC-PD") for s in p["sources"] for n in alias.get(s, [s])) for p in e["profiles"]))'
```

## Where the exact terms are recorded

The source revisions and terms behind the current snapshot are in `generated/evidence-index.json`. [SOURCES.md](SOURCES.md) describes each source family.

The CC0 1.0 legal text is at `https://creativecommons.org/publicdomain/zero/1.0/legalcode`.
