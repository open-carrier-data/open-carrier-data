# Source families

This page lists every source family that feeds the public data, what each one contributes, its terms, and how automation refreshes it. The exact revision and check date of each family sit in `generated/evidence-index.json` under `source_snapshots`.

## All source families at a glance

The table has one row per source name as it appears in profile evidence. The snapshot column names the `source_snapshots` record when its name differs.

| Source name in profiles | Snapshot record | Upstream | Contributes | Terms | Profiles |
| --- | --- | --- | --- | --- | --- |
| `aosp` | `aosp_carrier_config`, `aosp_carrier_ids` | AOSP `platform/packages/apps/CarrierConfig` and `platform/packages/providers/TelephonyProvider` | CarrierConfig values, Android carrier identity rules | Apache-2.0 | 235 |
| `lineageos` | same | `LineageOS/android_vendor_apn` | APN rows and MVNO selectors | Apache-2.0 | 1,064 |
| `lineageos_device_overlays` | `lineageos_device_carrier_overlays` | LineageOS device repos | device overlay carrier facts | NOASSERTION | 1,163 |
| `mobile_broadband_provider_info` | same | GNOME `mobile-broadband-provider-info` | carrier and APN facts | CC-PD | 836 |
| `apple_carrier_bundles` | same | Apple's carrier index | APN and MMS facts from IPCC packages | NOASSERTION | 1,881 |
| `google_carriersettings` | same | `GrapheneOS/adevtool` plus Google's live endpoint | match rules, APNs, CarrierConfig, capabilities | MIT and NOASSERTION | 3,446 |
| `google_pixel_vendor_carriersettings` | same | `TheMuppets` vendor snapshots | Pixel CarrierSettings facts | NOASSERTION | 2,236 |
| `samsung_omc` | none | Samsung firmware OMC baselines and GRAS checks | APN, capability, CarrierConfig, add-on facts | none asserted | 2,604 |
| `samsung_ims` | none | Samsung IMS maps in versioned firmware | positive IMS capability observations | none asserted | 629 |
| `fairphone_official_source` | same | Fairphone Gerrit manifest | carrier facts from Fairphone source | Apache-2.0 | 1,242 |
| `sony_open_devices_aosp` | same | `sonyxperiadev/local_manifests` | carrier facts from Sony AOSP trees | Apache-2.0 | 1,090 |

Four profile source names have no snapshot of the same name. `aosp` and `lineageos_device_overlays` map to differently named records. `samsung_omc` and `samsung_ims` have no snapshot record at all. Their check dates, both 2026-07-20 on 2026-09-24, are in `generated/devices/index.json` under `sources`. The oldest Samsung observation dates from 2026-07-13 and sets `checks_through`.

To print the profile count per source name, run:

```bash
python3 -c 'print(__import__("collections").Counter(s for p in __import__("json").load(open("generated/evidence-index.json"))["profiles"] for s in p["sources"]))'
```

To print the snapshot names, revisions, and check dates, run:

```bash
python3 -c 'print(*[(s["source_name"], s["revision_date"], s["checked_at"]) for s in __import__("json").load(open("generated/evidence-index.json"))["source_snapshots"]], sep="\n")'
```

The refresh methods below, the AOSP branch name, and the Samsung scope rules come from the private importer configuration. They cannot be checked from this repo.

## Freshness uses checked_at, not revision_date

Every `source_snapshots` record carries two dates. `revision_date` is when the upstream published that revision. `checked_at` is when automation last confirmed the revision with success.

Freshness uses `checked_at`. Unchanged upstream content stays current while its check is within 180 days. An observation with an older check is quarantined. The public side publishes the window as `checks_through` and `stale_after` in `generated/android/metadata.json`. On 2026-09-24 every snapshot record was checked that same day, but `checks_through` also follows the oldest observation review date. The oldest Samsung observation is from 2026-07-13, so `stale_after` stays 2027-01-09 until Samsung is refreshed. Past that date `tools/validate_public_carrier_data.py` warns by default and fails only with `--freshness fail`. The daily public job passes that flag and opens an issue labeled `stale-data` when it fails. Pushes and pull requests run in warn mode. The runner is offline and the private schedules are disabled, so no check arrives by itself.

## AOSP contributes CarrierConfig values and carrier IDs

Automation reads the `android-latest-release` branch of both AOSP repos and records the full commit ID. Terms are Apache-2.0, so redistribution is `permitted`.

## LineageOS contributes APN rows and device overlays

The APN repo is imported by commit ID under Apache-2.0. Device overlays are read across LineageOS device repos and recorded as one content hash. The project asserts no license for overlay content beyond what each repo declares, so those facts are `transformed_facts_only`.

## GNOME contributes public carrier and APN facts

The repo is imported by commit ID. Its dedication is public domain, recorded here as `CC-PD`.

## Apple contributes APN and MMS facts from digest-checked bundles

Automation reads Apple's carrier index over HTTPS and records its SHA-256. Every selected IPCC must match the SHA-1 or SHA-384 digest carried by the index before its facts are imported. An index can still point at an old HTTP CDN URL. Such a package is accepted only when its full digest matches.

The public repo never contains raw indexes, package URLs, package paths, selectors, or IPCC files. Unavailable packages and digest mismatches are quarantined and retried later. Apple declares no license, so the record says `NOASSERTION`.

## Google Pixel CarrierSettings contributes match rules, APNs, and capabilities

The maintained snapshot is the newest numeric Android branch in `GrapheneOS/adevtool`, which holds decoded CarrierSettings for supported Pixels. Automation records that revision, then checks every Pixel against Google's live endpoint. It applies a delta only when the endpoint's version is newer than the firmware baseline. `TheMuppets` vendor snapshots add a second, hash-recorded Pixel source.

Raw textproto and protobuf files, endpoint responses, and download URLs stay private. Pixel variants that disagree stay separate observations and become conditional or omitted in the merge. The GrapheneOS tooling is MIT. The project asserts no license for Google's data.

## Samsung contributes OMC facts and positive IMS observations

OMC facts come from firmware baselines and from GRAS update checks. A live GRAS observation needs a recent check and a complete model, CSC, sales code, Android version, OMC revision, and OMC version scope. A firmware observation needs a real release date.

IMS facts are positive, device-scoped observations of VoLTE, Wi-Fi calling, VoNR, video calling, SMS over IMS, and RCS. A false or absent Samsung switch is never published as proof that a carrier lacks the feature. Raw firmware, OMC files, requests, responses, signed URLs, and credentials stay private. The project asserts no Samsung license.

## Fairphone and Sony contribute facts from public AOSP trees

Both families are read from public AOSP-style manifests under Apache-2.0 and recorded by content hash. Only translated carrier facts are published.

## Device inventories use their own sources

The device catalog under `generated/devices/` uses its own sources. The broad Android inventory is Google's Play supported-devices CSV, recorded by SHA-256 and published as normalized identity fields under `NOASSERTION`. Identities that vanish from a later revision stay as `historical`. Apple product types come from the same carrier index as the bundles. LineageOS device repos and the carrier families above add exact model scope.

On 2026-09-24 the catalog's `index.json` lists 17 named sources. Print them with:

```bash
python3 -c 'print(*sorted(s["name"] for s in __import__("json").load(open("generated/devices/index.json"))["sources"]), sep="\n")'
```

## Artifact registries record what vendor indexes list

`generated/devices/android-carrier-artifacts.json` and `apple-carrier-artifacts.json` record which carrier artifacts a vendor index listed at the last check, with `indexed`, `extracted`, or `verified` states. Failed downloads and digest mismatches are quarantined and never published as artifacts or imported as facts. A model string alone never binds one vendor's artifact to another vendor's device.

## Suggest a source through the issue form

Use the `Maintained source suggestion` form under `.github/ISSUE_TEMPLATE/`. A usable source is refreshable by automation, has a clear carrier-data scope, and can be translated without publishing private material.
