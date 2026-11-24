# QA Report: <App name> (<applicationId>)

**Date:** <date> · **Build:** <versionName> (<versionCode>) · **targetSdk:** <n> · **minSdk:** <n>
**Tested on:** <device / emulator, Android version> or "Code scan only (no device)"

## Summary

| Severity | Count |
|---|---|
| 🔴 High | n |
| 🟠 Medium | n |
| 🟡 Low | n |

**Play Store readiness:** <Ready / Blocked: reason (e.g. targetSdk below 36, crash on launch)>

**Top problems**
1. QA-01: <one line>
2. QA-02: <one line>
3. QA-03: <one line>

## Fix results
_(filled in by fix-issues: ID | Title | Status | Files changed)_

## Issues

### 🔴 QA-01 · <Short title>
- **Category:** Crash / ANR / Status & navigation bar / Theme colors / Fonts / Layout / Orientation & state / Ads / Navigation & back / Performance & memory / Accessibility / Build & Play
- **Status:** Confirmed on device / From Crashlytics (N users) / From AdMob report (X% show rate) / Found in code
- **Where:** `path/File.kt:42` (and the device config if seen on device: `dark`, `font`, ...)
- **What users see:** <plain sentence>
- **Why:** <cause in 1-2 sentences>
- **Evidence:** code snippet / log line / `device/screens/font.png`
- **Fix:**
  ```kotlin
  // before
  ...
  // after
  ...
  ```

(repeat for each issue)

## Ads (only if the app shows ads)
- Placement: <banner slot, overlap/clearance results>
- Full-screen ads: <when shown, frequency cap>
- Setup: <APPLICATION_ID, test vs real IDs per build type, UMP consent, init thread>

## Ads show rate (if an AdMob/Firebase report was given)
| Ad unit | Format | Show rate | Wasted matched | Cause | Issue |
|---|---|---|---|---|---|
| <unit> | <fmt> | <x%> | <n> | <SR rule / cause> | QA-xx |

## Field crashes & ANRs (if Crashlytics/Play data was given)
| Crashlytics issue | Type | Users | Events | Root cause | Issue |
|---|---|---|---|---|---|
| <title/id> | Crash/ANR | <n> | <n> | <one line> | QA-xx |

## Orientation
- <per screen: OK / state lost / crash on rotation (from explore/results.md)>

## What passed
- <e.g. No crashes in 1500 monkey events>
- <e.g. Cold start 640 ms>
- <e.g. Dark mode colors correct on all checked screens>

## Not tested
- <e.g. Screens behind login, if no test account>
- <e.g. Device tests, if no device connected>

## Device test details
- Startup: <runs>
- Rendering: <janky %, p90>
- Screens: default · small · tablet · land · dark · font · offline (see `device/screens/`)
- Tap explorer: <screens explored, buttons tapped, problems> (see `device/explore/results.md`)
- Monkey: <events, crashes, ANRs>
