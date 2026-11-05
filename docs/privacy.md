# Privacy: OCD Android's weekly report

This page covers the one automatic send of OCD Android: the weekly report a phone sends after its owner said yes. Nothing is sent without that yes.

> **Status on 2026-11-05: sending is closed.** The relay is deployed, but `relay_open` in `community/relay.json` is false, so no phone sends anything. It stays false until this page, the question and the app's new first-screen line are live in the same build. The `validate` check refuses `relay_open: true` while this page has a "not filled in yet" mark.

## Who is responsible

| | |
|---|---|
| **Controller** | Open Carrier Data, the [open-carrier-data](https://github.com/open-carrier-data) project on GitHub |
| **Contact** | parcel-herbal-smog@duck.com |

A ROM builder who ships the app may share this responsibility ([rom-builders.md](rom-builders.md#your-duties-as-a-builder)).

## Why, and on what basis

**Purpose.** To learn which carrier features and data settings sign in or work on which phones, so OCD's public carrier data can improve.

**Legal basis.** Your consent: Article 6(1)(a) GDPR, and § 25(1) TDDDG for reading the results on your phone and sending them. You give it by tapping Yes. Ignoring or dismissing the question counts as no, and the app never asks again. A ROM builder cannot give it for you.

**Stopping.** You can stop at any time in Settings > About phone > Open Carrier Data. Sending stops at once and the phone clears what it had collected. Reports sent earlier stay counted.

## The question

The app asks this once per install, on one screen with equal Yes and No. Its one notification on the first boot with a SIM opens that screen, or the ROM's setup opens it instead:

> Help improve carrier settings? Once a week, on Wi-Fi and never while roaming, this phone can send Open Carrier Data which carrier features and data settings signed in or worked, with your phone model, ROM family, Android version, IMS software and carrier. It sends no name, phone numbers or SIM ID, no location, no day or time, and no call lengths or counts. But a result can show that this phone had calls that week, on mobile or Wi-Fi, whether they worked, and that one was outgoing. Your internet address reaches OCD's relay at Cloudflare (USA) while sending and OCD does not keep it. Results are published only for groups of phones and hold no ID, so what was sent cannot be taken back. You can stop any time in Settings > About phone > Open Carrier Data. [Details] [No] [Yes]

## What is sent

Only on a ROM install, once a week per SIM, one report of schema `ocd-week-report` version 1. Anything else is refused whole:

| Field | What it holds |
|---|---|
| `schema`, `schema_version` | the fixed name and version |
| `week` | the ISO week, this one or the last, for example `2026-W45` |
| `app_version` | major and minor, for example `0.5` |
| `device.model` | your phone's model if it is on OCD's public list, else `other` |
| `device.rom_family` | one of `stock`, `lineageos`, `other` |
| `device.android_major` | the Android version number |
| `device.ims_stack` | one of `phh_ims`, `samsung_ims`, `aosp_imsstack`, `other`, `not_known` |
| `carrier` | OCD's profile ID for your SIM's carrier, or the home network code when no profile matches |
| `results` | at most 16 pairs of `entry` and `result` |

An `entry` is `volte`, `vowifi`, `sms_over_ims`, `video_calling` or `vonr` with `:on` or `:off`, or `apn:` and a data setting from OCD's own data for your SIM's network. It is never a setting you or an employer added, and never one of the emergency type. A `result` is `works`, `calls_out`, `signed_in`, `service_off`, `not_possible` or `failed`. Each entry appears once a week, as one flag and never a count.

**What `works` and `calls_out` mean.** `works` means calls went both ways on this SIM, as far as packet counts show. `calls_out` means an outgoing call only. No sound was checked, so neither says you could be heard, and nothing here speaks for emergency calls. A `works`, `calls_out` or `failed` result shows that calls happened on the phone that week, and `calls_out` shows that one was outgoing. Only that one word leaves the phone: no packet counts, durations or call counts.

**Never sent:** your name, phone number, IMSI, ICCID, IMEI or any other SIM or device ID; any random, rotating, per-phone or per-install ID; plan, a bearer field, device codename, ROM build, firmware, SPN, GID1 or its prefix, Android carrier ID, data commit or digest, report hash; location, serving network or roaming state; a day or time; call counts, a direction field, duration or disconnect codes; the reason or method of a test. Results measured while roaming are dropped. Nothing from an emergency call ever counts. There is no bearer field, but the entry name itself, `volte` or `vowifi`, shows mobile or Wi-Fi calling.

**When.** At a random moment of the week, only on an unmetered network, never while roaming, with Data Saver off and no call in progress. It shows no notification. A missed week is dropped. There is no retry and no queue. The last report sent is shown in full on the same screen as the switch.

## Your internet address

Any connection shows your internet address to the other end, so it reaches the relay while the report is sent. OCD does not keep it: the relay stores no address, no hash of an address, no headers and no country, it writes no log, and logs, Logpush and traces are off in its configuration. Cloudflare carries the connection, and its own network and security systems see the address too.

## Who receives it

| Recipient | Role |
|---|---|
| **Cloudflare, Inc.** (USA) | Processor. It runs the relay and the counters on a free plan. Its data processing addendum names the EU-US Data Privacy Framework, with standard contractual clauses as the fallback. The relay's account is on Cloudflare's Self-Serve Subscription Agreement, whose section 6.1 brings in that addendum (version 6.4, read on 2026-11-05). Neither text names the free plan, so applying it here is our reading. |
| **GitHub, Inc.** (USA) | Hosts the published counts. It receives no report: a scheduled job reads only the counters that passed the threshold below. |
| **Everyone** | Reads the published counts. |

## How long

| Where | How long |
|---|---|
| Your phone | Results of the running week. The buffer clears after sending, after 7 days, or at once when you stop |
| The relay | Counters per week and group, deleted after 8 weeks |
| The published file | Public, with no end date, and copies may exist |

The relay keeps no report. It adds one to a counter for each entry, and stores the model, carrier and entry only as a digest.

## What is published

The counts appear in [open-carrier-data/week-counts](https://github.com/open-carrier-data/week-counts), by month and by device, carrier, ROM family, Android version, IMS software, entry and result. A row appears only with at least 3 reports in one ISO week. Smaller rows are never published and are deleted at 8 weeks. Every row reads "automatic, reported by phones, not checked by OCD, counts can be faked".

No count ever sets a value on any phone. A carrier value changes only through a source-backed change on `main`.

## What cannot be undone

A report holds no ID, so nobody can find your report afterwards, not even OCD. That means a report **cannot be found or removed once it is sent**. OCD cannot tell you which counts hold your reports, and it cannot take them out. This is why the question says so before you answer.

A group of 3 reports is not a promise that nobody could ever work out something about you: on a rare phone and a small carrier a group can be small. That is why this page says "no ID" and promises nothing more.

## Your rights

You can withdraw your consent at any time, as above. You can ask the controller about this processing, and you may complain to a data protection supervisory authority. For a report already sent, access and erasure are limited by what is said above: nothing links it to you.

## What this page does not cover

- **The tap report.** A report you open yourself and submit under your GitHub login is a separate path: [community/README.md](../community/README.md). It is public under your account.
- **The data download.** The app's download of carrier data from GitHub carries no identifier. GitHub sees your internet address, as with any connection.
- **Hand installs.** An app installed by hand never sends by itself.
