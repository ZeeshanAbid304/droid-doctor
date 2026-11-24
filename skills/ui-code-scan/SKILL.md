---
name: ui-code-scan
description: Scans an Android project's source code (XML layouts and Jetpack Compose) for UI and stability bugs without running the app. Covers colors that don't match the app theme, inconsistent fonts, text sizes in dp, status bar and navigation bar problems, edge-to-edge and WindowInsets mistakes, fixed sizes that break on small phones or tablets, missing dark mode, orientation/rotation state loss, keyboard covering fields, back-button breakage with targetSdk 36, AdMob setup and banner placement (overlap, insets, test/real IDs, consent, init on main thread, unexpected interstitials), memory leaks, heavy work in composition, ANR risks, release build settings, and Android 12-16 crash traps (exported, PendingIntent flags, exact alarms, notification permission, foreground service type). Use when the user asks to "scan my app code", "check my UI code", "check theme colors", "why are my colors different", "status bar wrong color", "content under status bar", "check fonts", "find ANR risk", "check orientation", "check my ads code", or "review my layouts".
---

# UI Code Scan

Find UI, theme, system-bar, layout, ANR and crash-risk problems by reading the project's code. Works for XML views, Jetpack Compose, or both.

## Steps

1. **Find the project root.** Look for `settings.gradle` or `settings.gradle.kts` in the current directory or the path the user gave. If there are several app modules, scan the root (the script walks every module).

2. **Run the scanner** (it is in this skill's base directory, under `scripts/`):

   ```bash
   python3 "<this-skill-dir>/scripts/scan_ui.py" <project_root> \
     --out <project_root>/qa-report/static.json \
     --md  <project_root>/qa-report/static.md
   ```

   It only needs Python 3, with no extra packages. If `python3` is missing, try `python`.

3. **Check the findings.** The script works with patterns and can be wrong. For every **high** and **medium** finding, open the file at the reported line and confirm it's real:
   - Drop false positives. For example, a `PendingIntent` whose flags come from a variable that already holds `FLAG_IMMUTABLE`, or a `runBlocking` that only runs in tests or on a worker thread.
   - Keep confirmed ones, and note the real line and a short code snippet.

4. **Do the manual review the script can't do.** Follow `references/manual-checks.md`: theme structure, color contrast, typography consistency, inset handling for each screen, and adaptive layout. Read the theme files (`ui/theme/Color.kt`, `Theme.kt`, `Type.kt`, `res/values*/themes.xml`, `colors.xml`) first, because every other judgement depends on them.

5. **Report.** Group by category, with high severity first. For each issue give the problem in one plain sentence, `file:line`, why users would notice it (what breaks, and on which devices or Android versions), and the concrete fix (code if short). Write the confirmed list to `qa-report/static-confirmed.md`. If the full-check skill called this skill, return the list to it instead of writing a separate final report.

6. **Don't edit code here.** Offer `/droid-doctor:fix-issues` to apply fixes.

## Severity meaning

- **high**: crash, ANR, install or Play upload blocked, or content hidden or unusable for many users.
- **medium**: clearly wrong look on some devices (wrong colors, dark mode broken, text cut off, bars wrong).
- **low**: polish, consistency or accessibility improvement.

## Notes

- Google Play requires targetSdk 36 for new apps and updates (since 31 Aug 2026). With targetSdk 35 and up, Android 15+ forces edge-to-edge. With targetSdk 36, Android 16 ignores orientation locks and `resizeableActivity=false` on large screens (600dp and wider).
- The scanner skips `build/`, `test/` and `androidTest/` folders.
