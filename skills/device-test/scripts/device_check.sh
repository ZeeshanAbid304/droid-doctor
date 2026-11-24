#!/usr/bin/env bash
# droid-doctor: live device test over adb.
#
# 1. wakes + unlocks the screen, keeps it on, turns animations off
# 2. installs the app, measures cold start
# 3. screenshots + UI dumps in: default, small, tablet, land, dark, font, offline
# 4. tap explorer: taps every button on every reachable screen, finds the exact
#    button that crashes / freezes (ANR), rotates every screen (state loss)
# 5. scroll jank stats, then a monkey stress test that keeps going after crashes
# 6. collects crashes, ANRs, StrictMode, skipped frames
# All device settings are restored on exit (also on Ctrl+C).
#
# Usage:
#   device_check.sh -p com.example.app [-a app-debug.apk] [-s SERIAL]
#                   [-o qa-report/device] [-e 1500] [-S 42]
#                   [-c default,small,tablet,land,dark,font,offline]
#                   [--max-taps 40] [--depth 2] [--no-monkey] [--no-explore]
#                   [--allow-risky]   (also tap buttons like Delete/Logout/Buy)
set -u

PKG="" APK="" SERIAL="" OUT="qa-report/device" EVENTS=1500 SEED=42 MONKEY=1 EXPLORE=1
MAX_TAPS=40 DEPTH=2 RISKY=""
CONFIGS="default,small,tablet,land,dark,font,offline"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    -p) PKG="$2"; shift 2;;
    -a) APK="$2"; shift 2;;
    -s) SERIAL="$2"; shift 2;;
    -o) OUT="$2"; shift 2;;
    -e) EVENTS="$2"; shift 2;;
    -c) CONFIGS="$2"; shift 2;;
    -S) SEED="$2"; shift 2;;
    --max-taps) MAX_TAPS="$2"; shift 2;;
    --depth) DEPTH="$2"; shift 2;;
    --no-monkey) MONKEY=0; shift;;
    --no-explore) EXPLORE=0; shift;;
    --allow-risky) RISKY="--allow-risky"; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "Unknown option: $1"; exit 2;;
  esac
done

[ -z "$PKG" ] && { echo "ERROR: -p <package name> is required"; exit 2; }
command -v adb >/dev/null || { echo "ERROR: adb not found. Install Android platform-tools and add to PATH."; exit 2; }
PY=python3; command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null || PY=python

if [ -z "$SERIAL" ]; then
  COUNT=$(adb devices | awk 'NR>1 && $2=="device"' | wc -l | tr -d ' ')
  [ "$COUNT" = "0" ] && { echo "ERROR: no device/emulator connected (adb devices is empty or unauthorized)."; exit 3; }
  [ "$COUNT" != "1" ] && { echo "ERROR: $COUNT devices connected. Pass one with -s SERIAL:"; adb devices; exit 3; }
  SERIAL=$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')
fi
A() { adb -s "$SERIAL" "$@"; }
SH() { adb -s "$SERIAL" shell "$@" | tr -d '\r'; }

mkdir -p "$OUT/screens"
SUM="$OUT/summary.md"
log() { echo "$*"; echo "$*" >> "$SUM"; }
: > "$SUM"

# ------------------------------------------------------------------ save original settings
SDK=$(SH getprop ro.build.version.sdk)
MODEL="$(SH getprop ro.product.manufacturer) $(SH getprop ro.product.model)"
ORIG_SIZE=$(SH wm size | awk -F': ' '/Override/{print $2}')
ORIG_DENSITY=$(SH wm density | awk -F': ' '/Override/{print $2}')
PHYS_SIZE=$(SH wm size | awk -F': ' '/Physical/{print $2}')
PHYS_DENSITY=$(SH wm density | awk -F': ' '/Physical/{print $2}')
ORIG_FONT=$(SH settings get system font_scale)
ORIG_NIGHT=$(SH cmd uimode night | awk -F': ' '{print $2}')
ORIG_ACCEL=$(SH settings get system accelerometer_rotation)
ORIG_ROT=$(SH settings get system user_rotation)
ORIG_STAYON=$(SH settings get global stay_on_while_plugged_in)
ORIG_TIMEOUT=$(SH settings get system screen_off_timeout)
ORIG_AIRPLANE=$(SH settings get global airplane_mode_on)
ORIG_WA=$(SH settings get global window_animation_scale)
ORIG_TA=$(SH settings get global transition_animation_scale)
ORIG_AD=$(SH settings get global animator_duration_scale)

put() { # put <namespace> <key> <value-or-null>
  if [ -z "$3" ] || [ "$3" = "null" ]; then A shell settings delete "$1" "$2" >/dev/null 2>&1
  else A shell settings put "$1" "$2" "$3"; fi
}
restore() {
  echo "Restoring device settings..."
  if [ -n "$ORIG_SIZE" ]; then A shell wm size "$ORIG_SIZE"; else A shell wm size reset; fi
  if [ -n "$ORIG_DENSITY" ]; then A shell wm density "$ORIG_DENSITY"; else A shell wm density reset; fi
  [ "$ORIG_FONT" = "null" ] && ORIG_FONT=1.0
  A shell settings put system font_scale "${ORIG_FONT:-1.0}"
  case "$ORIG_NIGHT" in yes|no|auto) A shell cmd uimode night "$ORIG_NIGHT" >/dev/null;; esac
  put system accelerometer_rotation "$ORIG_ACCEL"
  put system user_rotation "$ORIG_ROT"
  put global stay_on_while_plugged_in "$ORIG_STAYON"
  put system screen_off_timeout "$ORIG_TIMEOUT"
  put global window_animation_scale "$ORIG_WA"
  put global transition_animation_scale "$ORIG_TA"
  put global animator_duration_scale "$ORIG_AD"
  if [ "$ORIG_AIRPLANE" != "1" ] && [ "$SDK" -ge 30 ]; then A shell cmd connectivity airplane-mode disable >/dev/null 2>&1; fi
}
trap restore EXIT INT TERM

# ------------------------------------------------------------------ screen awake + unlocked
A shell svc power stayon true
A shell settings put system screen_off_timeout 1800000
A shell settings put global window_animation_scale 0
A shell settings put global transition_animation_scale 0
A shell settings put global animator_duration_scale 0
wake() {
  A shell input keyevent KEYCODE_WAKEUP
  A shell wm dismiss-keyguard >/dev/null 2>&1
  sleep 1
}
focus() { SH dumpsys window | grep -E "mCurrentFocus|mFocusedWindow" | head -1; }
in_front() { focus | grep -q "$PKG"; }
locked() { SH dumpsys window | grep -qE "(mShowingLockscreen|isStatusBarKeyguard|mDreamingLockscreen|KeyguardShowing|mKeyguardShowing)=true"; }

log "# Device test: $PKG"
log ""
log "- Device: $MODEL (serial $SERIAL), Android SDK $SDK"
log "- Screen: $PHYS_SIZE @ ${PHYS_DENSITY}dpi"
wake
if locked; then
  log "- **STOPPED: the phone is locked** (PIN/pattern). Unlock it, keep it unlocked, and run again."
  exit 5
fi

# ------------------------------------------------------------------ install
if [ -n "$APK" ]; then
  log "- Installing $APK"
  if ! A install -r -g "$APK" > "$OUT/install.txt" 2>&1; then
    log "- **INSTALL FAILED**: $(tail -1 "$OUT/install.txt")"
    log "  (Infinix/Tecno/Xiaomi: enable 'Install via USB' in Developer options)"
    exit 4
  fi
fi
if ! SH pm list packages "$PKG" | grep -qx "package:$PKG"; then
  log "- **ERROR**: package $PKG is not installed. Build and pass -a app-debug.apk"
  exit 4
fi
COMP=$(SH cmd package resolve-activity --brief -c android.intent.category.LAUNCHER "$PKG" | tail -1)
case "$COMP" in */*) ;; *) log "- **ERROR**: no launcher activity found for $PKG"; exit 4;; esac
log "- Launcher activity: $COMP"
A logcat -b all -c 2>/dev/null
A logcat -G 16M >/dev/null 2>&1   # bigger buffer so early ANRs are not lost

# ------------------------------------------------------------------ helpers
bar_heights() {
  local d sb nb
  d=$(SH dumpsys window)
  sb=$(echo "$d" | grep -oE "(statusBars|ITYPE_STATUS_BAR) frame=\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]" | head -1 | grep -oE "[0-9]+\]$" | tr -d ']')
  nb=$(echo "$d" | grep -oE "(navigationBars|ITYPE_NAVIGATION_BAR) frame=\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]" | head -1 | sed -E 's/.*frame=\[[0-9]+,([0-9]+)\]\[[0-9]+,([0-9]+)\]/\1/')
  echo "${sb:-0} ${nb:-0}"
}
alive() { [ -n "$(SH pidof "$PKG")" ]; }
dump_ui() { # dump_ui <outfile.xml>
  local i
  for i in 1 2 3; do
    A shell uiautomator dump /data/local/tmp/qa_ui.xml >/dev/null 2>&1
    A exec-out cat /data/local/tmp/qa_ui.xml > "$1" 2>/dev/null
    grep -q "<hierarchy" "$1" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}
launch() {
  A shell am force-stop "$PKG"
  wake
  A shell am start -n "$COMP" >/dev/null 2>&1
  sleep 4
  if ! in_front; then wake; A shell am start -n "$COMP" >/dev/null 2>&1; sleep 3; fi
}

# ------------------------------------------------------------------ startup time
log ""
log "## Startup time (cold start)"
for i in 1 2 3; do
  A shell am force-stop "$PKG"; wake
  T=$(SH am start -W -n "$COMP" | awk -F': ' '/TotalTime/{print $2}' | tr -dc '0-9')
  if [ -z "$T" ]; then
    sleep 2
    T=$(SH logcat -d | grep -E "Displayed $PKG" | tail -1 | grep -oE "\+[0-9s]+ms" | tr -d '+')
  fi
  log "- Run $i: ${T:-?} ms"
  sleep 2
done

# ------------------------------------------------------------------ configs
apply_config() {
  case "$1" in
    default) ;;
    small)   A shell wm size 720x1280; A shell wm density 360 ;;          # ~320x569 dp
    tablet)  A shell wm size 1600x2560; A shell wm density 320 ;;         # 800x1280 dp
    land)    A shell settings put system accelerometer_rotation 0; A shell settings put system user_rotation 1 ;;
    dark)    A shell cmd uimode night yes >/dev/null ;;
    font)    if [ "$SDK" -ge 34 ]; then A shell settings put system font_scale 2.0; else A shell settings put system font_scale 1.3; fi ;;
    offline) if [ "$SDK" -ge 30 ]; then A shell cmd connectivity airplane-mode enable >/dev/null 2>&1; else return 1; fi ;;
    *) echo "unknown config $1"; return 1;;
  esac
  sleep 2
}
reset_config() {
  case "$1" in
    small|tablet) if [ -n "$ORIG_SIZE" ]; then A shell wm size "$ORIG_SIZE"; else A shell wm size reset; fi
                  if [ -n "$ORIG_DENSITY" ]; then A shell wm density "$ORIG_DENSITY"; else A shell wm density reset; fi ;;
    land)    A shell settings put system user_rotation 0 ;;
    dark)    A shell cmd uimode night "${ORIG_NIGHT:-no}" >/dev/null 2>&1 || A shell cmd uimode night no >/dev/null ;;
    font)    A shell settings put system font_scale "${ORIG_FONT:-1.0}" ;;
    offline) [ "$ORIG_AIRPLANE" != "1" ] && A shell cmd connectivity airplane-mode disable >/dev/null 2>&1 ;;
  esac
  sleep 1
}

log ""
log "## Screens per configuration"
IFS=',' read -ra CFG <<< "$CONFIGS"
for c in "${CFG[@]}"; do
  apply_config "$c" || { log "- \`$c\`: skipped (not supported on this Android version)"; continue; }
  N0=$(A logcat -b crash -d 2>/dev/null | grep -c "FATAL EXCEPTION")
  launch
  SIZE=$(SH wm size | awk -F': ' 'END{print $2}')
  DENS=$(SH wm density | awk -F': ' 'END{print $2}')
  read -r SB NB <<< "$(bar_heights)"
  A exec-out screencap -p > "$OUT/screens/$c.png"
  if dump_ui "$OUT/screens/$c.xml"; then DUMP="dump ok"; else DUMP="dump FAILED"; rm -f "$OUT/screens/$c.xml"; fi
  echo "size=$SIZE density=$DENS status_bar_bottom=$SB nav_bar_top=$NB config=$c" > "$OUT/screens/$c.meta"
  N1=$(A logcat -b crash -d 2>/dev/null | grep -c "FATAL EXCEPTION")
  if [ "${N1:-0}" -gt "${N0:-0}" ]; then
    A logcat -b crash -d 2>/dev/null | awk -v n="$N0" '/FATAL EXCEPTION/{k++} k>n' | head -60 > "$OUT/screens/$c-crash.txt"
  fi
  if ! alive; then STATE="**CRASHED / CLOSED** (see screens/$c-crash.txt)"
  elif locked || ! in_front; then STATE="**NOT IN FRONT** ($(focus | sed 's/^ *//')) - screenshot may show lock screen"
  else STATE="running"; fi
  log "- \`$c\`: $SIZE @ ${DENS}dpi, app $STATE, $DUMP -> screens/$c.png"
  reset_config "$c"
done

# ------------------------------------------------------------------ tap explorer + rotation per screen
if [ "$EXPLORE" = "1" ]; then
  log ""
  log "## Tap explorer (every button, every screen, rotation)"
  A shell settings put system accelerometer_rotation 0 >/dev/null 2>&1
  A shell settings put system user_rotation 0 >/dev/null 2>&1
  "$PY" "$SCRIPT_DIR/tap_explorer.py" -p "$PKG" -c "$COMP" -s "$SERIAL" -o "$OUT/explore" \
       --max-taps "$MAX_TAPS" --depth "$DEPTH" $RISKY > "$OUT/explore.log" 2>&1
  if [ -f "$OUT/explore/summary.md" ]; then
    cat "$OUT/explore/summary.md" >> "$SUM"; cat "$OUT/explore/summary.md"
  else
    log "- explorer failed, see explore.log"
  fi
fi

# ------------------------------------------------------------------ jank while scrolling
log ""
log "## Scrolling performance"
launch
A shell dumpsys gfxinfo "$PKG" reset >/dev/null
read -r W H <<< "$(SH wm size | awk -F': ' 'END{print $2}' | tr 'x' ' ')"
if [ -n "${W:-}" ] && [ -n "${H:-}" ]; then
  for i in 1 2 3 4 5; do
    A shell input swipe $((W/2)) $((H*3/4)) $((W/2)) $((H/4)) 250 >/dev/null 2>&1
    A shell input swipe $((W/2)) $((H/4)) $((W/2)) $((H*3/4)) 250 >/dev/null 2>&1
  done
fi
SH dumpsys gfxinfo "$PKG" > "$OUT/gfxinfo.txt"
JANK=$(grep -m1 "Janky frames:" "$OUT/gfxinfo.txt" | sed 's/^ *//')
P90=$(grep -m1 "90th percentile:" "$OUT/gfxinfo.txt" | sed 's/^ *//')
log "- ${JANK:-Janky frames: n/a}; ${P90:-}"

# ------------------------------------------------------------------ monkey (continues after crashes)
if [ "$MONKEY" = "1" ]; then
  log ""
  log "## Monkey stress test ($EVENTS events, seed $SEED)"
  launch
  A shell monkey -p "$PKG" -s "$SEED" --throttle 150 --pct-syskeys 0 --pct-appswitch 5 \
      --ignore-crashes --ignore-timeouts --ignore-security-exceptions \
      -v "$EVENTS" > "$OUT/monkey.txt" 2>&1
  MC=$(grep -c "// CRASH:" "$OUT/monkey.txt"); MA=$(grep -c "// NOT RESPONDING:" "$OUT/monkey.txt")
  log "- Crashes during monkey: ${MC:-0}, ANRs during monkey: ${MA:-0}"
  grep -A3 "// CRASH:" "$OUT/monkey.txt" | grep -E "Long Msg|Short Msg" | sort | uniq -c | head -10 | sed 's/^/  - /' >> "$SUM"
  grep -q "Monkey finished" "$OUT/monkey.txt" && log "- Monkey finished all events"
fi

# ------------------------------------------------------------------ crashes / ANRs
log ""
log "## Crashes and ANRs (whole run)"
A logcat -b crash -d > "$OUT/logcat-crash.txt" 2>/dev/null
A logcat -b main,system,events -d -v threadtime > "$OUT/logcat.txt" 2>/dev/null
SH dumpsys activity exit-info "$PKG" > "$OUT/exit-info.txt" 2>/dev/null
cnt() { local n; n=$(grep -c "$1" "$2" 2>/dev/null); echo "${n:-0}"; }
CRASHES=$(cnt "FATAL EXCEPTION" "$OUT/logcat-crash.txt")
ANRS=$(cnt "ANR in $PKG" "$OUT/logcat.txt")
EXIT_ANR=$(cnt "(ANR)" "$OUT/exit-info.txt")
NATIVE=$(cnt "Fatal signal" "$OUT/logcat.txt")
log "- Java/Kotlin crashes (FATAL EXCEPTION, whole run): $CRASHES"
log "- ANRs in logcat: $ANRS (exit-info ANR records: $EXIT_ANR)"
log "- Native crashes (Fatal signal): $NATIVE"
if [ "$CRASHES" != "0" ]; then
  # unique exception types with first app frame
  awk -v pkg="$PKG" '
    /FATAL EXCEPTION/ {inb=1; exc=""; frame=""; next}
    inb && exc=="" && /Exception|Error/ {sub(/^.*AndroidRuntime: /,""); exc=$0; next}
    inb && frame=="" && index($0, "at " pkg) {sub(/^.*AndroidRuntime: +/,""); frame=$0; print exc " | " frame; inb=0}
  ' "$OUT/logcat-crash.txt" | sort | uniq -c | sort -rn > "$OUT/crash-types.txt"
  log "- Unique crashes (count | exception | first app frame):"
  sed 's/^/  - /' "$OUT/crash-types.txt" | head -15 | tee -a "$SUM"
  awk '/FATAL EXCEPTION/{n++} n>0 && n<=5' "$OUT/logcat-crash.txt" | head -150 > "$OUT/crash-stacks.txt"
fi
if [ "$ANRS" != "0" ]; then
  grep -A12 "ANR in $PKG" "$OUT/logcat.txt" | head -80 > "$OUT/anr.txt"
  log "- ANR details saved to anr.txt"
fi
STRICT=$(cnt "StrictMode" "$OUT/logcat.txt")
[ "$STRICT" != "0" ] && log "- StrictMode violations in log: $STRICT (disk/network on main thread)"
SKIPPED=$(grep -oE "Skipped [0-9]+ frames" "$OUT/logcat.txt" | awk '{if($2>m)m=$2} END{print m+0}')
[ "${SKIPPED:-0}" -gt 30 ] && log "- Choreographer: up to $SKIPPED frames skipped at once (main thread busy)"
LEAK=$(cnt "LeakCanary" "$OUT/logcat.txt")
[ "$LEAK" != "0" ] && log "- LeakCanary messages in log: $LEAK (check for leaks)"

log ""
log "Done. Output folder: $OUT"
