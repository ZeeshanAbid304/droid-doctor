---
name: crash-anr-fix
description: Fixes real-world crashes and ANRs reported by Firebase Crashlytics (or Play Console Android vitals). Pulls the issues through the Firebase MCP server's Crashlytics tools when it's connected, or from a report the user gives (pasted stack traces, a screenshot, a CSV/JSON/BigQuery export). It groups them, retraces obfuscated traces, maps every app frame to the code, finds each root cause, fixes all of them, verifies on the device, and can add notes to or close the Crashlytics issues when asked. Use when the user says "fix my Crashlytics crashes", "Firebase crash report", "fix ANRs from Firebase", "Play Console crashes", "check crash-free users", or gives a crash/ANR report.
---

# Crash & ANR Fix (Crashlytics / Play vitals)

## 1. Get the crash data (ask which source)

Ask with AskUserQuestion:
- **Firebase MCP (Recommended)** gives live Crashlytics data. Check whether Crashlytics MCP tools are available (tool names containing `crashlytics`, such as `crashlytics_get_report`). If they aren't, tell the user how to add them and wait:
  ```
  claude plugin marketplace add firebase/firebase-tools
  claude plugin install firebase@firebase
  ```
  (or `claude mcp add firebase npx -- -y firebase-tools@latest mcp`). It needs Node.js, and `npx firebase-tools login` once. Then restart Claude Code.
- **Paste or attach a report**: stack traces copied from Crashlytics or Play Console, a screenshot, or a CSV/JSON export (including the Crashlytics BigQuery export).
- **Only this device**: use `qa-report/device/logcat-crash.txt` / `anr.txt` from the device test.

### With the Firebase MCP
1. Find the app: the Firebase app ID for this `applicationId` (use the project/app listing tools if needed, or ask the user).
2. Get the `topIssues` report: crashes, ANRs and non-fatals. Also get the `topVersions` report, so you can check whether issues are in the latest version.
3. For each issue in scope (default: every crash and ANR with events in the last 7–30 days, top 20 by users), fetch a sample event (`crashlytics_batch_get_events` with the sample event from the report) to get the full stack trace, device, OS, and app version.
4. Save each stack trace into `qa-report/crashes/raw/<issue-id>.txt`, starting with a line `ISSUE <id> events=<n> users=<n> version=<v>`.

### With a report
Save what the user gave into `qa-report/crashes/raw/` as-is. For screenshots, type the visible stack trace into a .txt file.

## 2. Group and map to code

```bash
python3 "<this-skill-dir>/scripts/crash_parse.py" qa-report/crashes/raw/* --package <applicationId or code package> \
   --project . --md qa-report/crashes/issues.md --json qa-report/crashes/issues.json
```

- If it reports **obfuscated** traces, retrace with the matching release `mapping.txt` (`app/build/outputs/mapping/release/mapping.txt`, or ask the user for the one from the released build) using the `retrace` tool from Android SDK cmdline-tools. Then parse again. Don't guess from obfuscated names.
- Issues with **no app frames** (library or system only) still need a root cause. Use the catalog, the thread name, the device/OS distribution, and the last "Caused by".

## 3. Find the root cause of each issue

For every issue, open each mapped app frame and read the surrounding function. Then use `references/crash-catalog.md` to match the exception or ANR type to its usual causes. Write the cause in one plain sentence, and say **why it happens in the field** even if it never happens on your phone: process death, slow devices, Android version, OEM, offline, rotation, or a race.

For ANRs, look at what the **main thread** is doing in the trace: disk, database, network, locks, `runBlocking`, `Thread.sleep`, heavy work in composition or `onCreate`, slow broadcast receivers, or `SharedPreferences.apply` waiting at `onStop`.

## 4. Fix

- Fix the **root cause**, not the symptom. Don't wrap everything in try/catch; only catch where failure is expected (I/O, parsing, network). Never hide a crash just to make Crashlytics quiet.
- One issue at a time, highest users first. Group edits by file.
- Ask before product-visible behavior changes (for example, dropping a feature path or changing a permission flow).
- Use the recipes in `fix-issues/references/fix-patterns.md` and the catalog.
- When it's cheap, add a regression guard: a unit test for a parsing or null bug, or a `require(...)` with a clear message at the boundary.

## 5. Verify

- Build: `./gradlew :app:assembleDebug`.
- Reproduce where possible: use the `device-test` skill. The tap explorer, the rotation and offline configs, and `adb shell am kill <pkg>` while the app is in the background (for process-death bugs) reproduce most field crashes. Confirm each one is gone.
- For crashes you can't reproduce locally, explain why the fix covers the trace (point to the line).
- Re-run the `ui-code-scan` scanner to make sure no new problems were added.

## 6. Report, and update Crashlytics (only if asked)

Write `qa-report/crashes/CRASH_FIXES.md` with: issue (ID or title), type, users/events, root cause, fix (file:line), verified (yes / by reasoning). In `full-check`, add these as `QA-xx` issues instead.

If the Firebase MCP is connected and the user asks, add a note to each fixed issue (cause, fix, and the version that will contain it). Don't close issues until the fixed version is released and the user says so.

Remind the user that crash-free users only improve after the new version ships.
