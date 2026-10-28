# Ship OCD in a ROM

This guide is for people who build Android ROMs. It says how a ROM ships Open Carrier Data (OCD) as its carrier data, what the build must check before it ships, where the device's own fixes go, what the opt-in on other people's phones covers, and why nothing leaves a phone by itself.

Rule round 31 (2026-10-28) set these rules. Before it, only the owner's Galaxy S20 ran OCD's dataset. Now any ROM whose builder chooses OCD may ship it, once its build meets the ship minimum below. There is no further approval round: meeting the ship minimum is a build check, not a vote.

> **Status on 2026-10-28.** The owner's S20 build (LineageOS 24.0 for microG, AOSP ImsStack) is the only ROM that ships OCD today. The parts of round 31 marked *being built* below are not in that build yet. OcdCarrierSettings lives in the owner's ROM tree and its source is not published yet. The OCD app is [ocd-android](https://github.com/open-carrier-data/ocd-android).

## What OCD replaces

On a ROM that ships OCD, OCD's dataset is the phone's carrier data. It replaces Google's CarrierSettings files, AOSP's CarrierConfig assets and the ROM's own APN list. Google's values stay inside OCD as one source family, the Google lane, next to Samsung, Apple and the others ([ocd-dataset.md](ocd-dataset.md)).

- **OCD holds carrier data.** Your device tree keeps the device's own fixes (see [Device quirks stay in your device tree](#device-quirks-stay-in-your-device-tree)).
- **You decide.** Whether a ROM uses OCD is the builder's decision, made at build time. There is no safe mode and no on-phone switch that turns OCD off. Either the ROM ships OCD or it does not.
- **Emergency calls are not tested.** OCD never dials an emergency number and no test can place an emergency call. No record or screen says that emergency calls work.

## Two ways to ship it

1. **OcdCarrierSettings with a baked dataset.** The image carries OcdCarrierSettings, a build of Android's CarrierSettings app (package `com.android.carriersettings`) that serves OCD's dataset, and one complete dataset at a pinned commit. New data arrives with your ROM's updates.
2. **The same, plus the OCD app.** Your own build of the OCD app pulls the newest validated `main` commit, hands it to OcdCarrierSettings to install, and tests it on the phone. Whether the app pulls and installs is your choice as builder. The person's opt-in decides only the active tests (SM9).

If you take only OCD's APN file, for example into `vendor/apn`, [consume.md](consume.md) shows how. Pin a release or a validated `main` commit, and take a change to an emergency APN row only with OCD's published read of it (SM6). `carrier-config-list.xml` stays reference-only: it has none of OcdCarrierSettings's safety rules, so CarrierConfig values reach a ROM only through OcdCarrierSettings.

### What the phone serves, in order

For each SIM, OcdCarrierSettings picks one OCD profile with OCD's own exact matcher ([ocd-dataset.md](ocd-dataset.md#profiles)) and builds its settings in this order. Later steps win.

1. Android's defaults.
2. OCD's `default` profile.
3. The Google-lane fill, for keys the profile does not publish.
4. The matched profile's values.
5. Measured records for this exact cell: the owner's published records, and this phone's own results, which never leave it (see [Records from the owner's phones](#records-from-the-owners-phones)).
6. Last, your device tree's override and LineageOS's own fixed key, exactly as LineageOS's CarrierService applies them. This step also runs when OCD's dataset fails to load.

Between steps 5 and 6, OcdCarrierSettings enforces its fixed rules: group A (the emergency call keys), group B (the metered lists) and, on a phone without a tester, SM7. It enforces them with its own compiled-in copy, whatever the data says.

## The ship minimum, SM1 to SM12

A ROM may ship OCD as soon as all twelve hold in its build. Each one is there because it prevents a real harm.

| | In plain words | Why |
|---|---|---|
| **SM1, the component** | Serve OCD only through OcdCarrierSettings as built: the exact matcher, the Google-lane fill, the closed key list, groups A and B, the one-commit install, the crash guard, the last resort and the newer-pin check. OcdCarrierSettings carries no device values. | A prefix matcher gives Ecuadorian rows to Canadian SIMs; unread values reach the emergency path; a malformed value crashes the load; a metered list without `default` runs up data charges; a stale installed APN file outlives later builds. |
| **SM2, one carrier data source** | Ship no other carrier file that Telephony reads: no Google protobufs, no AOSP CarrierConfig assets as a second default. The build check proves it. | Two datasets with different match rules would decide a SIM's values, and no test would know which one did. |
| **SM3, the device** | Keep the device's own fixes in your device tree, applied last. The build check fails if the tree ships an override the image does not read. Before each build for a device ships, check on that device, with the previous build kept: IMS registers, and a call out over LTE stays up past 15 s, and so does one over Wi-Fi calling where the SIM has it. | Replacing CarrierSettings would otherwise drop a device's fixes without a sound. On the S20, without its fix, every VoLTE call was cancelled after 8 s. Only a call on the device shows such a quirk. |
| **SM4, a complete public dataset** | A build from public validated `main` alone gives every SIM its full settings, the Google-lane keys included. The build check lists every key that falls to Android's default because OCD withholds it for privacy, such as voicemail numbers. | Google's file sets about 160 keys for one German SIM. Android's defaults for missing ones would change codecs, SIP timers, IPsec and data retry, all untested. |
| **SM5, your own writer** | Only your ROM's build of the OCD app may write the dataset. Its certificate is a build parameter (*being built*). Every call checks the caller. adb and root may read and clear, never write. | Otherwise any app or a shell could replace the data every call depends on. |
| **SM6, the data pin and emergency rows** | Bake a validated `main` commit or a release's commit. OCD publishes an independent read for each `main` commit that changes emergency APN lines (*being built*), and a build pin or a runtime install takes such a change only with that read. Once the emergency data test's first use has passed on your device family (SM10), only a change to the APN name or roaming protocol of the SIM's emergency row needs the read. | Emergency APN rows decide the data path of an emergency call over IMS, and without the emergency data test nothing on the phone checks them. One import bug has already put a foreign emergency row into OCD's file. |
| **SM7, no tester** | While no test calls run on the phone (no app, the app disabled, no opt-in, or an IMS stack not calibrated under SM8), OcdCarrierSettings serves the values below only where they equal the Google-lane value: VoLTE, Wi-Fi calling or SMS over IMS turned off, provisioning that turns voice off, a Wi-Fi-only calling mode, and values that hide or lock the VoLTE or Wi-Fi calling switch, remove the option to turn IMS off, or block APN editing. | These values are safe only when a test checks them first. Without a tester, a VoLTE off removes every call on a network without 2G or 3G, a Wi-Fi-only mode removes calls on Wi-Fi that cannot reach the carrier, and a lock-out takes away the person's own way out. |
| **SM8, tests calibrated per IMS stack** | The app's active results count only on an IMS stack where one calls-out pass has confirmed, against the stack's own logs, that the app reads the right bearer and media counters. Today that is AOSP ImsStack. On other stacks results read "not counted", and SM7 applies. | Other stacks fill other counters. An uncalibrated test can read a failed call as a pass and keep a broken value, or the other way round. |
| **SM9, the person's opt-in** | On other people's phones, test calls, test SMS and the emergency data test run only after the phone's user turns them on. See [What the opt-in covers](#what-the-opt-in-covers). | Without consent the phone would call the person's mailbox, send SMS they did not write and open emergency bearers under their SIM. |
| **SM10, the emergency data test per device family** | The emergency data test runs on a device family (modem and RIL) and IMS stack only after its first use has passed there once, with `adb logcat` streamed, under round 30's five first-run checks. You run that first use, then turn the test on in your build. Only such a build grants the app `CONNECTIVITY_USE_RESTRICTED_NETWORKS`. | Another modem may handle an emergency data request without a call differently, for example by entering emergency mode, and only that device shows it. |
| **SM11, nothing leaves the phone by itself** | See [Nothing leaves a phone by itself](#nothing-leaves-a-phone-by-itself). | Data from strangers' phones would otherwise leave without their action, and a stranger's result, a fake or a bug would change what every phone serves. |
| **SM12, owner records on other phones** | The owner's measured records are served on any phone in their exact cell. Where SM7 applies, the kinds SM7 lists are left out. Where the app tests, a record new to the phone is tested at once. | Outside its exact cell a record can mean something else: "VoLTE works on S20 with o2" holds only with the S20's own fix and the stack it ran on. |

Unchanged on every ROM: groups A and B, the privacy rules, the refusals around calls and emergencies, the roaming rule, the caps on test calls and IMS re-registrations, the stop events, and the hard limits. No emergency number is ever dialled, and no record holds a phone number, IMSI or ICCID.

### When the app's tests get something wrong

There is no safe mode. These remain:

- **The tests themselves.** A failure counts only when an alternative passes. When IMS voice is lost after a change, the next candidate is applied at once, at home and abroad. The build's dataset is the last candidate. Every served feature is tested again every 14 days.
- **The voice-loss hold.** When only the build's dataset brings voice back, OcdCarrierSettings keeps serving it. At the next quiet moment at home the app finds the values that broke voice, and the newest dataset is served with working values in their place. If the same values break voice a second time, the phone stops changing anything until the person taps Resume or a newer build arrives.
- **Disabling the app.** When the person disables the OCD app in Android's Settings, pulls, installs and tests stop at once, and OcdCarrierSettings serves the build's dataset, with SM7. This works while the app crashes, while roaming and without a PC. Only an explicit disable counts, never a crash or an app update. When the app is enabled again, it tests every value that differs from the build's.
- **OcdCarrierSettings on its own.** Without the app, it serves the build's dataset when no dataset is installed (first boot, cleared data), when the installed one is corrupt, or when your new build pins a newer commit. It checks at boot and once a day.
- **You, the builder.** The build switch, the previous build kept for a rollback, and adb.

## Device quirks stay in your device tree

OCD is for carriers. A value whose reason holds on every carrier is a device quirk, and it belongs in your device tree, not in OCD. A value that a test measured on one device with one carrier is an OCD record for that cell.

- **Examples of quirks,** all from the S20: the radio reports no QoS sessions, so voice must run on the IMS default bearer; the GNSS chip fetches its own orbit files; ImsMedia has no EVS codec; a key exists only in one ROM's ImsStack fork. You control each of these. OCD cannot see any of them.
- **Where they go.** Use the override your ROM already applies after the carrier values:
  - on LineageOS, a `carrier_config_override.xml` in an overlay of `CarrierSettingsConfig`, next to LineageOS's own fixed key;
  - on AOSP, the CarrierConfig `vendor.xml` overlay (*being built* in OcdCarrierSettings).
- **Applied last.** OcdCarrierSettings applies your override after OCD's values and records, also when OCD's dataset fails to load. A carrier value or a record never overrides your fix.
- **Not tested over.** The app tries no other values and writes no records for a key your override sets on that phone. Such a test would only measure your own value.
- **Checked by the build.** The build check fails when your tree ships an override the image does not read (SM3). On LineageOS that means the overlay's APK must be in the image.

The S20's override, as an example. Its manifest targets `CarrierSettingsConfig` in `com.android.carriersettings` as a static overlay:

```xml
<carrier_config>
    <!-- The radio reports no QoS sessions: without this, every VoLTE call is cancelled after 8 s. -->
    <boolean name="imsvoice.voice_on_default_bearer_supported_bool" value="true" />
    <!-- The same while roaming. The key exists only in the owner's ImsStack fork. -->
    <boolean name="imsvoice.voice_on_default_bearer_in_roaming_without_qos_bool" value="true" />
    <!-- ImsMedia has no EVS codec. -->
    <boolean name="imsvoice.audio_evs_support_bool" value="false" />
    <!-- The Broadcom GNSS chip fetches its own orbit files. -->
    <string name="gps.longterm_psds_server_1"></string>
</carrier_config>
```

An override never sets an emergency key without an independent read of it. The S20 leaves `imsemergency.skip_audio_dedicated_bearer_wait_timer_for_emergency_bool` unset, because the read of 2026-10-25 found that where it acts, an emergency call could wait in setup instead of falling back to 2G or 3G.

## Records from the owner's phones

OCD keeps measured results such as "VoLTE works on S20 with o2, LineageOS 24.0 and AOSP ImsStack" as records. Each record belongs to one cell:

- the device (`Build.DEVICE` and model);
- the OCD carrier profile, or the network code plus GID1 or SPN for a SIM without a profile;
- the ROM family and build line, with its forks;
- the IMS stack, with its fork.

A record is served as a value only in its exact cell (SM12). In a neighbouring cell, for example the same phone and carrier on another ROM, it is only a first value to try, and only where the app tests. A new build or stack version makes a record due for a test at once. Records lapse 90 days after their last measurement. Only the owner's token writes records, and the owner's build never runs on anyone else's phone. [community/README.md](../community/README.md#the-owners-measured-records) has the intake rules, and [ocd-dataset.md](ocd-dataset.md#per-device-records) the file.

Today's records still include the S20's device values as records for every carrier. Round 31 moves them back into the S20's device tree. Once the S20 build with that override has passed on the phone, OCD drops those records and the `configured_device` kind (*being built*).

## Emergency settings

- **They update.** Each dataset brings the Google lane's newest emergency settings at once. A value from another source is served only after an independent read of it has passed and is published on `main`. The read starts automatically as soon as such a value appears (*being built*). A read that holds keeps the Google-lane value.
- **Display-only keys** leave group A after a read finds they change only what is shown or logged.
- **Emergency numbers are not OCD data.** Android takes them from the network, the SIM, the modem and its own emergency number database, which updates with Android. OCD publishes no emergency number list. The dial prefix and replace keys stay in group A.
- **Android's default emergency APN.** When a SIM's own emergency APN row fails the emergency data test, the app tests Android's default (`sos`, IPv4v6) in its place: OcdCarrierSettings installs the same APN list without that row for a moment and restores the full list at once, with the person's chosen APN set again. A call during that moment delays only the restore. If the default works and the row does not, the row stays out for that cell (*being built*).

## What the opt-in covers

On a phone that is not the owner's, the app asks before it does anything that the person would notice. The opt-in is off by default. Its notice says in plain words what the app does:

- it calls the SIM's own mailbox, at most 10 times a day;
- it sends test SMS to the SIM's own number;
- it changes carrier settings;
- it briefly opens the emergency data connection, without a call.

Test calls and test SMS go only where OCD's list marks them free for that carrier, so nobody pays for OCD's tests. The emergency data test also needs your first use on that device family and your build switch (SM10).

Without the opt-in the app still watches: IMS registration, whether mobile data works, and the no-regression check. The data itself needs no opt-in, because you as builder decide whether the ROM uses OCD. Without the opt-in SM7 applies.

## Nothing leaves a phone by itself

- No automatic report and no telemetry. The app's download from GitHub carries no identifier.
- Results measured on someone else's phone are served on that phone only. They never change what any other phone serves.
- A person may send a report. It stays a pointer that starts a source review, never a value, under round 19's anti-fake rules ([community/README.md](../community/README.md)).
- Only the owner's token writes measured records to `main`, and the owner's build with that token never runs on anyone else's phone.
- No record holds a phone number, IMSI, ICCID, IMEI, SIP URI or IP address.

## Where the rules are

The full rule record is private. This page follows rule round 31. [ocd-dataset.md](ocd-dataset.md) describes the dataset files, [consume.md](consume.md) the APN file and the other outputs, and [releases.md](releases.md) the two channels.
