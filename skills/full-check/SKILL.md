---
name: full-check
description: Runs a complete QA pass on an Android app, then offers to fix everything it found. Optionally includes the user's AdMob/Firebase report (fixes ad units with show rate below 70%) and Crashlytics crash/ANR reports. It scans the code (XML and Compose) for theme, font, status/navigation bar, edge-to-edge, layout, orientation/state loss, ads placement, back-button, ANR and crash problems. It tests the app live on a phone or emulator by tapping every button on every screen, rotating every screen, and checking small phone / tablet / landscape / dark / big font / offline, plus a monkey stress test. It writes one prioritized QA report and asks whether to fix all issues. Use when the user asks to "test my app", "QA my app", "full check", "check my app before release", "find all bugs in my app", "is my app ready for Play Store", or "check crashes, ANR, ads and UI issues".
---

# Full QA Check

Run both QA skills, merge the results into one report the developer can act on, then offer to fix everything.

## Steps

1. **Understand the project.** Read `settings.gradle(.kts)` and the app module's `build.gradle(.kts)`. Note the `applicationId`, `minSdk`, `targetSdk`, whether the UI is Compose, XML or both, whether the app shows ads (`play-services-ads`), and the main libraries. Tell the user in one or two lines what you found.

2. **Optional real-world data.** Ask once with AskUserQuestion (multiSelect, header "Extra data"):
   - **AdMob / Firebase ads report**: check and fix ad units with show rate below 70% (`ads-show-rate` skill)
   - **Crashlytics / Play crashes & ANRs**: check and fix field crashes and ANRs (`crash-anr-fix` skill)
   - **None, just test the app**

   For each one picked, follow that skill's "get the data" step now (export file, screenshot, or Firebase MCP), so the data is ready. Their analysis joins the report in step 5, and their fixes join step 6. Skip this question when the app has no ads SDK and the user didn't mention crashes. Then ask only about Crashlytics, or nothing.

3. **Code scan.** Follow the `ui-code-scan` skill of this plugin: run its scanner, confirm the high and medium findings in the code, and do its manual checks.

4. **Device test.** Run `adb devices`.
   - If a device or emulator is connected, follow the `device-test` skill: build the debug APK, run the device script (it includes the tap explorer, the rotation test on every screen, and the offline test), run the UI-dump analyzer on `screens/` and `explore/`, and review every screenshot.
   - If none is connected, ask once whether to start an emulator. If not, continue code-only and say clearly in the report what wasn't tested.
   - If the summary says the phone was locked or the app was not in front, ask the user to unlock the phone and re-run only the affected configs (`-c ...`). Don't report black screenshots as app bugs.

5. **Link code, device and report data.** When a device problem matches a code finding, merge them into one issue with both pieces of evidence. Examples:
   - The explorer's "CRASH tapping 'X'" plus the code line in its stack frame.
   - "STATE LOST" on rotation plus `COMPOSE_STATE_LOST_ROTATION`.
   - "Ad overlaps content" plus `ADS_BANNER_INSETS` / `ADS_XML_FLOATING_BANNER`.

   - Each low show-rate ad unit plus the `SR_*` code cause behind it (one issue per unit, with its show %).
   - Each Crashlytics issue plus the code line, and whether the explorer reproduced it on the device.

   Device evidence raises confidence. Mark each issue **Confirmed on device**, **From Crashlytics (N users)**, **From AdMob report (X% show rate)**, or **Found in code**. Field data (users affected, % show rate) decides priority within a severity.

6. **Write the report** to `qa-report/QA_REPORT.md` using `references/report-template.md`. Rules:
   - Order by severity (High > Medium > Low). Give every issue an ID: `QA-01`, `QA-02`, ...
   - Say in plain words what the app's user sees. Give the fix as concrete before/after code.
   - Cover every category that applies: Crash, ANR, Status & navigation bar, Theme colors, Fonts, Layout / screen sizes, Orientation / state, Ads, Ads show rate, Field crashes & ANRs (Crashlytics), Navigation / back, Performance / memory, Accessibility, Build / Play Store.
   - Add an **Ads** section summary when the app has ads (policy risks: overlap, accidental clicks, unexpected interstitials, consent).
   - Fill in "What passed" and "Not tested" honestly.

7. **Show the result and offer the fix.** Tell the user the totals and the top 3 issues in one line each. Then **ask with AskUserQuestion** (one question, header "Fix issues"):
   - **Fix all issues (Recommended)**: high, medium and low.
   - **Fix high + medium only**
   - **Let me choose by ID**: then ask which IDs, or accept a free-text list like "QA-01, QA-04".
   - **Not now, report only**

   If the user picks a fix option, continue straight into the `fix-issues` skill with that selection. Show-rate and Crashlytics issues are fixed there too, following the `ads-show-rate` and `crash-anr-fix` skills' fix and verify steps. Don't stop and ask them to type another command. If nobody answers (unattended run), don't fix anything; end with the report.

## Notes

- This skill only changes code after the user picks a fix option in step 6.
- If the user only wants one part ("just the code", "just on device"), run only that skill, then still offer the fix question.
- Re-running is safe: it overwrites `qa-report/`. Offer once to add `qa-report/` to `.gitignore`.
