# Show-rate causes checklist

Show rate = impressions / matched requests. Each item below creates matched requests that never become impressions.
For every low ad unit, go through the list and mark which ones apply, with file:line.

## A. Loading too often
1. **Load in recomposition**: `loadAd()` in `AndroidView(update = {...})`, or in a composable body without an effect.
2. **Load on every resume/start**: `onResume`/`onStart` calls `load()` even when an ad is already cached.
3. **Load per screen**: each Activity/Fragment loads its own interstitial in `onCreate`. If the user leaves before the show moment, it's wasted.
4. **Load on rotation / config change**: an ad loaded in the Activity is lost on recreate, so a new one loads.
5. **Manual refresh timer**: `postDelayed`, `Timer`, or `while(true){ delay; load }` reloads banners.
6. **Retry loops**: a failed load retries immediately, many times. This mostly hurts match rate, but often comes together with duplicate loads.

## B. Loading but not showing
7. **Conditional show after unconditional load**: a load every time, but `show()` only every Nth action, only after a cap time, or only on a rare event.
8. **Show point is rarely reached**: the ad is loaded at app start for a screen most users never open. Load closer to where it's shown.
9. **Several loaders, one show**: the same format is loaded in multiple places, or with multiple cached copies, and only one gets shown.
10. **Expired before show**: app open ads (Google's guide: check that the load was less than 4 hours ago). Long-cached interstitials and rewarded ads can also go stale. Check freshness before showing and reload if stale.
11. **Splash race**: an app open (or interstitial) ad shown only inside `onAdLoaded` during a splash. When it loads late, the user is already in the app, and it's never shown.
12. **Show called on a dead Activity**: `show(activity)` after `finish()` or rotation, which fails silently. Check `isFinishing`/`isDestroyed` before showing, and keep the ad cached.
13. **Show blocked by consent or app state** after a load that should not have happened: check `canRequestAds()` before loading.

## C. Displayed but not counted
14. **Native without `setNativeAd()`**: the impression is never recorded.
15. **Native in Compose without a real `NativeAdView`** wrapping the assets: impressions aren't tracked reliably. Use NativeAdView via AndroidView, or the official Compose native sample pattern.
16. **Banner hidden**: `visibility=gone/invisible`, a zero-height container, a hidden tab or pager page, `alpha=0`, or covered by another view. The ad isn't really viewable.
17. **Banner off-screen**: at the bottom of a long scrolling list, below the fold. It's loaded immediately but rarely scrolled to.

## D. Background waste
18. **Banner not paused**: no `pause()`/`resume()`, so it keeps refreshing while the app is in the background.
19. **Not destroyed**: old AdViews keep living and refreshing after the screen closes.
20. **Preloading natives in batches**: `loadAds(request, 5)` when only 1–2 are shown per session.

## What NOT to blame on code
- **Low match rate** (requests vs matched) comes from demand, fill and mediation setup.
- For bidding ad units, matched requests are defined differently. Google says partner bidding units can show a lower match rate and a higher show rate in reports, without affecting revenue.
- Brand-new apps and ad units: numbers swing a lot for the first days.
