# Source families

This page lists every source family that feeds the public data, what each one contributes, its terms, and how automation refreshes it. The exact revision and check date of each family sit in `generated/evidence-index.json` under `source_snapshots`.

## All source families at a glance

The table has one row per source name as it appears in profile evidence. The snapshot column names the `source_snapshots` record when its name differs. The profile counts change with every publish. The first command below prints the current ones.

| Source name in profiles | Snapshot record | Upstream | Contributes | Terms | Profiles on 2026-10-03 |
| --- | --- | --- | --- | --- | --- |
| `aosp` | `aosp_carrier_config`, `aosp_carrier_ids` | AOSP `platform/packages/apps/CarrierConfig` and `platform/packages/providers/TelephonyProvider` | CarrierConfig values, Android carrier identity rules | Apache-2.0 | 235 |
| `lineageos` | same | `LineageOS/android_vendor_apn` | APN rows and MVNO selectors | Apache-2.0 | 1,064 |
| `lineageos_device_overlays` | `lineageos_device_carrier_overlays` | LineageOS device repos | device overlay carrier facts | NOASSERTION | 1,163 |
| `mobile_broadband_provider_info` | same | GNOME `mobile-broadband-provider-info` | carrier and APN facts | CC-PD | 741 |
| `apple_carrier_bundles` | same | Apple's carrier index | APN and MMS facts from IPCC packages | NOASSERTION | 1,934 |
| `google_carriersettings` | same | `GrapheneOS/adevtool` plus Google's live endpoint | match rules, APNs, CarrierConfig, capabilities | MIT and NOASSERTION | 3,446 |
| `google_pixel_vendor_carriersettings` | same | `TheMuppets` vendor snapshots | Pixel CarrierSettings facts | NOASSERTION | 2,234 |
| `samsung_omc` | same | Samsung firmware OMC baselines | APN, capability, CarrierConfig, add-on facts | NOASSERTION | 2,572 |
| `samsung_ims` | same | Samsung IMS maps in versioned firmware | positive IMS capability observations | NOASSERTION | 944 |
| `fairphone_official_source` | same | Fairphone Gerrit manifest | carrier facts from Fairphone source | Apache-2.0 | 1,242 |
| `sony_open_devices_aosp` | same | `sonyxperiadev/local_manifests` | carrier facts from Sony AOSP trees | Apache-2.0 | 1,090 |

Two profile source names have no snapshot of the same name: `aosp` and `lineageos_device_overlays` map to differently named records. Samsung has no git revision, so the `samsung_omc` and `samsung_ims` records carry the SHA-256 of the lane's state file as `revision`; the daily Samsung run re-checks them. The oldest Samsung observation still sets `checks_through`.

To print the profile count per source name, run:

```bash
python3 -c 'print(__import__("collections").Counter(s for p in __import__("json").load(open("generated/evidence-index.json"))["profiles"] for s in p["sources"]))'
```

To print the snapshot names, revisions, and check dates, run:

```bash
python3 -c 'print(*[(s["source_name"], s["revision_date"], s["checked_at"]) for s in __import__("json").load(open("generated/evidence-index.json"))["source_snapshots"]], sep="\n")'
```

The refresh methods below, the AOSP branch name, and the Samsung scope rules come from the private importer configuration. They cannot be checked from this repo.

## How a source's on and off count

A source family that turns a capability on makes it `supported`, as long as none turns it off. An off counts only when the operator's own configuration gives it, or when two independent families give it. One family's off alone leaves the capability `unknown` and leaves its false CarrierConfig switch out. [docs/data-model.md](docs/data-model.md#capability-names-and-values) defines the values.

| Source name | Its offs |
| --- | --- |
| `apple_carrier_bundles`, `samsung_omc`, `samsung_ims` | never published; these lanes publish only what they turn on |
| `google_carriersettings`, `google_pixel_vendor_carriersettings` | one family; the operator's own for Google Fi |
| `aosp` | one family; the operator's own only for a file the carrier submitted, on 2026-10-04 SETAR's |
| `lineageos`, `sony_open_devices_aosp`, `fairphone_official_source` | one family, copies of AOSP's APN list |
| `lineageos_device_overlays` | one family |

`capability_sources` in each profile's record of `generated/evidence-index.json` names the sources that turn each capability on and off. To print, per source, how many profile capabilities it turns off, whatever value the profiles publish, run:

```bash
python3 -c 'import json, collections; print(collections.Counter(s for p in json.load(open("generated/evidence-index.json"))["profiles"] for c in p.get("capability_sources", {}).values() for s in c.get("off", [])))'
```

## Exact versions behind a profile

A snapshot revision names the source state that was checked. Where a family also knows the exact version each value was read from, the profile's record in `generated/evidence-index.json` names it under `source_versions`. [docs/data-model.md](docs/data-model.md) lists the fields.

| Source name | Version kind | From |
| --- | --- | --- |
| `google_carriersettings` | `builds` | the Pixel build ID of the GrapheneOS snapshot |
| `samsung_ims` | `builds` | the Samsung firmware (PDA) build |
| `samsung_omc` | `builds` | the firmware (PDA) build of the CSC package, recorded at extraction since 2026-10-04 |
| `fairphone_official_source` | `commits` | the pinned `fp2-common` or `fp3-common` commit |
| `sony_open_devices_aosp` | `commits` | the `device-sony-common` commit |
| `lineageos_device_overlays` | `commits` | the commit that last changed the overlay file |
| `google_pixel_vendor_carriersettings` | `commits` | the commits that last changed each device's CarrierSettings files |
| `apple_carrier_bundles` | `bundle_versions`, `ios_versions` | the bundle and iOS versions Apple's index lists for the package |

On 2026-10-03, 3,984 profiles carry the field, from the first four rows. The last three families add their versions from their next weekly refresh. The `aosp`, `lineageos`, and `mobile_broadband_provider_info` families read one commit per snapshot, which `source_snapshots` names. Samsung OMC names the firmware build only for observations extracted since 2026-10-04, up to 50 CSC packages a day; older ones carry none, because a later join would have to guess. Its OMC versions are in `observed_scope.omc_versions`.

To print how many profiles name a version, per family and kind, run:

```bash
python3 -c 'import json, collections; print(collections.Counter((i["source"], k) for p in json.load(open("generated/evidence-index.json"))["profiles"] for i in p.get("source_versions", []) for k in i if k != "source"))'
```

## Freshness uses checked_at, not revision_date

Every `source_snapshots` record carries two dates. `revision_date` is when the upstream published that revision. `checked_at` is when automation last confirmed the revision with success.

Freshness uses `checked_at`, the last successful sync of a lane. It says the lane is alive, not that a value is current: unchanged upstream content keeps passing while its check is within 180 days, however old the entries in it are. An observation whose source check or review date is older is quarantined. Only Samsung's update service and the GrapheneOS lane's check against Google's update service confirm vendor data as current; other vendor data, such as the `TheMuppets` Pixel files, passes as a versioned artifact at any age. `newest_entry` in the evidence index and `lookup.json` gives the age. The public side publishes the window as `checks_through` and `stale_after` in `generated/android/metadata.json`. `checks_through` also follows the oldest observation review date. The oldest Samsung observation is older than every snapshot check, so it sets the window, and the window moves only as the daily Samsung run re-extracts the observations from superseded firmware builds. To print the window, run `python3 -c 'print(*[__import__("json").load(open("generated/android/metadata.json"))[k] for k in ("checks_through", "stale_after")])'`. Past `stale_after` `tools/validate_public_carrier_data.py` warns by default and fails only with `--freshness fail`. The daily public job passes that flag and opens an issue labeled `stale-data` when it fails. Pushes and pull requests run in warn mode. A weekly GitHub-hosted job re-checks every family except Samsung, which runs daily on the self-hosted runner.

## AOSP contributes CarrierConfig values and carrier IDs

Automation reads the `android-latest-release` branch of both AOSP repos and records the full commit ID. Terms are Apache-2.0.

## LineageOS contributes APN rows and device overlays

The APN repo is imported by commit ID under Apache-2.0. When LineageOS removes an APN, the lane records it, and the same row is left out of the other sources unless one gives it with an entry newer than the removal; the evidence index names the LineageOS commit in the gate `lineageos_apn_removed:<commit>`. Device overlays are read across LineageOS device repos and recorded as one content hash. The project asserts no license for overlay content beyond what each repo declares, so those facts are `transformed_facts_only`.

## GNOME contributes public carrier and APN facts

The repo is imported by commit ID. Its dedication is public domain, recorded here as `CC-PD`.

## Apple contributes APN and MMS facts from digest-checked bundles

Automation reads Apple's carrier index over HTTPS and records its SHA-256. Every selected IPCC must match the SHA-1 or SHA-384 digest carried by the index before its facts are imported. An index can still point at an old HTTP CDN URL. Such a package is accepted only when its full digest matches.

The public repo never contains raw indexes, package URLs, package paths, selectors, or IPCC files. Unavailable packages and digest mismatches are quarantined and retried later. Apple declares no license, so the record says `NOASSERTION`.

## Google Pixel CarrierSettings contributes match rules, APNs, and capabilities

The maintained snapshot is the newest numeric Android branch in `GrapheneOS/adevtool`, which holds decoded CarrierSettings for supported Pixels. Automation records that revision, then checks every Pixel against Google's live endpoint. It applies a delta only when the endpoint's version is newer than the firmware baseline. `TheMuppets` vendor snapshots add a second, hash-recorded Pixel source.

Raw textproto and protobuf files, endpoint responses, and download URLs stay private. Pixel variants that disagree stay separate observations and become conditional or omitted in the merge. The GrapheneOS tooling is MIT. The project asserts no license for Google's data.

## Samsung contributes OMC facts and positive capability observations

OMC facts come from firmware baselines found through Samsung's unauthenticated firmware update lookup. OMC capabilities are positive too: where Samsung's last OMC layer turns a feature off, the capability stays `unknown` and no false CarrierConfig switch is written. The GRAS update-check path was removed on 2026-10-03; two older GRAS observations remain until re-extraction replaces them. A firmware observation needs a versioned artifact whose build Samsung's update service confirmed as current, dated by that confirmation.

OMC VoNR comes only from the carrier pack token `+vonrcall`, which makes Samsung's settings offer the VoNR switch for the carrier on that model. It means the switch is offered, not that VoNR is on by default or was tested; a model without the token leaves VoNR `unknown`, and test and lab networks get no value. The evidence index names the sales codes and models in `capability_basis`.

IMS facts are positive, device-scoped observations of VoLTE, Wi-Fi calling, video calling, SMS over IMS, and RCS. A false or absent Samsung switch is never published as proof that a carrier lacks the feature. Raw firmware, OMC files, requests, responses, signed URLs, and credentials stay private. The project asserts no Samsung license.

## Fairphone and Sony contribute facts from public AOSP trees

Both families are read from public AOSP-style manifests under Apache-2.0 and recorded by content hash. Only translated carrier facts are published.

## Device inventories use their own sources

The device catalog under `generated/devices/` uses its own sources. The broad Android inventory is Google's Play supported-devices CSV, recorded by SHA-256 and published as normalized identity fields under `NOASSERTION`. Identities that vanish from a later revision stay as `historical`. Apple product types come from the same carrier index as the bundles. LineageOS device repos and the carrier families above add exact model scope.

On 2026-10-03 the catalog's `index.json` lists 12 named sources. Print them with:

```bash
python3 -c 'print(*sorted(s["name"] for s in __import__("json").load(open("generated/devices/index.json"))["sources"]), sep="\n")'
```

## Artifact registries record what vendor indexes list

`generated/devices/android-carrier-artifacts.json` and `apple-carrier-artifacts.json` record which carrier artifacts a vendor index listed at the last check, with `indexed`, `extracted`, or `verified` states. Failed downloads and digest mismatches are quarantined and never published as artifacts or imported as facts. A model string alone never binds one vendor's artifact to another vendor's device.

## Suggest a source through the issue form

Use the `Maintained source suggestion` form under `.github/ISSUE_TEMPLATE/`. What makes a source usable is defined in [CONTRIBUTING.md](CONTRIBUTING.md#suggest-a-maintained-source).
