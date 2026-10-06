# Contribute to Open Carrier Data

This guide shows the three issue forms, the pull request path for tools and docs, and the checks to run before you submit. You do not need write access to the repo for any of them.

## Keep private data out

Before you post anything, remove every private value listed in [SECURITY.md](SECURITY.md). The issue forms and the pull request template point to the same list.

Safe values are the carrier name, country, brand, MCC/MNC, and Android carrier ID. A shortened ICCID prefix is safe when it is already public. APN values from public docs or the phone's settings screen are safe. So is a feature result such as "MMS receive works". A public APN username or password is fine only when it is a shared carrier setting. When unsure, leave the value out and describe the problem without it.

## Report wrong or missing carrier data

Use this path when a carrier is missing, a setting looks wrong, or you verified a fix on a device.

1. Open the `Wrong or missing carrier data` form at `https://github.com/open-carrier-data/open-carrier-data/issues/new/choose`.
2. Give the carrier name, country, and whether it is a host network or an MVNO.
3. Name the affected feature, what happens, and what you expected.
4. Add safe match details such as MCC/MNC, SPN, a GID prefix, or an Android carrier ID.
5. If you tested a fix, state the device, the setting you changed, the result, and the date.
6. Add a public source link if you have one.

## Suggest a maintained source

Use this path when you know an upstream that automation could import.

1. Open the `Maintained source suggestion` form.
2. Name the source, its owner, and what carrier facts it holds.
3. State its license or usage terms if known.

A usable source is public and preferably kept current by its owner (carrier, OEM, OS or public data project), can be refreshed by automation, and its terms allow publishing derived facts without the raw files.

## Improve tooling or docs

Open a pull request for schema, validator, generator, test, or documentation changes. To report a problem without a fix, use the `Documentation, schema, or tooling issue` form.

## Why carrier data changes are not accepted by hand

`carriers/` and the data files under `generated/` are rebuilt from the private pipeline on every publish; a hand edit would be overwritten and would carry false provenance, so change the source or importer instead (see [the curation section](#how-a-correction-reaches-stable-data)).

## How a correction reaches stable data

A correction reaches stable data in two ways. A maintained source publishes it and the import path picks it up. Or a maintainer changes an importer, mapping or source with the evidence in the pull request. A field report never changes a published value by itself. It starts a review of the source or importer behind the value, and a fix reaches the data through that source or importer. There are no per-carrier overrides.

## Run the local checks

Run the commands in the `validate` job of `.github/workflows/validate.yml` from the repo root; the pull request check runs the same. A snapshot past `stale_after` prints one warning and still passes. Only the daily `freshness-alarm` job runs the validators with `--freshness fail`.
