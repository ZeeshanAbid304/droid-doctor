# droid-doctor

A Claude Code plugin that works as a QA tester for Android apps (XML views and Jetpack Compose).
It finds the bugs new apps usually ship with, then fixes them.

**What it finds**
- **Crashes and ANRs**: taps every button on every screen and names the exact button that crashes or freezes. A monkey stress test (that keeps going after crashes) and logcat / exit-info analysis back this up.
- **Orientation**: rotates every screen, catching crashes on rotation, typed text that's lost, screens that reset, and landscape layouts that are cut off or can't scroll
- **Ads (AdMob)**: banners covering content or buttons, ads touching buttons (accidental clicks), ads under the nav bar, unexpected interstitials, a missing APPLICATION_ID (crash at launch), test vs real IDs, missing UMP consent, init on the main thread
- **Theme colors**: colors outside your palette, hardcoded `Color.White`/`#hex`, broken dark mode, dynamic color replacing brand colors, low contrast
- **Fonts**: text size in dp, mixed font families, custom font never applied, text cut at large font scale
- **Status bar and navigation bar**: content under the bars, wrong icon color, Android 15 edge-to-edge, keyboard covering fields
- **Different devices**: small phone, tablet, landscape, dark mode, 2x font, offline
- **Android 12–16 traps**: `exported`, PendingIntent flags, exact alarms, notification permission, foreground service type, receiver flags, predictive back (`onBackPressed` stops working at targetSdk 36), targetSdk for Play
- **Performance and memory**: slow start, jank, heavy work in composition, static Activity leaks, big images
- **Ads show rate**: reads your AdMob/Firebase report, flags every ad unit below 70% show rate, finds the code cause (loaded but never shown, reloads on resume/recomposition, per-screen loaders, expired app-open ads, native not registered, hidden banners), fixes it, and measures local show rate with a debug logger
- **Field crashes and ANRs**: pulls Crashlytics issues through the Firebase MCP (or a pasted/exported report), retraces, maps them to code, fixes the root causes, and verifies on the device
- **Release config**: debuggable release, no minify, cleartext traffic

## Skills

| Command | What it does |
|---|---|
| `/droid-doctor:full-check` | Everything, then one report (`qa-report/QA_REPORT.md`), then asks **"Fix all issues?"** |
| `/droid-doctor:ui-code-scan` | Reads the code only (no device needed) |
| `/droid-doctor:device-test` | Runs the app on an emulator or phone with adb |
| `/droid-doctor:ads-show-rate` | AdMob report: fixes every ad unit with show rate below 70% |
| `/droid-doctor:crash-anr-fix` | Crashlytics / Play crashes and ANRs: finds the root causes and fixes them |
| `/droid-doctor:fix-issues` | Fixes all issues, high+medium, chosen IDs, or a topic ("fix orientation", "fix ads overlapping"). Then rebuilds, re-tests, and marks each issue Fixed in the report |

## Requirements

- Claude Code, run from your Android project folder
- Python 3 (standard library only)
- Android SDK platform-tools (`adb`) on PATH, plus an emulator or a phone with USB debugging
- Windows: Git for Windows (Claude Code needs it anyway), which provides bash for the device script

## Install

Local folder:
```
/plugin marketplace add C:\tools\droid-doctor
/plugin install droid-doctor@droid-doctor
```
From GitHub:
```
/plugin marketplace add <your-github-user>/droid-doctor
/plugin install droid-doctor@droid-doctor
```
Update after a new version:
```
/plugin marketplace update droid-doctor
/plugin update droid-doctor@droid-doctor
```

## Firebase / AdMob data (optional)

- **Ads show rate:** in AdMob, go to Reports, choose the Ad unit dimension (plus Format) and the Ad requests, Matched requests, Impressions and Show rate metrics, then Export to CSV. Attach the file, or just paste a screenshot.
- **Crashlytics:** install the official Firebase plugin for live data:
  ```
  /plugin marketplace add firebase/firebase-tools
  /plugin install firebase@firebase
  ```
  (needs Node.js, and `npx firebase-tools login` once). Or paste stack traces / attach an export.

## Use

1. Unlock the phone and turn on **Stay awake** in Developer options. (Infinix/Tecno/Xiaomi: also turn on **Install via USB**.)
2. In your project folder, run `claude` and type `/droid-doctor:full-check`.
3. When asked about **Extra data**, pick the AdMob report and/or Crashlytics if you have them.
4. When the report is ready, pick **Fix all issues**.

Output goes to `qa-report/`:
```
qa-report/
├── QA_REPORT.md            # issues with IDs, severity, fixes, plus the "Fix results" table after fixing
├── static.md / .json       # raw code-scan results
└── device/
    ├── summary.md          # startup, configs, explorer, jank, monkey, crashes, ANRs
    ├── explore/            # results.md (every button + rotation), screen_NN.png / _land.png
    ├── screens/            # default, small, tablet, land, dark, font, offline
    ├── ui-analysis.md      # under bars, cut, overlap, truncated text, ads overlap
    └── crash-types.txt, crash-stacks.txt, anr.txt, logcat.txt, exit-info.txt
```

## Safety

- Device settings (size, density, rotation, dark mode, font, airplane mode, animations, screen timeout) are restored at the end, even after Ctrl+C.
- The explorer skips buttons like Delete, Logout, Buy, Pay, Send and Share unless you pass `--allow-risky`. Use an emulator or a test phone anyway.
- Code is only changed after you choose a fix option. Commit first so the fixes are one clean diff.

## Run the scripts without Claude

```bash
python3 skills/ui-code-scan/scripts/scan_ui.py ./MyApp --md report.md
bash    skills/device-test/scripts/device_check.sh -p com.my.app -a app-debug.apk
python3 skills/device-test/scripts/tap_explorer.py -p com.my.app -c com.my.app/.MainActivity
python3 skills/device-test/scripts/analyze_ui_dump.py qa-report/device/screens qa-report/device/explore -p com.my.app
```

## License

MIT
