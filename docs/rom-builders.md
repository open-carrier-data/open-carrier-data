# Ship OCD in a ROM

This guide is for people who build Android ROMs. It says how a ROM ships Open Carrier Data (OCD) as its carrier data, what the build must check before it ships, where the device's own fixes go, what the app does on its own, what leaves a phone, and what you owe the people who use your ROM.

Rule round 31 (2026-10-28) set these rules. Before it, only the owner's Galaxy S20 ran OCD's dataset. Now any ROM whose builder chooses OCD may ship it, once its build meets the ship minimum below. There is no further approval round: meeting the ship minimum is a build check, not a vote. Rule round 47 (2026-11-04) made the app the same on every phone, the S20 included: there is no owner build, no token and no exception. The app and OcdCarrierSettings side of round 47 ships in one ROM build, *being built*. Rule round 48 (2026-11-04) made the app invisible on a ROM and added one automatic send, after the person's own yes. Its relay is deployed, and sending stays closed until the question, the first-screen line and the privacy page are live in the same build ([What leaves a phone](#what-leaves-a-phone)).

> **Status on 2026-10-30.** The owner's S20 build (LineageOS 24.0 for microG, AOSP ImsStack) is the only ROM that ships OCD today. The parts of round 31 marked *being built* below are not in that build yet. OcdCarrierSettings is published as the second app of [ocd-android](https://github.com/open-carrier-data/ocd-android), in [`carriersettings/`](https://github.com/open-carrier-data/ocd-android/tree/main/carriersettings), with its own tags (`carriersettings/v1.0.1` today). Since rule round 37 the S20 builds it from there, pinned to that tag. The OCD app, OCD Android, is the other app in that repository.

## What OCD replaces

On a ROM that ships OCD, OCD's dataset is the phone's carrier data. It replaces Google's CarrierSettings files, AOSP's CarrierConfig assets and the ROM's own APN list. Google's values stay inside OCD as one source family, the Google lane, next to Samsung, Apple and the others ([ocd-dataset.md](ocd-dataset.md)).

- **OCD holds carrier data.** Your device tree keeps the device's own fixes (see [Device quirks stay in your device tree](#device-quirks-stay-in-your-device-tree)).
- **You decide.** Whether a ROM uses OCD is the builder's decision, made at build time. There is no safe mode and no on-phone switch that turns OCD off. Either the ROM ships OCD or it does not.
- **Emergency calls are not tested.** OCD never dials an emergency number and no test can place an emergency call. No record or screen says that emergency calls work.

## Two ways to ship it

1. **OcdCarrierSettings with a baked dataset.** The image carries OcdCarrierSettings, a build of Android's CarrierSettings app (package `com.android.carriersettings`) that serves OCD's dataset, and one complete dataset at a pinned commit. New data arrives with your ROM's updates. The module is OcdCarrierSettingsDataset in [ocd-android's `carriersettings/`](https://github.com/open-carrier-data/ocd-android/tree/main/carriersettings). Your ROM adds one manifest project pinned to a `carriersettings/v*` tag (never `main`), `PRODUCT_PACKAGES += OcdCarrierSettingsDataset`, your writer settings or explicitly none (SM5), and a baked dataset. [Add it to a ROM](https://github.com/open-carrier-data/ocd-android/blob/main/carriersettings/README.md#add-it-to-a-rom) has the steps and the build check.
2. **The same, plus the OCD app.** Your own build of the OCD app pulls the newest validated `main` commit, hands it to OcdCarrierSettings to install, and checks it on the phone without anyone seeing it. Whether the app pulls and installs is your choice as builder. Calls, SMS and USSD run only on the person's tap (SM9). The app asks the person once whether it may send a weekly summary, unless you set the question off (SM11).

If you take only OCD's APN file, for example into `vendor/apn`, [consume.md](consume.md) shows how. Pin a validated `main` commit, and take a change to an emergency APN row only with OCD's published read of it (SM6). `carrier-config-list.xml` stays reference-only: it has none of OcdCarrierSettings's safety rules, so CarrierConfig values reach a ROM only through OcdCarrierSettings.

### What the phone serves, in order

For each SIM, OcdCarrierSettings picks one OCD profile with OCD's own exact matcher ([ocd-dataset.md](ocd-dataset.md#profiles)) and builds its settings in this order. Later steps win.

1. Android's defaults.
2. OCD's `default` profile.
3. The Google-lane fill, for keys the profile does not publish.
4. The matched profile's values.
5. This phone's own local results, which no other phone is ever served (see [Results stay on the phone](#results-stay-on-the-phone)). No published result is served: `device-records.json` stays empty.
6. Last, your device tree's override and LineageOS's own fixed key, exactly as LineageOS's CarrierService applies them. This step also runs when OCD's dataset fails to load.

Between steps 5 and 6, OcdCarrierSettings enforces its fixed rules: group A (the emergency call keys), group B (the metered lists) and, on every phone, SM7. It enforces them with its own compiled-in copy, whatever the data says.

## The ship minimum, SM1 to SM11

A ROM may ship OCD as soon as all eleven hold in its build. Each one is there because it prevents a real harm.

| | In plain words | Why |
|---|---|---|
| **SM1, the component** | Serve OCD only through OcdCarrierSettings as built: the exact matcher, the Google-lane fill, the closed key list, groups A and B, the one-commit install, the crash guard, the last resort and the newer-pin check. OcdCarrierSettings carries no device values. | A prefix matcher gives Ecuadorian rows to Canadian SIMs; unread values reach the emergency path; a malformed value crashes the load; a metered list without `default` runs up data charges; a stale installed APN file outlives later builds. |
| **SM2, one carrier data source** | Ship no other carrier file that Telephony reads: no Google protobufs, no AOSP CarrierConfig assets as a second default. The build check proves it. | Two datasets with different match rules would decide a SIM's values, and no test would know which one did. |
| **SM3, the device** | Keep the device's own fixes in your device tree, applied last. The build check fails if the tree ships an override the image does not read. Before each build for a device ships, check on that device, with the previous build kept: IMS registers, and a call out over LTE stays up past 15 s, and so does one over Wi-Fi calling where the SIM has it. | Replacing CarrierSettings would otherwise drop a device's fixes without a sound. On the S20, without its fix, every VoLTE call was cancelled after 8 s. Only a call on the device shows such a quirk. |
| **SM4, a complete public dataset** | A build from public validated `main` alone gives every SIM its full settings, the Google-lane keys included. The build check lists every key that falls to Android's default because OCD withholds it for privacy, such as voicemail numbers. | Google's file sets about 160 keys for one German SIM. Android's defaults for missing ones would change codecs, SIP timers, IPsec and data retry, all untested. |
| **SM5, your own writer** | Only your ROM's build of the OCD app may write the dataset. Its certificate and package are build parameters, `OCD_WRITER_CERT` and `OCD_WRITER_PACKAGE`, with no default: set both, or set both to `none` and no app can write. A build with the provider and neither fails. Every call checks the caller. adb and root may read and clear, never write. Next to them sits the app's build switch, the string resource `ocd_week_report`, `ask` or `off`, default `ask`: **shipping the app with `ask` may make you share responsibility for the send**, so read [Your duties as a builder](#your-duties-as-a-builder). | Otherwise any app or a shell could replace the data every call depends on. |
| **SM6, the data pin and emergency rows** | Bake a validated `main` commit. `main` has no waiting period ([releases.md](releases.md#main-has-no-waiting-period)): run the phone guard and the F5 walk from your old pin to your new one, and read [changelog.md](changelog.md) before you move. OCD publishes an independent read for each `main` commit that changes emergency APN lines, in `generated/ocd-dataset/f5-reads.json` ([F5 reads](ocd-dataset.md#f5-reads)), and a build pin or a runtime install takes such a change only with that read. Once the emergency data test's first use has passed on your device family (SM10), only a change to the APN name or roaming protocol of the SIM's emergency row needs the read. | Emergency APN rows decide the data path of an emergency call over IMS, and without the emergency data test nothing on the phone checks them. One import bug has already put a foreign emergency row into OCD's file. |
| **SM7, every phone** | No test call runs by itself on any phone, so on every phone, the S20 included, OcdCarrierSettings serves the values below only where they equal the Google-lane value: VoLTE, Wi-Fi calling or SMS over IMS turned off, provisioning that turns voice off, a Wi-Fi-only calling mode, and values that hide or lock the VoLTE or Wi-Fi calling switch, remove the option to turn IMS off, or block APN editing. No automatic trial ever applies such a value. By a rough count this holds back about 1,250 values in about 650 of 6,789 profiles, 1,115 of them switches hidden or locked and 135 turned off. | These values are safe only when a test checks them first, and no automatic test can. A VoLTE off removes every call on a network without 2G or 3G, a Wi-Fi-only mode removes calls on Wi-Fi that cannot reach the carrier, and a lock-out takes away the person's own way out. |
| **SM8, tests calibrated per IMS stack** | The app's active results count only on an IMS stack where one calls-out pass has confirmed, against the stack's own logs, that the app reads the right bearer and media counters. Today that is AOSP ImsStack. On other stacks results read "not counted", and no automatic trial runs. | Other stacks fill other counters. An uncalibrated test can read a failed call as a pass and keep a broken value, or the other way round. |
| **SM9, calls and SMS on a tap** | Automatic runs use only what nobody can see, hear or pay for. Test calls, test SMS, balance USSD, Test now trials, the voice-loss hold split and MMS APN candidates run only when the person taps, on every phone. There is no opt-in to turn them on in the background. See [What the app does on its own](#what-the-app-does-on-its-own). | Otherwise the phone would ring or show a call screen at night, leave entries in the call log, send SMS nobody wrote, and cost money on some tariffs. |
| **SM10, the emergency data test per device family** | The emergency data test never runs by itself, and no person gets a tap for it. Only you, the builder, run it over adb, the same for every builder: first on a device family (modem and RIL) and IMS stack, with `adb logcat` streamed, under round 30's five first-run checks. Once that first use has passed, your build declares it. Only such a build grants the app `CONNECTIVITY_USE_RESTRICTED_NETWORKS`. | It opens an emergency bearer that the operator logs under the person's SIM, and another modem may handle an emergency data request without a call differently, for example by entering emergency mode. Only that device shows it. |
| **SM11, what leaves a phone** | Nothing leaves a phone by itself unless the person said yes. After that one yes, and only on a ROM install, the app sends one closed week report per SIM to OCD's relay, only on an unmetered network and never while roaming. It holds no identifier, no free text, no day or time and no phone numbers, call lengths or counts, though a result can show that calls happened that week, on mobile or Wi-Fi, whether they worked, and that one was outgoing, and the person can stop it at any time. A hand install never sends by itself. Any other result leaves only when the person taps and submits it under their own GitHub login. No result, sent or tapped, ever sets a value on any phone: a carrier value changes only through a source-backed change on `main`. The app's download from GitHub carries no identifier. See [What leaves a phone](#what-leaves-a-phone). | Data would otherwise leave strangers' phones without valid consent, a shared key would let anyone write to the dataset, and a fake or a bug would change what every phone serves. |

SM12, owner records on other phones, ended with rule round 47: no result of any account is served on another phone. Every ROM builder signs with their own key under SM5, and the S20 is one such builder.

Unchanged on every ROM: groups A and B, the privacy rules, the refusals around calls and emergencies, the roaming rule, the caps on test calls and IMS re-registrations, the stop events, and the hard limits. No emergency number is ever dialled, and no record holds a phone number, IMSI or ICCID.

### Your duties as a builder

Shipping the app gives you four duties. None of them needs any work at build time beyond what SM5 already asks, but the first two are yours to keep.

1. **Name the app in your ROM's public notes.** Say that the ROM ships the OCD app and what it does on its own (the [line below](#what-the-app-does-on-its-own) is enough). A person on your ROM never sees the app by accident, so they have no other way to learn who changes their carrier data when they look for the cause of a fault.
2. **Know what `ask` means.** The build switch, the app's string resource `ocd_week_report`, has two states, `ask` and `off`, default `ask`, and no on state. Anything but `ask` reads as off. With `ask` the app asks each person once, by itself. You do nothing, but you chose to ship an app that can send, and that may make you share responsibility for the send with OCD's controller (GDPR, § 25 TDDDG). This is not legal advice. To stay out of it, overlay `ocd_week_report` with `off` in your build of the app, next to `OCD_WRITER_CERT` and `OCD_WRITER_PACKAGE`: the app then never asks and never sends.
3. **Never answer for the person.** Silence, a swipe, a build default, a preset, a script or your own choice never counts as a yes. Only the person's own tap does, and docs alone never count as telling them. Your setup flow may ask instead of the app's notification, but only by opening the app's own question screen, `WeekQuestionActivity`: that screen is the only place a yes can be given. It is guarded by `MODIFY_PHONE_STATE`, and no extra answers it. A screen of your own with the same words records nothing, because the app would never hear the answer. Once the question screen has opened, the app skips the notification and never asks again, so leaving it unanswered stays no.
4. **Leave the app in sight of Settings.** The app has no icon on a ROM install, and it stays listed in Settings > Apps, where it can be disabled. Disabling is the way back to the build's dataset without a PC. Never hide it from the app list or remove its entry in About phone: a hidden privileged app with network access looks like spyware, and the person must be able to reach Resume and the send switch.

### When the app's tests get something wrong

There is no safe mode. These remain:

- **No automatic call test exists.** An automatic result stops at `signed_in`, and registered IMS does not mean calls work: the S20 once registered and still lost every call. Only a real call or a call the person tapped can give `works` or `calls out`. A phone can stay "signed in" for days, and Wi-Fi calling may stay unproven for a long time on a phone that rarely calls over Wi-Fi. Screens and records say "signed in", never "works". So do not ship a value because you expect phones to test calls: check it yourself (SM3).
- **Repair after a measured failure.** A healthy phone gets no trials: a trial can lose a real incoming call and drop data, and gains only "still registered". The normal path on every phone, for installs, the 14-day re-check and new SIMs, is passive: no overrides, calls or SMS. Overrides and APN swaps run by themselves only after a failure measured on that phone, judged by IMS voice registration and data, in an idle moment, on a calibrated stack (SM8), within the caps and the existing refusals. An MMSC probe failure alone opens nothing. A failure counts only when an alternative passes. When IMS voice is lost after a change, the next candidate is applied at once, at home and abroad. The build's dataset is the last candidate.
- **The real-call watch.** A value can keep IMS registered and still break calls, so after an install changes a voice, Wi-Fi calling or SMS value the app watches that SIM's real outgoing calls. It dials nothing. A failure is a real outgoing call that never went active, with one call only, a fresh disconnect and a code on a closed list. Busy, not found, a bad address, rejected, forbidden, unwanted, no answer and a hang-up never count. A call that went active disarms the watch. Two failures put the phone straight on the voice-loss hold, with no candidates. The watch writes no failed result.
- **The voice-loss hold.** When only the build's dataset brings voice back, OcdCarrierSettings keeps serving it. It stays held until the person taps: on the tap the app finds the values that broke voice, and the newest dataset is served with working values in their place. A hold from the real-call watch has no split, because registration cannot judge it: it ends on the person's Resume tap. If the same values break voice a second time, the phone stops changing anything until the person taps Resume or a newer build arrives.
- **Disabling the app.** When the person disables the OCD app in Android's Settings, pulls, installs and tests stop at once, and OcdCarrierSettings serves the build's dataset, with SM7. This works while the app crashes, while roaming and without a PC. Only an explicit disable counts, never a crash or an app update. When the app is enabled again, it checks every value that differs from the build's, passively.
- **OcdCarrierSettings on its own.** Without the app, it serves the build's dataset when no dataset is installed (first boot, cleared data), when the installed one is corrupt, or when your new build pins a newer commit. It checks at boot and once a day; that check only compares your build's pin, and the app's pull has its own timing. The baked copy keeps all these roles, and it stays the last candidate in voice loss.
- **You, the builder.** The build switch, the previous build kept for a rollback, and adb.

## Device quirks stay in your device tree

OCD is for carriers. A value whose reason holds on every carrier is a device quirk, and it belongs in your device tree, not in OCD. A value measured on one device with one carrier stays a local result of that phone, and a report can open a source review.

- **Examples of quirks,** all from the S20: the radio reports no QoS sessions, so voice must run on the IMS default bearer; the GNSS chip fetches its own orbit files; ImsMedia has no EVS codec; a key exists only in one ROM's ImsStack fork. You control each of these. OCD cannot see any of them.
- **Where they go.** Use the override your ROM already applies after the carrier values:
  - on LineageOS, a `carrier_config_override.xml` in an overlay of `CarrierSettingsConfig`, next to LineageOS's own fixed key;
  - on AOSP, the CarrierConfig `vendor.xml` overlay (*being built* in OcdCarrierSettings).
- **Applied last.** OcdCarrierSettings applies your override after OCD's values and records, also when OCD's dataset fails to load. A carrier value or a record never overrides your fix.
- **Not tested over.** The app tries no other values and keeps no local results for a key your override sets on that phone. Such a test would only measure your own value.
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

## Results stay on the phone

A result such as "VoLTE works on S20 with o2, LineageOS 24.0 and AOSP ImsStack" stays on the phone that measured it as a value. After the person's yes, one flag per entry goes into the [weekly report](#what-leaves-a-phone), which counts it and sets nothing. The result belongs to one cell:

- the device (`Build.DEVICE` and model);
- the OCD carrier profile, or the network code plus GID1 or SPN for a SIM without a profile;
- the ROM family and build line, with its forks;
- the IMS stack, with its fork.

The phone serves its own result only in its exact cell. In a neighbouring cell, for example after a move to another ROM, it is only a first value to try when a repair runs. Local results lapse 90 days after their last measurement, with two exceptions: `emergency_default_won` and `winner_after_failure` no longer lapse, because nothing would test them again and a row or value that failed on that phone would silently return. They end when the row or key changes in the data, when the cell changes, after a tap test, or for emergency records after a manual adb run.

No result of any account, the owner's included, is served as a value on another phone. A carrier value changes only through a source-backed change on `main`. `generated/devices/device-records.json` stays an empty role, because readers refuse a pull without it ([ocd-dataset.md](ocd-dataset.md#records-by-cell-rule-round-31)).

The S20's device values, once records for every carrier, are back in the S20's device tree. OCD dropped those records and the `configured_device` kind once the S20 build with that override had passed on the phone.

## Emergency settings

- **They update.** Each dataset brings the Google lane's newest emergency settings at once. A value from another source is served only after an independent read of it has passed and is published on `main` ([Group A reads](ocd-dataset.md#group-a-reads)). The publisher lists each new such value at once in `generated/ocd-dataset/group-a-pending.json`, and an agent reads it; GitHub's free runners run no agent. A read that holds keeps the Google-lane value.
- **Display-only keys** leave group A after a read finds they change only what is shown or logged.
- **Emergency numbers are not OCD data.** Android takes them from the network, the SIM, the modem and its own emergency number database, which updates with Android. OCD publishes no emergency number list. The dial prefix and replace keys stay in group A.
- **Android's default emergency APN.** When a SIM's own emergency APN row fails a builder's manual run of the emergency data test (SM10), the app tests Android's default (`sos`, IPv4v6) in its place: OcdCarrierSettings installs the same APN list without that row for a moment and restores the full list at once, with the person's chosen APN set again. A call during that moment delays only the restore. If the default works and the row does not, the row stays out for that cell (*being built*).

## What the app does on its own

On a ROM install the app is invisible to anyone who is not looking for it. It has no launcher icon. Its entry is the last row of Settings > About phone, and Settings search finds it by words such as calls, VoLTE, Wi-Fi calling and carrier. That screen holds the send switch, the last week report in full, Resume and this one line:

> On its own, this app only reads the phone's state, installs new carrier data, repairs a failure it measured and, if you said yes, sends OCD one weekly summary. It makes no calls and sends no SMS unless you tap for it.

An install by hand has no background work and sends nothing by itself. It keeps its launcher icon and today's line:

> On its own, OCD Android installs new carrier data, reads the phone's state, watches real calls and SMS, and repairs a measured failure. It calls, texts or dials a code only when you tap, and it sends a report only when you submit it.

**Automatic, on every phone.** Only what nobody can see, hear or pay for:

- passive reads and the IMS registration state;
- watching real calls and SMS;
- network-reach counters where a stack already has them;
- data and DNS probes after a measured failure: once per SIM per 6 hours, never while roaming or with mobile data off, with no throughput sample. The 14-day MMSC probe is the only routine probe;
- dataset installs ([How new data reaches a phone](#how-new-data-reaches-a-phone));
- repair after a measured failure ([When the app's tests get something wrong](#when-the-apps-tests-get-something-wrong)).

Automatic runs show no notification. Only a run where calls were lost, or the person must act, shows one, and the voice-loss and stop-event notifications stay. The voice-loss notice has its own ID and comes back at most once a day until Resume, so a swipe cannot strand the person. The one other notification is the question about the weekly summary, once per install. Reading carrier SMS keeps its own switch, off by default.

**Only on the person's tap,** on every phone: a test call, a test SMS, the balance USSD, Test now trials, the voice-loss hold split and MMS APN candidates.

- A tapped call is not muted. It uses the normal call screen, the person can hang up, and it stays in the call log. The app ends it after the media window.
- Numbers and USSD codes come only from the table in the signed app, never from pulled data. USSD keeps its exact-code list and 3 a day, and no menu step is automated.
- A tap keeps its limits: the SIM's own brand only, may-cost words on entries not marked free, no call for an SPN the table does not list, and the emergency-number refusal. The call words add that a mailbox call may mark a new message as heard. After a `not_received`, the SMS tap warns that the stored number may be wrong.
- An adb tap counts only as a one-off act. No scheduled adb tap of a test call runs on any phone.

**Never automatic,** even where research lists them as silent: a call to the phone's own number, a headless mailbox call, a call to a reserved fictional ("drama") number, SIP OPTIONS to the phone's own number, an MMS send request, and TS.43. Only a later rule round with evidence changes this list. No IMS stack change for NOTIFY or RTCP counters is authorised.

The carrier data itself needs no consent from the person, because you as builder decide whether the ROM uses OCD. The weekly send is different: it needs the person's own yes ([What leaves a phone](#what-leaves-a-phone)).

## How new data reaches a phone

No ROM build or release sits between `main` and a phone. A phone cannot be pushed to, so "as soon as it exists" means the next check. The baked copy keeps its roles; the ROM pin exists only for that copy.

- **On an unmetered network** one periodic job checks at WorkManager's 15-minute floor, with jitter and no idle, screen or schedule condition. A phone's hotspot counts as metered. It reads `generated/ocd-dataset/manifest.json` from `main` on the raw host with a conditional request and compares `dataset_digest` and `data_digest` with the installed set. That read is a hint only: no data is taken from it. Only a difference starts the normal pull by commit SHA, with F1 to F5 ([ocd-dataset.md](ocd-dataset.md#how-a-phone-takes-new-data)).
- **On 403 or 429** from either host, the app honours Retry-After and backs off, doubling up to 6 hours.
- **On a metered network** it checks every 6 hours and takes at most one full pull a day, and never while roaming or with Data Saver on. When OcdCarrierSettings asks again, only the daily limit lifts.
- **Activation.** If a SIM's served values and APN rows are unchanged, OcdCarrierSettings records the commit and skips the notify and the proof for that SIM. If they changed, it activates at the first moment with every Guard refusal clear, not roaming, with the screen off and no media or VoIP audio. The Guard refusals stay: during and 10 minutes after a call, 60 minutes after an emergency call, in emergency callback or SMS modes, when state is unreadable, and the first-hour restart check. The roaming wait stays too.
- **An older ROM** whose OcdCarrierSettings has no skip-notify keeps today's daily pull. The app tells it by the provider's protocol version.

Faster pulling ships in the same ROM build as SM7 everywhere, the real-call watch and skip-notify. There is no separate switch-on step.

## What leaves a phone

> **Status on 2026-11-05.** The relay is deployed, and sending stays closed: `relay_open` in `community/relay.json` is false, so no phone sends anything. `relay_open` turns true only when the question, the first-screen line and the [privacy page](privacy.md) are live in the same build.

Nothing leaves a phone by itself unless the person said yes. After that one yes, and only on a ROM install, the app sends one closed week report per SIM to OCD's relay, only on an unmetered network and never while roaming. It holds no identifier, no free text, no day or time and no phone numbers, call lengths or counts, though a result can show that calls happened that week, on mobile or Wi-Fi, whether they worked, and that one was outgoing, and the person can stop it at any time. A hand install never sends by itself. Any other result leaves only when the person taps and submits it under their own GitHub login. No result, sent or tapped, ever sets a value on any phone: a carrier value changes only through a source-backed change on `main`. The app's download from GitHub carries no identifier.

**The question.** The app asks by itself, once per install: one notification on the first boot with a SIM, opening one screen with equal Yes and No. Dismissed or ignored means no, and it is never asked again. If notifications are blocked, nothing is asked and the answer stays no. The words are on the [privacy page](privacy.md#the-question).

**The report.** `ocd-week-report` version 1 holds the ISO week, the app's major and minor version, the device's model (on OCD's public list, else `other`), ROM family, Android major and IMS stack, the carrier (OCD profile ID, or the home network code when no profile matches), and at most 16 pairs of entry and result. The [privacy page](privacy.md#what-is-sent) has the exact fields and the full list of what is never sent. Plan is never sent, so the published tree's plan level always reads `unknown`. A result is `works` (calls both ways by packet counts, round 26's L3), `calls_out` (an outgoing call only), `signed_in`, `service_off`, `not_possible` or `failed`. No sound was checked, nothing here speaks for emergency calls, and a call result shows that calls happened that week. On an uncalibrated stack (SM8) only `signed_in`, `service_off` and `not_possible` are sent.

**The send.** A small weekly step in the existing 15-minute job, on a privileged install only. A random moment in the week, one POST per SIM, HTTPS only, no redirects, no cookies, a constant User-Agent, at most 4 KB. Only on an unmetered network, not roaming, with Data Saver off and no call in progress, and with no notification. On any non-2xx the phone drops that week's report, keeps no queue and retries nothing. A missed week is dropped. Turning the switch off stops it at once and clears the local buffer.

**What stops it.** The relay's address is compiled into the APK. `relay_open` can only stop sending, never redirect it. Maintainers set it in [`community/relay.json`](../community/relay.json), the generator copies it into `generated/android/metadata.json`, and the app reads it there at its pinned commit, so it takes no request of its own. The flag is an input of `data_digest`, so a flip is new data, and a phone takes it at its next 15-minute check. OcdCarrierSettings never reads it. Absent, false, or a last pull of `main` older than 30 days means no send, so a ROM with no updates stops by itself and nobody has to renew the flag.

**The relay.** A small Cloudflare Worker on a free account, in its own public repository, [week-counts](https://github.com/open-carrier-data/week-counts). It holds no GitHub credential, so nothing on this path can write to the dataset. It stores counters only: no report body, IP address, hash of an address, headers or logs. Rows leave after 8 weeks.

**Fakes.** With no account they cannot be stopped, so they are bounded and made worthless. A counter stops at 500 a week and a week at 50,000 rows. A row at its cap is not published that week. Anything that is not on OCD's public lists is dropped. At Cloudflare's free limits the relay fails closed, and no payment method is on the account, so no bill is possible.

**Published.** Only rows with at least 3 reports in one ISO week, by month, as device > carrier > plan, in the week-counts repository and never on this repository's `main`. Every row reads "automatic, reported by phones, not checked by OCD, counts can be faked". Phones and ROM builds never read these counts. They never enter `observed/` or the manifest, and `validate` fails if they do. Nothing opens an issue or a source review by itself. A person or an agent may start one after reading them.

**The tap report stays as it is.** To send any other result, the person taps, reads the prefilled closed report and submits it under their own GitHub login, which the app never holds. The form says the issue is public under their account. A person without a GitHub account can read that report but not send it. No key or token exists in the APK, and none anywhere can write to GitHub for a phone. A report stays a pointer that can start a source review, never a value, under round 19's anti-fake rules ([community/README.md](../community/README.md)). Every such result reads "reported, not checked by OCD", with its date, a count of accounts and whether it is contested. No report or record holds a phone number, IMSI, ICCID, IMEI, SIP URI or IP address, and a report holds a date, never a time. The app's privacy scan runs again in the bot.

## Samsung's RIL can hide the network's refusal code

If you build for an Exynos Samsung phone, the radio library `libsec-ril-impl.so` may be hiding why the network refused a data connection. OCD Android reads the refusal code from Android to tell a wrong APN from a blocked account, so this matters for any test that depends on the real cause.

**What happens.** When the network refuses a data connection with a permanent 3GPP cause (for example ESM #33, "service option not subscribed"), Samsung's RIL replaces the code with a made-up value (-7). Once your fix passes the real code on, the RIL tries to be helpful in a second way: it asks the modem again at once, and the modem answers with a local back-off value (-8) while its retry timer runs. That second answer overwrites the first. Either way Android sees `UNKNOWN` and not the cause the network gave.

**The fix, three byte changes** in `vendor/lib64/libsec-ril-impl.so` (AArch64):

- Two places in `CustomizeFailCause` load -7 (`mov w24, #-7`, bytes `D8 00 80 12`). Change each to `mov w24, w19`, which keeps the network's code (`F8 03 13 2A`).
- One place in `ContextActivationDca::OnDataCallDisconnected` branches into the "try again due to throttle" re-ask (`tbnz w0, #31`, bytes `60 06 F8 37`). Change it to a `nop` (`1F 20 03 D5`). The first cause then goes out as final. The RIL still passes on its retry time, so Android keeps its own retry timing. The change applies to every cause, not only #33: failures that were going to be throttled are now reported at once.

**Proven only on the S20.** One phone (Galaxy S20, SM-G981B, `x1s`), one blob, one network. The blob is the one that TheMuppets extracts for that phone, SHA-1 `216643fd9da4fdfe944a53e3b372c00db3fe16ce`; with the three changes it is `c89f532a60e91c3f6bb6b39e6fd6f62969ba027f`, same length, 12 bytes different. Nothing is known about other Samsung phones or other firmware.

**Do not copy the offsets.** They belong to that blob (the changes sit at file offsets 0x2ee52c, 0x2ee588 and 0x2eddd8) and are different in every other build. Find the same code in your own blob: in `CustomizeFailCause`, look for the two places that load -7 into the register that is later returned as the cause (on the S20 one is followed by a compare with 35, the other by a byte load and a branch), and in `OnDataCallDisconnected`, look for the one branch taken when `CustomizeRetryTime` returned a negative number, which leads into calls to `IsNeedToSetPermanent` and `IsReasonApnThrottledAndPerm`. A disassembler such as Ghidra or rizin shows both quickly. Then check that your byte pattern occurs once in the file before you change it.

**How to carry it in a device tree.** The S20's device tree is not published (its base, [LineageOS's `android_device_samsung_universal9830-common`](https://github.com/LineageOS/android_device_samsung_universal9830-common), does not have the change), so here is the pattern. In `extract-files.py`, add `sig_replace` lines to the blob's fixups. Each pattern is the bytes to change plus a few bytes after them, so it matches in one place only:

```python
'vendor/lib64/libsec-ril-impl.so': blob_fixup()
    .sig_replace('D8 00 80 12 7F 8E 00 71 28 01 00 54', 'F8 03 13 2A 7F 8E 00 71 28 01 00 54')
    .sig_replace('D8 00 80 12 E8 E3 40 39 68 00 00 36', 'F8 03 13 2A E8 E3 40 39 68 00 00 36')
    .sig_replace('60 06 F8 37 E0 03 18 AA', '1F 20 03 D5 E0 03 18 AA'),
```

Those patterns are the S20 blob's. Yours will differ. Then put the hash of the fixed file in `proprietary-files.txt` so a build with another blob stops and does not ship a half-fixed one.

**How to test.** Set a made-up APN that no carrier has (use a new name each time: the modem's back-off timer runs per APN) and let the phone try to connect. With the fix, `logcat -b radio` shows the real cause in the data call result, for example `cause=SERVICE_OPTION_NOT_SUBSCRIBED(0x21)`, and Telephony logs the same. Without it you see `UNKNOWN(0x10000)` or a raw -7 or -8. The modem's end-reason log should show one refusal and no second request right after it. On the S20 it showed `/11` and no `/63`. Restore your APN list afterwards, and do not place any call as part of this test.

## Where the rules are

The full rule record is private. This page follows rule round 31, rule round 37 for where OcdCarrierSettings lives, rule round 47 for what runs by itself and how data travels, and rule round 48 for the invisible app, the weekly send and your duties. [ocd-dataset.md](ocd-dataset.md) describes the dataset files, [consume.md](consume.md) the APN file and the other outputs, and [releases.md](releases.md) the one channel.
