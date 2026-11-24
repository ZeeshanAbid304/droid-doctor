---
name: ads-show-rate
description: Finds and fixes low AdMob show rate (impressions / matched requests) in an Android app. It reads an AdMob or Firebase ads report the user provides (CSV export, Google Sheets download, pasted table, or a screenshot), lists every ad unit below the threshold (default 70%), traces each one to the code that loads it, finds the cause (ads loaded but never shown, loads on every recomposition/resume/rotation, per-screen loaders, expired app-open ads, native ads not registered or batch-loaded, hidden or background banners, manual refresh), fixes it, and verifies with a debug ad logger on the device. Also works without a report, from the code alone. Use when the user says "show rate is low", "fix show rate", "ads show rate below 70", "matched requests but low impressions", "check my AdMob report", or "improve ad impressions".
---

# Ads Show Rate

**Show rate = impressions ÷ matched requests.** A low show rate almost always means the app loads ads that it never shows. It's a code problem, not an AdMob problem. (A low *match* rate is different: that's demand or fill, and code fixes won't change it much. Say so if you see it.)

## 1. Get the data (ask; don't assume)

Ask with AskUserQuestion which data the user has:
- **AdMob report file (Recommended).** In AdMob, go to Reports, open a report with the **Ad unit** dimension (add **Format**), and include the **Ad requests, Matched requests, Impressions and Show rate** metrics for the last 7–28 days. Then Export to CSV. The user attaches the file or gives its path.
- **Screenshot or pasted table** from AdMob or Firebase (the AdMob section in Firebase). Read the image or text and write it into `qa-report/ads/report.md` as a markdown table with the same columns. The parser reads markdown tables.
- **No report:** check the code only (step 3), plus the local on-device measurement (step 5).

Threshold: 70% unless the user says otherwise (`--threshold 80`).

## 2. Analyze the report

```bash
python3 "<this-skill-dir>/scripts/showrate.py" <report.csv> --project . --threshold 70 \
  --md qa-report/ads/show-rate.md --json qa-report/ads/show-rate.json
```

It sums rows per ad unit (daily exports are fine), computes show rate and wasted matched requests, sorts the units worst first, and lists where each low unit's ID or name appears in the code. If the report has no Ad unit ID column, ask the user which code constant or string each low unit maps to, or search the code for the unit name.

## 3. Find the cause in code

Run the `ui-code-scan` scanner and look at every finding with the **"Ads show rate"** category (`SR_*` rules) plus the `ADS_*` rules. Then, **for each low unit**, open the code that loads it and trace the whole life of that ad: where it's loaded, cached, shown, and destroyed. Check each cause in `references/show-rate-causes.md` and write down the ones that apply, with file:line. Usual suspects by format:

- **Interstitial / rewarded:** loaded on every screen open or onResume, but shown only sometimes (frequency cap, every Nth action, or only when the user does something rare). Loaded in an Activity that's destroyed or rotated before showing. Several copies loaded in different screens.
- **App open:** loaded at cold start but shown only if it arrives before the splash ends. No 4-hour freshness check. Shown on every foreground while a new one is loaded each time.
- **Banner:** loaded while hidden (gone, other tab or page, off-screen), reloaded in recomposition or onResume, a manual refresh timer, not paused in the background, several banners loaded but one visible.
- **Native:** `setNativeAd()` missing (no impression counted), `loadAds(n)` loading many at once, loading per list item bind, ads loaded for rows the user never scrolls to.

## 4. Fix

Use the show-rate recipes in the `fix-issues` skill's `references/fix-patterns.md` ("Ads show rate" section). The core fix is almost always one **AdManager**: one cached ad per ad unit, load only when nothing is cached and a show is likely soon, show when cached and allowed, then load the next one. Destroy and pause banners properly.

- Ask before changing *when* ads appear (frequency, placement). That's a product decision. Fixing *how* they load doesn't need asking.
- Never change ad unit IDs or the AdMob account settings.
- Also add the **debug-only ad logger** (`QA_ADS` lines, from the same reference), so step 5 can measure the result. It logs only in debug builds.

## 5. Verify on device

If a device is connected: build debug, run the app, and go through the flows that show ads (use the `device-test` tap explorer, or tap through the main flows with `adb shell input`). Then:

```bash
adb logcat -d > qa-report/ads/logcat.txt
python3 "<this-skill-dir>/scripts/showrate.py" --logcat qa-report/ads/logcat.txt
```

The local show rate per unit should now be at or above the threshold for the flows tested. Compare before and after, if you measured before the fix.
Be honest that the real AdMob show rate only updates after the new version is live with real users (give it a few days after release). Also, Google's own reporting differs for bidding units: Google notes partner bidding units can show a lower match rate and a higher show rate because matched requests are counted differently.

## 6. Report

Write `qa-report/ads/SHOW_RATE.md`: a table per unit (before %, cause, fix, file:line, local after %), then what to watch in AdMob after release. If running inside `full-check`, add these as `QA-xx` issues in the "Ads" category instead.
