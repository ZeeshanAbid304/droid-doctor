---
name: device-test
description: Tests an Android app live on a connected phone or emulator over adb. It taps every button on every reachable screen to find exactly which button crashes or freezes (ANR), rotates every screen to catch crashes and lost state, and checks small phone, tablet, landscape, dark mode, large font and offline (airplane mode). It also checks ads overlapping content or buttons, measures cold start and scroll jank, and runs a monkey stress test that keeps going after crashes. Then it reviews every screenshot. Use when the user asks to "test my app on device", "test on emulator", "find crashes", "check ANR", "check orientation/rotation", "check ads overlapping", "check different screen sizes", "test dark mode", "test big font", "test offline", "monkey test", or "check how my app looks on tablets".
---

# Device Test

Run the app on a real device or emulator, break it on purpose, and look at every screen.

## Before starting

1. Check `adb devices`. If no device shows up, tell the user to start an emulator (Android Studio > Device Manager) or plug in a phone with USB debugging on, then stop. If several are listed, ask which one and pass `-s SERIAL`.
2. **Tell the user to unlock the phone and leave it unlocked.** The script wakes the screen, keeps it on, and turns animations off, but it can't enter a PIN. Infinix, Tecno and Xiaomi phones also need **Install via USB** (and on Xiaomi, **USB debugging (Security settings)**) in Developer options.
3. Find the **package name**: `applicationId` in `app/build.gradle(.kts)` (plus `applicationIdSuffix` for debug, if set).
4. Build: `./gradlew :app:assembleDebug` (`gradlew.bat` on Windows). The APK is usually `app/build/outputs/apk/debug/app-debug.apk`. If the build fails, show the first real error and stop.
5. Warn the user in one line: for about 10–20 minutes the phone will change size, rotation, dark mode, font size and airplane mode, and taps will happen by themselves. Everything is restored at the end. Buttons that look dangerous (Delete, Logout, Buy, Send, ...) are skipped.

## Run

The scripts are in this skill's base directory, under `scripts/`. Run them with a long timeout (30 minutes):

```bash
bash "<this-skill-dir>/scripts/device_check.sh" -p <package> -a <apk> -o qa-report/device
python3 "<this-skill-dir>/scripts/analyze_ui_dump.py" qa-report/device/screens qa-report/device/explore \
    -p <package> --md qa-report/device/ui-analysis.md
```

On Windows, if `python3` isn't found, use `python`.

Options:
- `-c default,dark` to run only some configs
- `--max-taps 80 --depth 3` to explore bigger apps
- `--no-monkey` / `--no-explore` to skip those parts
- `--allow-risky` to also tap Delete, Logout and similar buttons (emulator only)
- `-e 3000` for more monkey events

To run only the explorer: `python3 scripts/tap_explorer.py -p <pkg> -c <pkg/.Activity> -o qa-report/device/explore`

**Login screens:** if the app needs a login, ask for a test account, or ask the user to log in once. Then re-run without `-a`, so the app data is kept.

## Review the results

1. **`summary.md`** gives the overview. If any config says "NOT IN FRONT" or the phone was locked, those screenshots are invalid. Ask the user to unlock the phone, re-run with `-c <those configs>`, and don't report them as app bugs.
2. **Tap explorer** (`explore/results.md`): every CRASH, FREEZE, ANR and CLOSED row names the exact button and screen. A CRASH row includes the exception and the first app stack frame: open that line in the code and explain the cause. A FREEZE means the main thread was blocked for 3s or more (real users get an ANR on their next touch). Find the blocking call behind that button.
3. **Rotation** (`explore/results.md`, Rotation table): CRASH ON ROTATION, STATE LOST (typed text gone), SCREEN CHANGED (content reset) and RESTARTED are orientation bugs. Compare `explore/screen_NN.png` with `screen_NN_land.png`.
4. **Configs:** `screens/<config>-crash.txt` exists when the app crashed in that config. A crash or blank screen in `offline` means network errors are not handled.
5. **Crashes / ANRs for the whole run:** `crash-types.txt` (unique exceptions with counts), `crash-stacks.txt`, `anr.txt`, `exit-info.txt`.
6. **Performance:** cold start over 1500 ms is medium; over 3000 ms is high. Janky frames over 10% or a 90th percentile over 32 ms means stutter. "Skipped N frames" over 30 means the main thread was busy (heavy work in composition, database or network on the main thread).
7. **`ui-analysis.md`:** views under the status or nav bar, cut-off, overlapping or truncated text, small touch targets, and **ads overlapping content, touching buttons, or sitting under the nav bar**.
8. **Look at every screenshot** (`screens/*.png`, `explore/*.png`) with the Read tool, using `references/visual-review.md`. Report only what you can see, and name the file.
9. Write `qa-report/device-confirmed.md`. For each issue give the severity, the config or screen and button, what the user sees, the code cause (open the code to confirm), and the fix.

Don't change app code here. The `fix-issues` skill does that.

## Troubleshooting

- `uiautomator dump` fails on screens that animate constantly, or on `FLAG_SECURE` screens (which also give a black screenshot). Rely on the screenshot and say so.
- If the explorer shows "could not reach" for a path, the screen changes between launches (random content or a login state). Explore deeper by hand if it matters.
- Android 13 and lower cap font scale at 1.3. Offline mode needs Android 11 or higher.
