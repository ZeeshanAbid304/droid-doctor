# Crash & ANR catalog (Android)

Match the exception or ANR text, then check the listed causes in the code.

## Crashes

| Exception / message | Usual causes | Fix |
|---|---|---|
| `NullPointerException`, `!!`, `lateinit property ... has not been initialized` | `!!` on a nullable value; a lateinit used before set or after process death; a view accessed after `onDestroyView`; Intent extras missing | Null-safe access with a fallback UI state; init in the right lifecycle step; restore from SavedStateHandle; validate Intent extras |
| `IndexOutOfBoundsException`, `NoSuchElementException` (`first()`, `[0]`) | Empty lists from the network or DB; a list changed between the size check and the access; a stale position in an adapter | `getOrNull`, `firstOrNull`; use `bindingAdapterPosition` and check `NO_POSITION` |
| `IllegalStateException: Can not perform this action after onSaveInstanceState` | Fragment transaction or dialog shown after the app went to the background | Use navigation and show dialogs only when lifecycle is at least STARTED; `commitAllowingStateLoss` only for non-critical UI |
| `IllegalStateException: Fragment not attached to a context` | `requireContext()`/`requireActivity()` in a callback that runs after the fragment is gone | Collect in `viewLifecycleOwner.lifecycleScope` with `repeatOnLifecycle`, or check `isAdded` |
| `IllegalArgumentException: navigation destination ... is unknown` | A double tap navigates twice, or navigation from a stale screen | Check `currentDestination` before navigating, or debounce |
| `IllegalArgumentException ... FLAG_IMMUTABLE or FLAG_MUTABLE` | PendingIntent without a mutability flag (targetSdk 31+) | Add `FLAG_IMMUTABLE` |
| `SecurityException` (exact alarm, permission, `startForeground`) | Exact alarm without `canScheduleExactAlarms`; runtime permission not granted; FGS type/permission missing | Check permissions or capability first; declare the FGS type and permission |
| `ForegroundServiceStartNotAllowedException` | Starting a foreground service from the background (Android 12+) | WorkManager (expedited), or start it only from allowed contexts |
| `ForegroundServiceDidNotStartInTimeException` / `RemoteServiceException: Context.startForegroundService() did not then call Service.startForeground()` | `startForeground` not called within a few seconds of starting the service, or the service was stopped first | Call `ServiceCompat.startForeground` first thing in `onStartCommand` |
| `WindowManager$BadTokenException` / `WindowLeaked` | A dialog or popup shown after the Activity finished | Check `!isFinishing && !isDestroyed`; use DialogFragment or Compose dialogs tied to state |
| `TransactionTooLargeException` | Big Bundles: bitmaps or long lists in `onSaveInstanceState`/Intent extras | Keep IDs in the Bundle and the data in a DB or ViewModel |
| `OutOfMemoryError` | Large bitmaps, leaked Activities (static refs), unbounded caches | Coil/Glide with sizing; remove static Activity/View refs; LeakCanary in debug |
| `NetworkOnMainThreadException` | Network on the main thread | `withContext(Dispatchers.IO)` / suspend Retrofit |
| `UnknownHostException`, `SocketTimeoutException`, `SSLHandshakeException` (uncaught) | Offline or bad network not handled | try/catch around calls, an error UI state, retry |
| `JsonDataException`, `SerializationException`, `NumberFormatException` | Server returned an unexpected shape or empty value | Nullable or default fields; parse defensively; catch at the repository boundary |
| `SQLiteException`, `IllegalStateException: Room cannot verify the data integrity` | Missing migration, or the schema changed | Add a Migration (or `fallbackToDestructiveMigration` only if data loss is OK) |
| `ClassNotFoundException` / `NoSuchMethodError` in release only | R8 removed or renamed classes used by reflection (Gson models, enums) | Keep rules, or `@Keep` / `@SerializedName` |
| `Resources$NotFoundException` | A resource only in a qualified folder (`-v26`, `-night`, `-sw600dp`), or a vector on old APIs | Add a default resource |
| `DeadSystemException`, `DeadObjectException` | The system is dying or rebooting; usually noise | Ignore unless the volume is high; catch around binder calls if needed |
| `CancellationException` reported as a crash | A coroutine cancellation rethrown in the wrong place | Don't catch-all `Exception` around suspend calls without rethrowing CancellationException |
| `IllegalStateException` in `ActivityResultRegistry` (`registerForActivityResult` after STARTED) | Launcher registered late | Register as a property / in `onCreate` |
| AdMob `MobileAdsInitProvider ... Missing application ID` | No `APPLICATION_ID` meta-data | Add it to the manifest |

## ANRs

| ANR type (text) | Meaning | Usual causes / fix |
|---|---|---|
| `Input dispatching timed out` | Main thread didn't handle a touch or key within about 5 s | Main-thread disk/DB/network, `runBlocking`, `Thread.sleep`, heavy loops or sorting in click handlers or composition, lock contention, big JSON parsing. Move work to `Dispatchers.IO`/`Default`. |
| `executing service` / `Timeout executing service` | `Service.onCreate/onStartCommand` took too long | Do the work off the main thread (coroutine or WorkManager) |
| `Broadcast of Intent` | `BroadcastReceiver.onReceive` took too long | `goAsync()` plus a coroutine, or hand off to WorkManager |
| `ContentProvider not responding` | Slow provider `onCreate` or queries (often an SDK init via provider) | Lazy init; App Startup with deferred initializers |
| `did not then call Service.startForeground` | FGS start deadline missed | `startForeground` immediately in `onStartCommand` |
| Main thread in `QueuedWork.waitToFinish` / `SharedPreferencesImpl` | Many `apply()` calls flushing at `onStop`/`onPause` | DataStore; fewer writes; batch them |
| Main thread in `MobileAds.initialize` / ad SDK init / `WebView` init at startup | Ad or WebView SDK initialized on the main thread at launch | Initialize on a background thread after first frame; lazy WebView |
| Main thread `BLOCKED` waiting for a lock held by a background thread | Synchronized on the same object as I/O work | Don't hold locks during I/O; use coroutines with Mutex off main |
| Startup ANR in `Application.onCreate` | Too many SDK inits | Defer non-critical SDKs (App Startup lazy, after first frame) |

## Field-only causes to always consider

- **Process death:** the app is restored from the background without its in-memory singletons, so `lateinit` or static data is null. Test with `adb shell am kill <pkg>` while the app is in the background, then reopen it from Recents.
- **Rotation, dark-mode or language change:** Activity recreation.
- **Slow and low-RAM devices:** timing races and ANRs that don't happen on a fast phone.
- **OEM differences** (Xiaomi, Infinix, Samsung): background limits, missing intents (resolve with `resolveActivity`), WebView versions.
- **Android version-specific behavior:** check the OS distribution of the issue in Crashlytics.
