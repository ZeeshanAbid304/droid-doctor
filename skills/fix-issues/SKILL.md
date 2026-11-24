---
name: fix-issues
description: Fixes the problems found by the droid-doctor checks (the QA report): all of them, only high/medium, or chosen IDs. Covers crashes, ANRs, status/navigation bar and edge-to-edge, theme colors and dark mode, fonts, layouts on different screen sizes, orientation and state loss, ad placement and AdMob setup, low ads show rate (AdMob report), Crashlytics crashes and ANRs, back-button handling, memory leaks and build settings. Edits the Kotlin/Compose/XML/manifest/Gradle files, rebuilds, re-tests on the device, and marks each issue Fixed in the report. Use when the user says "fix all issues", "fix the issues", "fix QA-03", "fix all high issues", "fix orientation", "fix ads overlapping", "fix show rate", "fix Crashlytics crashes", "fix the status bar problem", "apply the fixes", or after a full-check report.
---

# Fix Issues

Apply fixes from `qa-report/QA_REPORT.md` (or from `static-confirmed.md` / `device-confirmed.md`), then prove that they worked.

## 1. Pick the issues

- Read the latest report. If there is none, run the `full-check` skill first (it ends by offering this fix).
- If full-check already passed a selection (all / high+medium / IDs), use it. Otherwise ask with AskUserQuestion: **Fix all issues (Recommended)**, **High + medium only**, **Choose by ID**, **Cancel**.
- "Fix all" means every issue in the report, including low ones.
- The user can name a topic instead of IDs ("fix orientation", "fix ads overlapping", "fix dark mode"). Select every issue in that category.

## 2. Safety first

- Run `git status --porcelain`. If the tree is dirty, say so and suggest committing first. If the user agrees, commit with the message "Before droid-doctor fixes", so all fixes are one easy-to-review diff.
- Never change `applicationId`, signing configs, real ad unit IDs, or API keys.

## 3. Fix, in this order

Order by risk: build/manifest crash traps, then field crashes and ANRs (most users first, from Crashlytics), crashes, ANRs, ads show rate (lowest % first), insets/bars, orientation/state, ads, theme/fonts/layout, and low polish last. Group fixes by file so each file is opened once.

- Read enough context (the whole composable/function, plus the theme files) before editing.
- Make the smallest correct change that matches the project's style (`MaterialTheme.colorScheme`, existing ViewModels, existing string resources). Don't add new libraries unless the fix needs one (for example, the UMP consent SDK for ads), and if it does, say so.
- Use `references/fix-patterns.md`. It has recipes for every rule in the report.
- Planted or test bugs (buttons that `throw` on purpose, `Thread.sleep` demo buttons): ask once whether to remove them or make them safe. Don't guess.
- When a fix needs a product decision (dark brand colors, keep `dynamicColor` or not, where the banner goes, whether to show an interstitial at all), ask with AskUserQuestion, giving a recommended option. Batch these questions into one prompt at the start of fixing, not one at a time.

## 4. Build

`./gradlew :app:assembleDebug` (on Windows: `gradlew.bat :app:assembleDebug`). Fix any compile error you caused. Repeat until it's green.

## 5. Verify

- **Show rate:** add the QA_ADS debug logger, go through the ad flows on the device, and run `showrate.py --logcat` (see the `ads-show-rate` skill). Units should reach the threshold locally.
- **Crashlytics issues:** reproduce with the device test where possible (explorer, rotation, offline, `am kill` for process death). Otherwise point to the line the fix covers.
- **Code:** re-run the `ui-code-scan` scanner. Each fixed rule must no longer fire at that file and line.
- **Device** (if connected): re-run `device_check.sh` with only what's needed. For example, `-c default,dark,font,land` for UI fixes, the explorer for crash, ANR or rotation fixes, or `--no-monkey` to save time. Run `analyze_ui_dump.py` again and compare the new screenshots with the old ones (look at both).
- An issue is **Fixed** only when the check that found it now passes. Otherwise mark it **Still failing** and explain why.

## 6. Update the report

Add a "Fix results" section at the top of `qa-report/QA_REPORT.md` with a table: ID | Title | Status (Fixed / Still failing / Skipped / Needs your decision) | Files changed. Keep the original issue text below it.

## 7. Tell the user

Give the totals (for example, "18 fixed, 1 needs your decision, 1 skipped"), the list of changed files, anything still to check by hand (screens behind login, release build with R8), and suggest committing.
