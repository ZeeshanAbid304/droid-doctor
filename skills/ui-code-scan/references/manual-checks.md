# Manual checks (what the script can't judge)

Work through each section. Only report a problem if you can point to the code.

## 1. Theme structure

- There must be ONE source of truth for colors: Compose `ColorScheme` in `Theme.kt`, or XML theme attributes. If both exist (hybrid app), check that the XML `colorPrimary` / `colorSurface` match the Compose scheme. If they don't, XML screens and Compose screens will look like two different apps.
- `darkColorScheme` must exist, with a value set for every role used in screens (`surface`, `onSurface`, `primary`, `onPrimary`, `background`, `surfaceVariant`, `outline`).
- `dynamicColor = true` replaces brand colors on Android 12+. Ask whether that's wanted. Most branded apps want `false`.
- XML: theme `parent` should be `Theme.Material3.DayNight.*` (or MaterialComponents DayNight). A `Light` parent means dark mode never works for XML screens.
- Splash screen: if `core-splashscreen` is used, `windowSplashScreenBackground` should match the first screen's background. Otherwise you get a color "flash" at startup.

## 2. Color contrast

For each text-on-background pair you can resolve (theme role pairs, plus any hardcoded pair you found), compute the WCAG contrast ratio:

```
L = 0.2126*R + 0.7152*G + 0.0722*B   (each channel: c/255, then c<=0.03928 ? c/12.92 : ((c+0.055)/1.055)^2.4)
ratio = (Lmax + 0.05) / (Lmin + 0.05)
```

Normal text needs at least 4.5. Large text (18sp and up, or 14sp bold) needs at least 3.0. Check light AND dark schemes. A quick way: run a short `python3 -c` with the formula.

## 3. Typography

- Compose: `Typography(...)` in `Type.kt` should set `fontFamily` for the styles in use. If the app ships custom fonts but `Typography` uses `FontFamily.Default`, the custom font never shows.
- Count distinct `fontSize`, `fontWeight` and `fontFamily` combos across screens. More than about 8 sizes means inconsistent design. Suggest mapping them to `MaterialTheme.typography` roles.
- XML: `textAppearance` styles should be used instead of a separate `textSize` and `fontFamily` on every view.
- Any `maxLines = 1` or `android:maxLines="1"` without ellipsis on long or translated text gets cut silently.

## 4. Status bar / navigation bar / insets (per screen)

For each Activity and each top-level screen:

- Compose: is there `enableEdgeToEdge()` in the Activity? Does each screen either use `Scaffold` and apply `innerPadding`, or apply `Modifier.safeDrawingPadding()` / `windowInsetsPadding(...)` / `statusBarsPadding()`? Screens without a Scaffold (login, onboarding, full-screen images) are the usual offenders.
- `LazyColumn` at the bottom of a screen should use `contentPadding` with the navigation bar inset. Otherwise the last item hides behind the gesture bar.
- Bottom sheets, FABs and bottom bars must respect `navigationBars` insets.
- Text fields near the bottom need `imePadding()` (Compose), or `adjustResize` plus insets (Views). Otherwise the keyboard covers them.
- Status bar icon color: on a light top bar the icons must be dark (`isAppearanceLightStatusBars = true`), and the reverse in dark mode. Check that it switches with the theme.
- Views: the root of each layout (or `CoordinatorLayout` / `AppBarLayout`) must handle insets via `fitsSystemWindows` or `ViewCompat.setOnApplyWindowInsetsListener`.

## 5. Adaptive layout / different devices

- Does any screen use `WindowSizeClass`, `BoxWithConstraints`, `layout-sw600dp` or `layout-land`? If not, and screens are lists or forms, flag "stretched on tablets" (medium) when the content is not width-limited (`widthIn(max = 600.dp)` or similar).
- Images with fixed `height` plus `ContentScale.Crop` on tablets show only a sliver. Check the aspect ratio approach.
- Rows with several `Text`s and no `weight()` overflow on 320dp-wide phones.
- Hardcoded `dp` paddings over 32dp on both sides leave too little room on small phones.
- Landscape: forms and screens without `verticalScroll` get cut off in landscape (no scrolling).

## 6. Lifecycle / crash patterns worth a look

- `collectAsState()` on flows in Compose without lifecycle awareness. Prefer `collectAsStateWithLifecycle()`.
- `LaunchedEffect(Unit)` doing navigation, which repeats on rotation in some setups.
- `Fragment` view binding not cleared in `onDestroyView` (leaks, and crashes when accessed after destroy).
- Navigation called twice quickly causes `IllegalArgumentException: navigation destination ... is unknown`. Debounce clicks or check the current destination.
- `SavedStateHandle` / `rememberSaveable` missing for form input, which is lost on rotation or process death.

## 7. Ads (if the app uses AdMob or another ad SDK)

- Where is each banner placed? It must be in its own slot (Scaffold `bottomBar`, or below the content in a Column/LinearLayout), never floating over content. It also needs navigation-bar insets.
- Is there clear space between ads and buttons (especially "Next", "Save" or bottom nav items)? Ads right next to buttons cause accidental clicks, which breaks AdMob policy.
- Full-screen ads: when are they shown? Not at app launch, not when a screen opens, not when the user presses back, and with a frequency cap.
- Test IDs in debug and real IDs in release, switched by build type (`buildConfigField` / `manifestPlaceholders`).
- `MobileAds.initialize` runs off the main thread, and only after consent (UMP) when consent is required.
- Native ads must show the "Ad" attribution label and AdChoices.
- Rewarded ads: is the reward granted only in `onUserEarnedReward`?

## 8. Orientation and configuration changes

- For each screen with user input or selection: is the state in `rememberSaveable` or a ViewModel?
- Data loading: in ViewModel `init` / `stateIn`, not in `LaunchedEffect(Unit)` (that reloads on rotation)?
- `android:configChanges` in the manifest: if it's present just to "fix" rotation, check that the Compose layout still reacts to the size change (it does) and that the Views layouts don't depend on `layout-land` resources (they won't reload).
- Dialogs and bottom sheets: do they stay open after rotation, or close and lose input?
- Rotation while a coroutine or network call runs: is the call in `viewModelScope` (it survives) or `lifecycleScope` / `rememberCoroutineScope` (it's cancelled and restarted)?

## 9. Offline and errors

- Every network call is wrapped in try/catch (or `runCatching`) for `IOException` / `HttpException`. The UI shows an error state with retry, not a crash or an endless spinner.
- Image loading has a placeholder and an error image.
