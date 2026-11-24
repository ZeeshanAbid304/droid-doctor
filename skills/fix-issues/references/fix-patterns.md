# Fix patterns

## Edge-to-edge + insets (Compose)

```kotlin
// Activity
override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()                 // before super/setContent
    super.onCreate(savedInstanceState)
    setContent { AppTheme { AppRoot() } }
}

// Screen with Scaffold: USE the padding
Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.home)) }) }) { innerPadding ->
    LazyColumn(contentPadding = innerPadding) { /* ... */ }
}

// Screen without Scaffold
Column(Modifier.fillMaxSize().safeDrawingPadding()) { /* ... */ }

// Text field near the bottom
Column(Modifier.fillMaxSize().imePadding()) { /* ... */ }
```

## Edge-to-edge + insets (Views)

```kotlin
enableEdgeToEdge()
setContentView(binding.root)
ViewCompat.setOnApplyWindowInsetsListener(binding.root) { v, insets ->
    val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
    v.updatePadding(left = bars.left, top = bars.top, right = bars.right, bottom = bars.bottom)
    insets
}
```

## Status bar icon color (replaces window.statusBarColor)

```kotlin
// Compose theme: icons follow light/dark theme
val view = LocalView.current
if (!view.isInEditMode) {
    SideEffect {
        val window = (view.context as Activity).window
        WindowCompat.getInsetsController(window, view).apply {
            isAppearanceLightStatusBars = !darkTheme
            isAppearanceLightNavigationBars = !darkTheme
        }
    }
}
```
Or `enableEdgeToEdge(statusBarStyle = SystemBarStyle.auto(Color.TRANSPARENT, Color.TRANSPARENT))`.
To color the area behind the status bar, draw a background behind the top bar (for example, the TopAppBar container color). The status bar itself is transparent.

## Theme colors

- Compose: replace `Color(0xFF...)` / `Color.White` with `MaterialTheme.colorScheme.<role>`. Map: background → `background`/`surface`; text on it → `onSurface`; brand → `primary`, text on brand → `onPrimary`; secondary text → `onSurfaceVariant`; dividers → `outlineVariant`.
- Add `darkColorScheme(...)` with the same roles. Ask the user for dark brand shades if they're unknown, and suggest lighter tones of the brand color.
- `dynamicColor = false` when the brand colors must stay.
- XML: `#hex` → `?attr/colorPrimary`, `?attr/colorSurface`, `?attr/colorOnSurface`, or `@color/x` with a `values-night/colors.xml` version.

## Fonts

```kotlin
val AppFont = FontFamily(Font(R.font.poppins_regular), Font(R.font.poppins_bold, FontWeight.Bold))
val Typography = Typography().run {
    copy(
        displayLarge = displayLarge.copy(fontFamily = AppFont),
        headlineMedium = headlineMedium.copy(fontFamily = AppFont),
        titleLarge = titleLarge.copy(fontFamily = AppFont),
        bodyLarge = bodyLarge.copy(fontFamily = AppFont),
        bodyMedium = bodyMedium.copy(fontFamily = AppFont),
        labelLarge = labelLarge.copy(fontFamily = AppFont),
    )
}
// screens: Text(text, style = MaterialTheme.typography.bodyLarge) instead of fontSize = 16.sp
```
XML: `android:textSize="16dp"` → `16sp`, and better, `android:textAppearance="?attr/textAppearanceBodyLarge"`. Set the app font once in the theme: `<item name="fontFamily">@font/poppins</item>` and `android:fontFamily`.

## Layout / sizes

- `Modifier.width(400.dp)` → `Modifier.fillMaxWidth().widthIn(max = 600.dp)`
- Fixed height around text → `heightIn(min = 48.dp)` / `android:minHeight`
- Row overflow → `Modifier.weight(1f)` on the flexible Text, plus `maxLines` and `overflow = TextOverflow.Ellipsis`
- Not scrollable in landscape → `Modifier.verticalScroll(rememberScrollState())`
- Tablet stretch → wrap content in `Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) { Column(Modifier.widthIn(max = 600.dp)) { ... } }`, or use `WindowSizeClass`.
- Small touch target → `Modifier.minimumInteractiveComponentSize()` or `IconButton` (48dp by default).

## ANR

- `runBlocking { repo.load() }` → `lifecycleScope.launch { repo.load() }` / `viewModelScope.launch`
- Room `allowMainThreadQueries()` → remove it, make DAO methods `suspend` or return `Flow`, and call them from a coroutine.
- `Thread.sleep(x)` → `delay(x)` in a coroutine.
- Sync HTTP → `withContext(Dispatchers.IO) { call.execute() }` or a suspend Retrofit function.
- SharedPreferences `commit()` → `apply()`.

## Crash traps

- Manifest: every component with an `<intent-filter>` gets `android:exported="true|false"`.
- `PendingIntent.getX(ctx, req, intent, 0)` → `PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT`.
- `registerReceiver(r, f)` → `ContextCompat.registerReceiver(ctx, r, f, ContextCompat.RECEIVER_NOT_EXPORTED)`.
- Exact alarms:
  ```kotlin
  if (Build.VERSION.SDK_INT < 31 || alarmManager.canScheduleExactAlarms()) {
      alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pi)
  } else {
      context.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}")))
  }
  ```
  Reminder or alarm apps can declare `USE_EXACT_ALARM`, which Play allows only for those app types.
- Notifications (Android 13+): declare `<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>` and request it with `rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission())`.
- Foreground service (Android 14+): `android:foregroundServiceType="dataSync|mediaPlayback|..."`, the matching `FOREGROUND_SERVICE_<TYPE>` permission, and `ServiceCompat.startForeground(service, id, notif, type)`.
- `!!` → `?.let {}` / `?: return` / `requireNotNull(x) { "why" }`.

## Orientation / state loss

```kotlin
// typed text, selected tab, dialog open, counters -> survive rotation
var name by rememberSaveable { mutableStateOf("") }
var tab by rememberSaveable { mutableIntStateOf(0) }

// screen data -> ViewModel (survives rotation), SavedStateHandle (survives process death)
class FormViewModel(private val state: SavedStateHandle) : ViewModel() {
    val name = state.getStateFlow("name", "")
    fun setName(v: String) { state["name"] = v }
}
```
- Data loaded in `LaunchedEffect(Unit)` reloads on every rotation. Load it in the ViewModel `init` instead.
- Content cut in landscape: add `Modifier.verticalScroll(rememberScrollState())` or use `LazyColumn`. For wide screens, use two panes (`WindowSizeClass` / `currentWindowAdaptiveInfo()`), or center the content with `widthIn(max = 600.dp)`.
- Crash on rotation: usually a Fragment without an empty constructor, a `lateinit` that isn't re-set after recreate, or a non-Parcelable object in a saved state. Fix the root cause. Don't add `android:configChanges` to hide it.
- Orientation lock (`screenOrientation="portrait"`) is ignored on tablets and foldables with targetSdk 36, so the layout must work in landscape. Don't depend on the lock.

## Ads (AdMob)

```xml
<!-- manifest, inside <application>: missing = crash at launch -->
<meta-data android:name="com.google.android.gms.ads.APPLICATION_ID" android:value="${admobAppId}"/>
```
```kotlin
// build.gradle.kts: test IDs in debug, real IDs in release
buildTypes {
    debug {
        manifestPlaceholders["admobAppId"] = "ca-app-pub-3940256099942544~3347511713"
        buildConfigField("String", "BANNER_ID", "\"ca-app-pub-3940256099942544/9214589741\"")
    }
    release {
        manifestPlaceholders["admobAppId"] = "<REAL APP ID>"
        buildConfigField("String", "BANNER_ID", "\"<REAL BANNER ID>\"")
    }
}
// buildFeatures { buildConfig = true }
```
Never invent real IDs. Leave `<REAL ...>` placeholders and tell the user to fill them in.

```kotlin
// init off the main thread (startup ANR)
CoroutineScope(Dispatchers.IO).launch { MobileAds.initialize(applicationContext) {} }

// Compose banner: below content, above the gesture bar, adaptive size, destroyed
@Composable
fun AdBanner(modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val widthDp = LocalConfiguration.current.screenWidthDp
    val adView = remember {
        AdView(ctx).apply {
            adUnitId = BuildConfig.BANNER_ID
            setAdSize(AdSize.getCurrentOrientationAnchoredAdaptiveBannerAdSize(ctx, widthDp))
            loadAd(AdRequest.Builder().build())
        }
    }
    DisposableEffect(Unit) { onDispose { adView.destroy() } }
    AndroidView(factory = { adView }, modifier = modifier.fillMaxWidth().navigationBarsPadding())
}

Scaffold(bottomBar = { AdBanner() }) { innerPadding ->
    Content(Modifier.padding(innerPadding))   // content never goes under the ad
}
```
- XML: don't float the banner with `layout_gravity="bottom"` over content. Use a vertical `LinearLayout` (content with `layout_weight=1`, then the banner) or a constraint chain, and pad the banner with navigation-bar insets.
- Ad overlapping or touching buttons (accidental clicks, an AdMob policy violation): add at least 8dp of clear space between ads and buttons, and never place an ad right next to primary actions.
- Interstitial or app-open ad shown in `onCreate` / `LaunchedEffect(Unit)` ("unexpected interstitial"): show it after a completed action (level end, after saving) with a frequency cap (for example, at most once every 2–3 minutes), and never on the first launch.
- Consent (EEA/UK/CH):
  ```kotlin
  val ci = UserMessagingPlatform.getConsentInformation(activity)
  ci.requestConsentInfoUpdate(activity, ConsentRequestParameters.Builder().build(), {
      UserMessagingPlatform.loadAndShowConsentFormIfRequired(activity) { if (ci.canRequestAds()) initAds() }
  }, { /* log */ })
  if (ci.canRequestAds()) initAds()
  ```
  This needs the `com.google.android.ump:user-messaging-platform` dependency. Tell the user they also need to set up the consent message in the AdMob console (Privacy & messaging).

## Back button (targetSdk 36 / Android 16 predictive back)

```kotlin
// Activity / Fragment (Views)
onBackPressedDispatcher.addCallback(this) {
    if (drawerOpen) closeDrawer() else { isEnabled = false; onBackPressedDispatcher.onBackPressed() }
}
// Compose
BackHandler(enabled = sheetOpen) { sheetOpen = false }
```
Remove `override fun onBackPressed()` and the `KEYCODE_BACK` handling in `onKeyDown`.

## Memory leaks

- Remove `companion object { var activity: Activity? }` / `object Foo { lateinit var context: Context }`. Pass a context when needed, or store `applicationContext`.
- Clear view binding in `Fragment.onDestroyView()` (`_binding = null`).

## Heavy work in composition (jank / slow launch)

```kotlin
// before
val result = (1..300_000).map { f(it) }.sorted().last()
// after
val result by produceState(initialValue = 0L, key1 = input) {
    value = withContext(Dispatchers.Default) { (1..300_000).maxOf { f(it) } }
}
```

## Raw threads and crash-prone code

- `Thread { work() }.start()` becomes `viewModelScope.launch(Dispatchers.IO) { runCatching { work() }.onFailure { /* show error */ } }`
- `list[3]` becomes `list.getOrNull(3) ?: return`
- `x!!.y` becomes `x?.y ?: default`

## Keyboard covering fields

`Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()))`. With Scaffold, add `contentWindowInsets = WindowInsets.safeDrawing`, or `imePadding()` on the content.

## Build / Play

- Release: `isDebuggable = false` (or remove it), `isMinifyEnabled = true`, `isShrinkResources = true`. Then build the release variant once to catch R8 problems.
- `usesCleartextTraffic="true"`: remove it, and switch URLs to https.

## Ads show rate (impressions / matched requests)

Core rule: **load only when nothing is cached and a show is likely soon; show from the cache; load the next one after showing.**

```kotlin
// Debug-only logger: lets the plugin measure local show rate (showrate.py --logcat)
object QaAds {
    fun log(event: String, unit: String, format: String) {
        if (BuildConfig.DEBUG) Log.i("QA_ADS", "QA_ADS event=$event unit=$unit format=$format")
    }
}

// One app-wide manager per full-screen ad unit (object or Hilt @Singleton)
object InterstitialManager {
    private const val UNIT = "home_interstitial"
    private var ad: InterstitialAd? = null
    private var loading = false
    private var loadedAt = 0L
    private const val MAX_AGE_MS = 60 * 60 * 1000L   // treat ads older than 1h as stale

    fun preload(context: Context) {
        if (loading || (ad != null && !isStale())) return
        loading = true
        QaAds.log("request", UNIT, "interstitial")
        InterstitialAd.load(context.applicationContext, BuildConfig.INTER_ID, AdRequest.Builder().build(),
            object : InterstitialAdLoadCallback() {
                override fun onAdLoaded(a: InterstitialAd) {
                    ad = a; loading = false; loadedAt = SystemClock.elapsedRealtime()
                    QaAds.log("loaded", UNIT, "interstitial")
                }
                override fun onAdFailedToLoad(e: LoadAdError) {
                    loading = false; QaAds.log("failed", UNIT, "interstitial")
                }
            })
    }

    private fun isStale() = SystemClock.elapsedRealtime() - loadedAt > MAX_AGE_MS

    /** Call at a natural break. Always calls onDone (shown or not). */
    fun showIfReady(activity: Activity, onDone: () -> Unit) {
        val a = ad
        if (a == null || isStale() || activity.isFinishing || activity.isDestroyed) {
            if (isStale()) ad = null
            onDone(); preload(activity); return
        }
        a.fullScreenContentCallback = object : FullScreenContentCallback() {
            override fun onAdImpression() { QaAds.log("impression", UNIT, "interstitial") }
            override fun onAdDismissedFullScreenContent() { ad = null; onDone(); preload(activity) }
            override fun onAdFailedToShowFullScreenContent(e: AdError) { ad = null; onDone(); preload(activity) }
        }
        QaAds.log("shown", UNIT, "interstitial")
        a.show(activity)
    }
}
```
- Remove every `InterstitialAd.load` from Activities, Fragments, `onResume` and composables. Call `InterstitialManager.preload(context)` once, at the start of the flow that ends with the ad.
- Frequency caps: check the cap **before preloading** (`if (cap.allowsSoon()) preload()`), not only before showing.
- Rewarded ads: the same manager pattern. Preload only on screens that have the "watch ad" button.

**App open ads** (Google pattern): preload in the `Application`, show on `ProcessLifecycleOwner` `ON_START` only if a fresh ad is cached (loaded under 4 hours ago). Never wait for it on the splash: if none is ready, continue and load for next time.
```kotlin
private fun isFresh() = ad != null && (System.currentTimeMillis() - loadTime) < 4 * 3_600_000L
```

**Banners**
```kotlin
val lifecycle = LocalLifecycleOwner.current.lifecycle
DisposableEffect(lifecycle) {
    val obs = LifecycleEventObserver { _, e ->
        when (e) { Lifecycle.Event.ON_PAUSE -> adView.pause(); Lifecycle.Event.ON_RESUME -> adView.resume(); else -> {} }
    }
    lifecycle.addObserver(obs)
    onDispose { lifecycle.removeObserver(obs); adView.destroy() }
}
adView.adListener = object : AdListener() {
    override fun onAdLoaded() { QaAds.log("loaded", "main_banner", "banner") }
    override fun onAdImpression() { QaAds.log("impression", "main_banner", "banner") }
    override fun onAdFailedToLoad(e: LoadAdError) { QaAds.log("failed", "main_banner", "banner") }
}
```
- Load in `remember {}` / `factory`, never in `update` or onResume. One banner per visible slot. No manual refresh timers (set the refresh in the AdMob console).
- Don't load a banner that is hidden (`gone`, an inactive tab or page, off-screen at the bottom of a long list). Load it when it becomes visible.

**Native ads**
- Always `nativeAdView.setNativeAd(ad)` after binding the asset views. Without it, no impression is counted.
- Load one ad at a time, when its slot is near the viewport (for example, 2 items before it). Keep a small cache (1–2) outside the adapter or LazyColumn, and never request inside `onBindViewHolder` / `items {}`.
- `destroy()` native ads that are replaced or off-screen for good.
- Log impressions: `AdLoader.Builder(...).withAdListener(object : AdListener() { override fun onAdImpression() { QaAds.log("impression", UNIT, "native") } })`
