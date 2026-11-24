#!/usr/bin/env python3
"""
droid-doctor static scanner.

Scans an Android project (XML views and Jetpack Compose) for UI, theme,
system-bar, layout, ANR and crash-risk problems that often show up in new apps.

Usage:
    python3 scan_ui.py <project_dir> [--out qa-report/static.json] [--md qa-report/static.md]

Only uses the Python standard library.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from xml.etree import ElementTree as ET

PLAY_REQUIRED_TARGET_SDK = 36  # Google Play: new apps + updates since 31 Aug 2026

SKIP_DIRS = {"build", ".gradle", ".idea", ".git", "node_modules", "intermediates",
             "generated", ".cxx", "test", "androidTest", "testDebug", "testRelease"}
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


# --------------------------------------------------------------------------- helpers
class Findings:
    def __init__(self, root):
        self.root = root
        self._items = {}  # (rule, file) -> finding (aggregated)

    def add(self, rule, severity, category, path, line, message, fix):
        rel = os.path.relpath(path, self.root) if path else "-"
        key = (rule, rel, message if rule.startswith("PROJECT_") else "")
        if key in self._items:
            self._items[key]["count"] += 1
            if line and line not in self._items[key]["lines"] and len(self._items[key]["lines"]) < 10:
                self._items[key]["lines"].append(line)
            return
        self._items[key] = {
            "rule": rule, "severity": severity, "category": category, "file": rel,
            "lines": [line] if line else [], "count": 1, "message": message, "fix": fix,
        }

    def all(self):
        return sorted(self._items.values(),
                      key=lambda f: (SEV_ORDER[f["severity"]], f["category"], f["file"]))


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            yield os.path.join(dirpath, name)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def line_of(text, index):
    return text.count("\n", 0, index) + 1


def norm_hex(value):
    """Return color as #AARRGGBB uppercase, or None."""
    v = value.strip().lstrip("#")
    if v.lower().startswith("0x"):
        v = v[2:]
    if not re.fullmatch(r"[0-9a-fA-F]{3,8}", v):
        return None
    if len(v) == 3:
        v = "FF" + "".join(c * 2 for c in v)
    elif len(v) == 4:
        v = "".join(c * 2 for c in v)
    elif len(v) == 6:
        v = "FF" + v
    elif len(v) != 8:
        return None
    return "#" + v.upper()


def is_theme_file(path):
    p = path.replace("\\", "/").lower()
    base = os.path.basename(p)
    return ("/theme/" in p or "/ui/theme" in p or "/designsystem/" in p
            or base in {"color.kt", "colors.kt", "theme.kt", "type.kt", "typography.kt",
                        "shape.kt", "dimens.kt", "colors.xml", "themes.xml", "styles.xml"})


def dp_value(v):
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*dp\s*", v or "")
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- collection
class Project:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.layouts, self.values, self.code, self.manifests, self.gradle = [], [], [], [], []
        self.font_files = []
        self.res_dirs = set()
        for path in walk(self.root):
            p = path.replace("\\", "/")
            base = os.path.basename(p)
            parent = os.path.basename(os.path.dirname(p))
            if base.endswith((".gradle", ".gradle.kts")) or base == "libs.versions.toml":
                self.gradle.append(path)
            elif base == "AndroidManifest.xml":
                self.manifests.append(path)
            elif "/res/" in p:
                self.res_dirs.add(parent)
                if parent.startswith("layout") and base.endswith(".xml"):
                    self.layouts.append(path)
                elif parent.startswith("values") and base.endswith(".xml"):
                    self.values.append(path)
                elif parent.startswith("font"):
                    self.font_files.append(path)
            elif base.endswith((".kt", ".java")):
                self.code.append(path)
        self.code_text = {p: read(p) for p in self.code}
        self.all_code = "\n".join(self.code_text.values())
        self.target_sdk, self.min_sdk = self._sdk_levels()
        self.palette = self._palette()

    def _sdk_levels(self):
        target = minimum = None
        self.sdk_file = None
        for g in self.gradle:
            t = read(g)
            m = re.search(r"targetSdk(?:Version)?\s*(?:=|\s)\s*(\d+)", t)
            if m:
                target = max(target or 0, int(m.group(1)))
                self.sdk_file = g
            m = re.search(r"minSdk(?:Version)?\s*(?:=|\s)\s*(\d+)", t)
            if m:
                minimum = int(m.group(1)) if minimum is None else min(minimum, int(m.group(1)))
            # version catalog style: targetSdk = "36"
            m = re.search(r'targetSdk\s*=\s*"(\d+)"', t)
            if m:
                target = max(target or 0, int(m.group(1)))
        return target, minimum

    def _palette(self):
        palette = {}  # #AARRGGBB -> name
        for v in self.values:
            t = read(v)
            for m in re.finditer(r'<color\s+name="([^"]+)"\s*>\s*(#[0-9a-fA-F]{3,8})\s*<', t):
                h = norm_hex(m.group(2))
                if h:
                    palette.setdefault(h, "@color/" + m.group(1))
        for p, t in self.code_text.items():
            if not is_theme_file(p):
                continue
            for m in re.finditer(r"val\s+(\w+)\s*=\s*Color\(\s*(0x[0-9a-fA-F]{6,8})\s*\)", t):
                h = norm_hex(m.group(2))
                if h:
                    palette.setdefault(h, m.group(1))
        return palette


# --------------------------------------------------------------------------- checks
def check_gradle(prj, f):
    gfile = prj.sdk_file or (prj.gradle[0] if prj.gradle else None)
    if prj.target_sdk is None:
        f.add("PROJECT_NO_TARGET", "low", "Build", gfile, None,
              "Could not read targetSdk from Gradle files.",
              "Check the app module build.gradle(.kts) and set targetSdk explicitly.")
    elif prj.target_sdk < PLAY_REQUIRED_TARGET_SDK:
        f.add("PROJECT_TARGET_SDK", "high", "Build", gfile, None,
              f"targetSdk is {prj.target_sdk}. Google Play only accepts new apps and updates "
              f"that target {PLAY_REQUIRED_TARGET_SDK} or higher.",
              f"Raise targetSdk to {PLAY_REQUIRED_TARGET_SDK}, then re-run this scan: edge-to-edge and "
              "large-screen orientation rules change at 35/36.")


def check_layouts(prj, f):
    font_families = defaultdict(list)
    for path in prj.layouts:
        text = read(path)
        lines = text.splitlines()
        for i, ln in enumerate(lines, 1):
            for m in re.finditer(r'(android|app):(\w+)="(#[0-9a-fA-F]{3,8})"', ln):
                attr, hexv = m.group(2), norm_hex(m.group(3))
                if hexv in prj.palette:
                    f.add("XML_HARDCODED_COLOR", "low", "Theme colors", path, i,
                          f"Hardcoded color {m.group(3)} in {attr}; it matches {prj.palette[hexv]}.",
                          f"Use {prj.palette[hexv]} or a theme attribute like ?attr/colorPrimary so dark mode works.")
                else:
                    f.add("XML_OFF_THEME_COLOR", "medium", "Theme colors", path, i,
                          f"Color {m.group(3)} in {attr} is not in the app palette (colors.xml / Color.kt).",
                          "Replace with a theme color (?attr/colorSurface, ?attr/colorOnSurface, ...) "
                          "or add it to the palette with a night variant.")
            if re.search(r'"@android:color/(white|black|darker_gray|holo_\w+)"', ln):
                f.add("XML_SYSTEM_COLOR", "medium", "Theme colors", path, i,
                      "Uses @android:color/* directly; it ignores your theme and breaks in dark mode.",
                      "Use ?attr/colorSurface / ?attr/colorOnSurface or an @color with a values-night version.")
            m = re.search(r'android:textSize="(\d+(?:\.\d+)?)(dp|px|dip)"', ln)
            if m:
                f.add("XML_TEXTSIZE_NOT_SP", "medium", "Fonts", path, i,
                      f"textSize uses {m.group(2)}; text will not grow with the user's font size setting.",
                      "Use sp, ideally via a TextAppearance style from the theme.")
            m = re.search(r'(?:android|app):fontFamily="([^"]+)"', ln)
            if m:
                font_families[m.group(1)].append((path, i))
                if not m.group(1).startswith(("@font/", "?")):
                    f.add("XML_FONT_HARDCODED", "low", "Fonts", path, i,
                          f'fontFamily="{m.group(1)}" is a system font name, not your app font.',
                          "Use @font/... from res/font or set fonts once in the theme / TextAppearance.")
            if 'android:typeface="' in ln:
                f.add("XML_TYPEFACE", "low", "Fonts", path, i,
                      "android:typeface overrides the theme font.",
                      "Remove it and use a TextAppearance style.")
            m = re.search(r'android:text="([^"@?][^"]*)"', ln)
            if m and not ln.strip().startswith("tools:"):
                f.add("XML_HARDCODED_TEXT", "low", "Text", path, i,
                      f'Hardcoded text "{m.group(1)[:40]}" (cannot be translated, easy to forget).',
                      "Move it to res/values/strings.xml.")

        # element-level checks
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        # map the n-th <Tag ...> element to its source line
        tag_lines = defaultdict(list)
        for m in re.finditer(r"<([A-Za-z_][\w.]*)", text):
            tag_lines[m.group(1)].append(line_of(text, m.start()))
        tag_seen = defaultdict(int)
        for el in tree.iter():
            full_tag = el.tag
            tag = full_tag.split(".")[-1]
            idx = tag_seen[full_tag]
            tag_seen[full_tag] += 1
            ln = tag_lines[full_tag][idx] if idx < len(tag_lines[full_tag]) else None
            w = el.get(ANDROID_NS + "layout_width")
            h = el.get(ANDROID_NS + "layout_height")
            wv, hv = dp_value(w), dp_value(h)
            if wv and wv >= 320:
                f.add("XML_FIXED_WIDTH", "medium", "Layout / screen sizes", path, ln,
                      f"<{tag}> has fixed width {w}; it will overflow or be cut on small phones (320-360dp wide).",
                      "Use match_parent / 0dp with constraints, or a max width.")
            if tag in {"TextView", "Button", "MaterialButton", "EditText", "TextInputEditText",
                       "AppCompatTextView", "MaterialTextView", "Chip"} and hv and hv < 200:
                f.add("XML_TEXT_FIXED_HEIGHT", "medium", "Layout / screen sizes", path, ln,
                      f"<{tag}> has fixed height {h}; text gets cut when font size is large.",
                      "Use wrap_content with android:minHeight instead.")
            if tag in {"ImageView", "ImageButton", "AppCompatImageView", "ShapeableImageView",
                       "FloatingActionButton"}:
                if el.get(ANDROID_NS + "contentDescription") is None and \
                        el.get(ANDROID_NS + "importantForAccessibility") != "no":
                    f.add("XML_NO_CONTENT_DESC", "low", "Accessibility", path, ln,
                          f"<{tag}> has no contentDescription.",
                          'Add android:contentDescription, or importantForAccessibility="no" if decorative.')
            if tag in {"ImageButton", "Button", "MaterialButton", "CheckBox", "RadioButton", "Switch"}:
                for dim in (wv, hv):
                    if dim is not None and dim < 48:
                        f.add("XML_SMALL_TOUCH", "low", "Accessibility", path, ln,
                              f"<{tag}> touch target is smaller than 48dp.",
                              "Make it at least 48x48dp (use padding or minWidth/minHeight).")
                        break
            if tag == "ScrollView" and el.get(ANDROID_NS + "fillViewport") is None and len(list(el)) == 1:
                child = list(el)[0]
                if child.get(ANDROID_NS + "layout_height") == "match_parent":
                    f.add("XML_SCROLL_CHILD_MATCH", "low", "Layout / screen sizes", path, ln,
                          "ScrollView child uses match_parent height (content may not scroll).",
                          'Use wrap_content on the child and android:fillViewport="true".')

    app_fonts = [k for k in font_families if not k.startswith("?")]
    if len(app_fonts) > 2:
        f.add("PROJECT_MANY_FONTS", "medium", "Fonts", None, None,
              f"{len(app_fonts)} different font families are used in layouts: {', '.join(app_fonts[:6])}.",
              "Pick 1-2 fonts and set them once in the theme (textAppearance* / Typography).")


def check_values(prj, f):
    has_night = any(d.startswith("values-night") for d in prj.res_dirs)
    uses_daynight = False
    for path in prj.values:
        text = read(path)
        if "<style" not in text:
            continue
        if "DayNight" in text:
            uses_daynight = True
        for m in re.finditer(r'<style\s+name="([^"]+)"([^>]*)>(.*?)</style>', text, re.S):
            name, head, body = m.group(1), m.group(2), m.group(3)
            if not re.search(r'parent="[^"]*(Theme|DayNight)', head + name):
                continue
            ln = line_of(text, m.start())
            sb = re.search(r'name="android:statusBarColor"', body)
            nb = re.search(r'name="android:navigationBarColor"', body)
            if (sb or nb) and (prj.target_sdk or 0) >= 35:
                f.add("THEME_BAR_COLOR_IGNORED", "medium", "Status / navigation bar", path, ln,
                      f"Theme {name} sets statusBarColor/navigationBarColor, but with targetSdk "
                      f"{prj.target_sdk} Android 15+ draws edge-to-edge and ignores these.",
                      "Draw your own background behind the bars and pad content with WindowInsets; "
                      "use windowLightStatusBar / WindowInsetsControllerCompat for icon color.")
            if sb and not re.search(r'name="android:windowLightStatusBar"', body):
                f.add("THEME_STATUS_ICON_CONTRAST", "medium", "Status / navigation bar", path, ln,
                      f"Theme {name} sets statusBarColor but not windowLightStatusBar; "
                      "status bar icons may be white on a light bar (or the reverse).",
                      'Add <item name="android:windowLightStatusBar">true</item> for light bars '
                      "(false in values-night).")
            if nb and not re.search(r'name="android:windowLightNavigationBar"', body):
                f.add("THEME_NAV_ICON_CONTRAST", "low", "Status / navigation bar", path, ln,
                      f"Theme {name} sets navigationBarColor but not windowLightNavigationBar.",
                      "Set windowLightNavigationBar to match the bar background.")
            if re.search(r'name="android:windowTranslucentStatus">true', body):
                f.add("THEME_TRANSLUCENT_STATUS", "low", "Status / navigation bar", path, ln,
                      "windowTranslucentStatus is deprecated and gives a grey scrim on some devices.",
                      "Use enableEdgeToEdge() and WindowInsets instead.")
    compose_dark = "isSystemInDarkTheme" in prj.all_code
    if (uses_daynight or compose_dark) and not has_night and prj.layouts:
        f.add("PROJECT_NO_NIGHT_RES", "medium", "Theme colors", None, None,
              "App supports dark mode, but there is no res/values-night folder; XML screens keep light colors.",
              "Add values-night/colors.xml and themes.xml with dark versions.")


def check_compose_and_code(prj, f):
    insets_seen = re.search(
        r"WindowInsets|windowInsetsPadding|systemBarsPadding|statusBarsPadding|navigationBarsPadding|"
        r"safeDrawingPadding|safeContentPadding|fitsSystemWindows|setOnApplyWindowInsetsListener|"
        r"imePadding|contentWindowInsets", prj.all_code)
    insets_xml = any('fitsSystemWindows="true"' in read(p) for p in prj.layouts)
    scaffold_ok = False
    edge_called = "enableEdgeToEdge" in prj.all_code or "setDecorFitsSystemWindows(window, false)" in prj.all_code

    for path, text in prj.code_text.items():
        theme_file = is_theme_file(path)
        is_kt = path.endswith(".kt")

        # ---- colors
        if not theme_file:
            for m in re.finditer(r"Color\(\s*(0x[0-9a-fA-F]{6,8})\s*\)", text):
                h = norm_hex(m.group(1))
                ln = line_of(text, m.start())
                if h in prj.palette:
                    f.add("COMPOSE_HARDCODED_COLOR", "low", "Theme colors", path, ln,
                          f"Hardcoded Color({m.group(1)}) equals theme color {prj.palette[h]}.",
                          "Use MaterialTheme.colorScheme.* so it changes with dark mode.")
                else:
                    f.add("COMPOSE_OFF_THEME_COLOR", "medium", "Theme colors", path, ln,
                          f"Color({m.group(1)}) is not in the app palette.",
                          "Use MaterialTheme.colorScheme.* or add it to Color.kt with a dark variant.")
            for m in re.finditer(r"\bColor\.(White|Black|Red|Blue|Green|Yellow|Gray|LightGray|DarkGray|Cyan|Magenta)\b", text):
                f.add("COMPOSE_NAMED_COLOR", "medium" if m.group(1) in ("White", "Black") else "low",
                      "Theme colors", path, line_of(text, m.start()),
                      f"Color.{m.group(1)} is used directly; it does not follow the theme or dark mode.",
                      "Use MaterialTheme.colorScheme.surface / onSurface / primary etc.")
            for m in re.finditer(r"fontSize\s*=\s*\d+(?:\.\d+)?\.sp", text):
                f.add("COMPOSE_FONT_SIZE", "low", "Fonts", path, line_of(text, m.start()),
                      "Hardcoded fontSize in a screen; sizes drift between screens.",
                      "Use style = MaterialTheme.typography.bodyLarge (etc.).")
            for m in re.finditer(r"FontFamily\.(Serif|Monospace|Cursive|SansSerif)|fontFamily\s*=\s*FontFamily\(", text):
                f.add("COMPOSE_FONT_FAMILY", "low", "Fonts", path, line_of(text, m.start()),
                      "Font family set directly in a screen instead of in Typography.",
                      "Define fonts once in Type.kt and use MaterialTheme.typography.")
            for m in re.finditer(r"\.(?:width|requiredWidth|size|requiredSize)\(\s*(\d+)\.dp\s*\)", text):
                if int(m.group(1)) >= 320:
                    f.add("COMPOSE_FIXED_WIDTH", "medium", "Layout / screen sizes", path, line_of(text, m.start()),
                          f"Fixed width {m.group(1)}.dp overflows small phones.",
                          "Use fillMaxWidth() with widthIn(max = ...) instead.")
            for m in re.finditer(r"\bText\(\s*\"", text):
                f.add("COMPOSE_HARDCODED_TEXT", "low", "Text", path, line_of(text, m.start()),
                      "Text(\"...\") with a hardcoded string.",
                      "Use stringResource(R.string.xxx).")
            for m in re.finditer(r"\.height\(\s*(\d+)\.dp\s*\)[^\n]*\n?[^\n]*\bText\(", text):
                f.add("COMPOSE_TEXT_FIXED_HEIGHT", "low", "Layout / screen sizes", path, line_of(text, m.start()),
                      "A container with fixed height holds Text; it can be cut at large font scale.",
                      "Use heightIn(min = ...) instead of height(...).")

        # ---- dynamic color overriding brand colors
        m = re.search(r"dynamicColor\s*:\s*Boolean\s*=\s*true", text)
        if m:
            f.add("COMPOSE_DYNAMIC_COLOR", "medium", "Theme colors", path, line_of(text, m.start()),
                  "dynamicColor defaults to true: on Android 12+ the app uses wallpaper colors, not your brand colors.",
                  "Set dynamicColor = false unless you want Material You colors.")
        m = re.search(r"DynamicColors\.applyToActivitiesIfAvailable", text)
        if m:
            f.add("XML_DYNAMIC_COLOR", "medium", "Theme colors", path, line_of(text, m.start()),
                  "DynamicColors is applied: on Android 12+ brand colors are replaced by wallpaper colors.",
                  "Remove it if the app should keep its own colors.")
        if theme_file and "lightColorScheme" in text and "darkColorScheme" not in text:
            f.add("COMPOSE_NO_DARK_SCHEME", "medium", "Theme colors", path, None,
                  "Theme defines lightColorScheme but no darkColorScheme.",
                  "Add a darkColorScheme and pick it with isSystemInDarkTheme().")

        # ---- Scaffold padding not used -> content under top bar / status bar
        for m in re.finditer(r"\bScaffold\s*(\(|\{)", text):
            window = text[m.end() - 1: m.end() + 2500]
            lm = re.match(r"\{\s*(\w+)\s*->", window) or \
                re.search(r"\)\s*\{\s*(\w+)\s*->|content\s*=\s*\{\s*(\w+)\s*->", window)
            if not lm:
                continue
            var = lm.group(1) or (lm.group(2) if lm.lastindex and lm.lastindex >= 2 else None)
            after = window[lm.end(): lm.end() + 3000]
            if var != "_" and re.search(r"\b" + re.escape(var) + r"\b", after):
                scaffold_ok = True
            if var == "_" or not re.search(r"\b" + re.escape(var) + r"\b", after):
                f.add("COMPOSE_SCAFFOLD_PADDING", "high", "Status / navigation bar", path, line_of(text, m.start()),
                      "Scaffold content ignores its padding; content goes under the top bar, status bar or nav bar.",
                      "Apply it: Modifier.padding(innerPadding) on the content root.")
        for m in re.finditer(r'UnusedMaterial3ScaffoldPaddingParameter|UnusedMaterialScaffoldPaddingParameter', text):
            f.add("COMPOSE_SCAFFOLD_SUPPRESS", "medium", "Status / navigation bar", path, line_of(text, m.start()),
                  "Lint warning about unused Scaffold padding is suppressed.",
                  "Remove the suppression and apply the padding.")

        # ---- deprecated status / nav bar APIs
        for m in re.finditer(r"window\.(statusBarColor|navigationBarColor)\s*=|set(StatusBar|NavigationBar)Color\(|"
                             r"systemUiVisibility|SYSTEM_UI_FLAG_|rememberSystemUiController", text):
            f.add("CODE_DEPRECATED_BAR_API", "medium", "Status / navigation bar", path, line_of(text, m.start()),
                  f"'{m.group(0).strip('=( ')}' is deprecated; on Android 15+ it does nothing, so bar colors differ by device.",
                  "Use enableEdgeToEdge(SystemBarStyle...) and WindowCompat.getInsetsController(...)"
                  ".isAppearanceLightStatusBars.")

        # ---- ANR risks
        for rule, pat, sev, msg, fix in [
            ("ANR_THREAD_SLEEP", r"Thread\.sleep\(", "medium", "Thread.sleep() blocks the thread it runs on (ANR if main).",
             "Use delay() inside a coroutine."),
            ("ANR_RUN_BLOCKING", r"\brunBlocking\s*[\({]", "high", "runBlocking blocks the calling thread; on the main thread it causes ANRs.",
             "Use lifecycleScope / viewModelScope.launch with suspend functions."),
            ("ANR_ROOM_MAIN_THREAD", r"allowMainThreadQueries\(\)", "high", "Room allowMainThreadQueries(): database work on main thread -> freezes / ANR.",
             "Remove it and make DAO functions suspend or return Flow."),
            ("ANR_SYNC_HTTP", r"\.newCall\([^)]*\)\.execute\(\)", "medium", "Synchronous OkHttp call; ANR / NetworkOnMainThread crash if on main.",
             "Use enqueue() or call it inside withContext(Dispatchers.IO)."),
            ("CRASH_GLOBAL_SCOPE", r"\bGlobalScope\.", "low", "GlobalScope coroutine is not tied to lifecycle (leaks, crash after screen closes).",
             "Use viewModelScope or lifecycleScope."),
        ]:
            for m in re.finditer(pat, text):
                f.add(rule, sev, "ANR risk", path,
                      line_of(text, m.start()), msg, fix)
        for i, ln in enumerate(text.splitlines(), 1):
            if "edit()" in ln and ".commit()" in ln:
                f.add("ANR_PREFS_COMMIT", "low", "ANR risk", path, i,
                      "SharedPreferences commit() writes to disk on the calling thread.",
                      "Use apply(), or DataStore.")

        # ---- crash risks
        bang = len(re.findall(r"!!(?!=)", text)) if is_kt else 0
        if bang:
            f.add("CRASH_NOT_NULL_ASSERT", "medium" if bang >= 5 else "low", "Crash risk", path, None,
                  f"{bang} use(s) of !! (crashes with NullPointerException if the value is null).",
                  "Use ?.let { }, ?: default, or requireNotNull with a clear message.")
        for m in re.finditer(r"catch\s*\(\s*\w+\s*:\s*(Exception|Throwable)\s*\)\s*\{\s*\}", text):
            f.add("CRASH_EMPTY_CATCH", "low", "Crash risk", path, line_of(text, m.start()),
                  "Empty catch block hides real errors.",
                  "At least log the exception.")
        for m in re.finditer(r"PendingIntent\.get(Activity|Broadcast|Service|ForegroundService)\s*\(", text):
            stmt = text[m.start(): m.start() + 400]
            stmt = stmt[: stmt.find(")\n") + 1 if ")\n" in stmt else len(stmt)]
            if "FLAG_IMMUTABLE" not in stmt and "FLAG_MUTABLE" not in stmt:
                f.add("CRASH_PENDINGINTENT_FLAG", "high", "Crash risk", path, line_of(text, m.start()),
                      "PendingIntent without FLAG_IMMUTABLE/FLAG_MUTABLE crashes on Android 12+ (targetSdk 31+).",
                      "Add PendingIntent.FLAG_IMMUTABLE (or FLAG_MUTABLE if it must be changed).")
        if (prj.target_sdk or 0) >= 34:
            for m in re.finditer(r"(?<!ContextCompat\.)\bregisterReceiver\s*\(", text):
                stmt = text[m.start(): m.start() + 300].split("\n\n")[0]
                if "RECEIVER_" not in stmt and "fun registerReceiver" not in text[max(0, m.start() - 20): m.start() + 20]:
                    f.add("CRASH_RECEIVER_EXPORT_FLAG", "high", "Crash risk", path, line_of(text, m.start()),
                          "registerReceiver() without RECEIVER_EXPORTED/RECEIVER_NOT_EXPORTED throws on Android 14+.",
                          "Use ContextCompat.registerReceiver(context, r, filter, ContextCompat.RECEIVER_NOT_EXPORTED).")

    # ---- project-wide: exact alarms, notifications, foreground service
    if re.search(r"\.setExact(AndClock|AndAllowWhileIdle)?\(|setAlarmClock\(", prj.all_code) and \
            "canScheduleExactAlarms" not in prj.all_code:
        f.add("PROJECT_EXACT_ALARM", "high", "Crash risk", None, None,
              "Exact alarms are scheduled without checking canScheduleExactAlarms(); "
              "SecurityException crash on Android 12+ / alarms denied by default on Android 14+.",
              "Check alarmManager.canScheduleExactAlarms() and send the user to "
              "ACTION_REQUEST_SCHEDULE_EXACT_ALARM if false (or use USE_EXACT_ALARM for alarm/reminder apps).")

    if prj.code and not (insets_seen or insets_xml or scaffold_ok):
        if (prj.target_sdk or 0) >= 35 or edge_called:
            f.add("PROJECT_NO_INSETS", "high", "Status / navigation bar", None, None,
                  "App draws edge-to-edge (targetSdk 35+ or enableEdgeToEdge) but never handles WindowInsets; "
                  "toolbars, buttons and lists will sit under the status bar / gesture bar.",
                  "Compose: use Scaffold padding or Modifier.safeDrawingPadding(). Views: "
                  "ViewCompat.setOnApplyWindowInsetsListener on the root view.")
    if prj.code and (prj.target_sdk or 0) >= 35 and not edge_called and re.search(r":\s*(Component|AppCompat|Fragment)Activity\(", prj.all_code):
        f.add("PROJECT_NO_ENABLE_EDGE", "low", "Status / navigation bar", None, None,
              "Activities don't call enableEdgeToEdge(); Android 15+ is edge-to-edge anyway, Android 14 and lower are not, "
              "so the app looks different across versions.",
              "Call enableEdgeToEdge() in each Activity's onCreate before setContent/setContentView.")


def check_fonts(prj, f):
    for fp in prj.font_files:
        name = os.path.splitext(os.path.basename(fp))[0]
        used = ("R.font." + name) in prj.all_code or \
            any(("@font/" + name) in read(p) for p in prj.layouts + prj.values + prj.font_files)
        if not used:
            f.add("FONT_UNUSED", "low", "Fonts", fp, None,
                      f"Font '{name}' is in res/font but never used; the app probably shows the default font instead.",
                      "Reference it in Typography (Compose) or the theme fontFamily (XML), or delete it.")


def check_manifest(prj, f):
    perms = set()
    for mf in prj.manifests:
        text = read(mf)
        perms |= set(re.findall(r'uses-permission[^>]*android:name="([^"]+)"', text))
        for m in re.finditer(r"<(activity|activity-alias|service|receiver)\b([^>]*)>(.*?)</\1>", text, re.S):
            tag, attrs, body = m.groups()
            if "<intent-filter" in body and "android:exported" not in attrs:
                f.add("MANIFEST_EXPORTED", "high", "Crash risk", mf, line_of(text, m.start()),
                      f"<{tag}> has an intent-filter but no android:exported; install fails on Android 12+.",
                      'Add android:exported="true" (launcher / deep link) or "false".')
            if tag == "service" and (prj.target_sdk or 0) >= 34 and "foregroundServiceType" not in attrs \
                    and "startForeground" in prj.all_code:
                f.add("MANIFEST_FGS_TYPE", "high", "Crash risk", mf, line_of(text, m.start()),
                      "Service may run in foreground but has no foregroundServiceType; crashes on Android 14+.",
                      'Add android:foregroundServiceType="..." and the matching FOREGROUND_SERVICE_* permission.')
        for m in re.finditer(r'android:screenOrientation="(portrait|landscape|sensorPortrait|userPortrait)"', text):
            f.add("MANIFEST_ORIENTATION_LOCK", "medium", "Layout / screen sizes", mf, line_of(text, m.start()),
                  f'screenOrientation="{m.group(1)}": with targetSdk 36, Android 16 ignores this on tablets/foldables, '
                  "so the layout must also work in landscape.",
                  "Test landscape / tablet layouts (device-test does this) and use adaptive layouts.")
        if re.search(r'android:resizeableActivity="false"', text):
            f.add("MANIFEST_NOT_RESIZEABLE", "low", "Layout / screen sizes", mf, None,
                  'resizeableActivity="false" is ignored on large screens with targetSdk 36.',
                  "Support multi-window / resizing.")
    uses_notif = re.search(r"NotificationCompat\.Builder|Notification\.Builder|NotificationManagerCompat", prj.all_code)
    if uses_notif and (prj.target_sdk or 0) >= 33 and "android.permission.POST_NOTIFICATIONS" not in perms:
        f.add("PROJECT_POST_NOTIF", "high", "Crash risk", prj.manifests[0] if prj.manifests else None, None,
              "App shows notifications but does not declare POST_NOTIFICATIONS; on Android 13+ they are silently blocked.",
              "Declare the permission and request it at runtime.")
    elif uses_notif and "POST_NOTIFICATIONS" in "".join(perms) and \
            not re.search(r"POST_NOTIFICATIONS", prj.all_code):
        f.add("PROJECT_POST_NOTIF_RUNTIME", "medium", "Crash risk", None, None,
              "POST_NOTIFICATIONS is declared but never requested at runtime.",
              "Request it with ActivityResultContracts.RequestPermission() on Android 13+.")


# --------------------------------------------------------------------------- ads
TEST_PUB = "3940256099942544"


def check_ads(prj, f):
    gradle_text = "\n".join(read(g) for g in prj.gradle)
    xml_text = "\n".join(read(p) for p in prj.layouts)
    manifest_text = "\n".join(read(m) for m in prj.manifests)
    uses_ads = ("play-services-ads" in gradle_text or "com.google.android.gms.ads" in prj.all_code
                or "gms.ads.AdView" in xml_text)
    if not uses_ads:
        return
    mf = prj.manifests[0] if prj.manifests else None
    if "com.google.android.gms.ads.APPLICATION_ID" not in manifest_text:
        f.add("ADS_NO_APP_ID", "high", "Ads", mf, None,
              "AdMob is used but the manifest has no com.google.android.gms.ads.APPLICATION_ID: the app crashes at launch.",
              '<meta-data android:name="com.google.android.gms.ads.APPLICATION_ID" android:value="ca-app-pub-xxx~yyy"/> inside <application>.')
    all_src = prj.all_code + "\n" + xml_text + "\n" + gradle_text + "\n" + manifest_text
    units = set(re.findall(r"ca-app-pub-(\d{16})/\d{10}", all_src))
    real = {u for u in units if u != TEST_PUB}
    switch = re.search(r"BuildConfig\.DEBUG|buildConfigField[^\n]*(AD|ad)|resValue[^\n]*(ad|AD)", all_src)
    if real and not switch:
        f.add("ADS_REAL_IDS_IN_DEBUG", "medium", "Ads", None, None,
              "Real ad unit IDs are hardcoded, so debug builds and testers load live ads. "
              "Clicking your own live ads can get the AdMob account suspended.",
              "Use Google's test IDs in debug: buildConfigField per build type, or register the device as a test device.")
    if units and not real:
        f.add("ADS_ONLY_TEST_IDS", "medium", "Ads", None, None,
              "Only Google test ad IDs (ca-app-pub-3940256099942544) were found, so a release build would show test ads and earn nothing.",
              "Put real IDs in the release build type (buildConfigField / resValue) before publishing.")
    if f"ca-app-pub-{TEST_PUB}~" in manifest_text:
        f.add("ADS_TEST_APP_ID", "low", "Ads", mf, None,
              "The manifest uses the sample AdMob APPLICATION_ID.",
              "Replace it with your app's real ID for release (use manifestPlaceholders per build type).")
    for path, text in prj.code_text.items():
        for m in re.finditer(r"MobileAds\.initialize\s*\(", text):
            before = text[max(0, m.start() - 400): m.start()]
            if not re.search(r"launch\s*(\(|\{)|Dispatchers\.(IO|Default)|thread\s*\{|Thread\s*\{|Executors|withContext", before):
                f.add("ADS_INIT_MAIN_THREAD", "medium", "Ads", path, line_of(text, m.start()),
                      "MobileAds.initialize() runs on the main thread at startup, which adds launch time and can cause ANRs.",
                      "Call it from a background thread: CoroutineScope(Dispatchers.IO).launch { MobileAds.initialize(ctx) {} }.")
        if re.search(r"AdSize\.(BANNER|FULL_BANNER|LARGE_BANNER|SMART_BANNER)\b", text):
            m = re.search(r"AdSize\.(BANNER|FULL_BANNER|LARGE_BANNER|SMART_BANNER)\b", text)
            f.add("ADS_FIXED_BANNER", "low", "Ads", path, line_of(text, m.start()),
                  f"Fixed banner size AdSize.{m.group(1)}: it looks wrong on tablets and in landscape.",
                  "Use an anchored adaptive banner: AdSize.getCurrentOrientationAnchoredAdaptiveBannerAdSize(context, widthDp).")
        if "AdView" in text and not theme_or_test(path):
            if re.search(r"AndroidView\s*\(", text) and not re.search(
                    r"navigationBarsPadding|safeDrawingPadding|windowInsetsPadding|systemBarsPadding|bottomBar\s*=|WindowInsets", text):
                m = re.search(r"AdView", text)
                f.add("ADS_BANNER_INSETS", "medium", "Ads", path, line_of(text, m.start()),
                      "Banner ad in Compose with no navigation-bar insets or Scaffold bottomBar: on edge-to-edge screens it sits "
                      "under the gesture bar, or on top of content.",
                      "Put the banner in Scaffold(bottomBar = { AdBanner(Modifier.navigationBarsPadding()) }) "
                      "or in a Column below the content.")
            if "AdView(" in text and ".destroy()" not in prj.all_code:
                m = re.search(r"AdView\(", text)
                f.add("ADS_NO_DESTROY", "low", "Ads", path, line_of(text, m.start()),
                      "AdView is created but never destroy()ed, so it leaks the WebView/Activity.",
                      "Call adView.destroy() in onDestroy, or DisposableEffect { onDispose { adView.destroy() } }.")
        for m in re.finditer(r"(InterstitialAd|AppOpenAd|RewardedAd)\b[\s\S]{0,600}?\.show\(", text):
            fn_start = text.rfind("fun ", 0, m.start())
            fn_head = text[fn_start: fn_start + 80] if fn_start >= 0 else ""
            if re.search(r"fun (onCreate|onResume|onStart)\b", fn_head) or "LaunchedEffect(Unit)" in text[max(0, m.start() - 300): m.start()]:
                f.add("ADS_FULLSCREEN_ON_LAUNCH", "medium", "Ads", path, line_of(text, m.start()),
                      f"{m.group(1)} is shown as soon as a screen opens. Ads that appear unexpectedly break AdMob's "
                      "'unexpected interstitial' policy and annoy users.",
                      "Show full-screen ads only at natural breaks (after an action completes), with a frequency cap.")
    for path in prj.layouts:
        text = read(path)
        for m in re.finditer(r"<com\.google\.android\.gms\.ads\.AdView\b([^>]*)>?", text):
            attrs = m.group(1)
            if re.search(r'layout_gravity="[^"]*bottom|layout_alignParentBottom="true"|layout_constraintBottom_toBottomOf="parent"', attrs) \
                    and not re.search(r"layout_constraintTop_toBottomOf", attrs):
                f.add("ADS_XML_FLOATING_BANNER", "medium", "Ads", path, line_of(text, m.start()),
                      "Banner is pinned to the bottom of the parent and floats over content (it can cover list items or "
                      "buttons, and with edge-to-edge it goes under the nav bar).",
                      "Put the content above the banner (LinearLayout weight, or a constraint chain content > banner), "
                      "and pad the banner with navigation-bar insets.")
            if 'adSize="BANNER"' in attrs or 'adSize="SMART_BANNER"' in attrs:
                f.add("ADS_FIXED_BANNER", "low", "Ads", path, line_of(text, m.start()),
                      "Fixed banner size in XML.",
                      "Create the AdView in code with an adaptive banner size.")
    if not re.search(r"UserMessagingPlatform|ConsentInformation|ConsentRequestParameters", prj.all_code):
        f.add("ADS_NO_CONSENT", "medium", "Ads", None, None,
              "The app shows ads but has no consent form (Google UMP). Google requires a certified consent message for "
              "users in the EEA, UK and Switzerland, and ads may be limited without it.",
              "Add the UMP SDK: ConsentInformation.requestConsentInfoUpdate(...) and then loadAndShowConsentFormIfRequired(...) "
              "before loading ads.")


def check_show_rate(prj, f):
    """Code patterns that waste matched requests -> low AdMob show rate (impressions / matched requests)."""
    if not re.search(r"com\.google\.android\.gms\.ads|AdView|InterstitialAd|RewardedAd|AppOpenAd|NativeAd", prj.all_code + "".join(read(p) for p in prj.layouts)):
        return
    cat = "Ads show rate"
    load_fullscreen_files = []
    for path, text in prj.code_text.items():
        if theme_or_test(path):
            continue
        # banner loaded in AndroidView update {} -> every recomposition
        for m in re.finditer(r"update\s*=\s*\{[^{}]{0,300}?loadAd\s*\(", text, re.S):
            f.add("SR_LOAD_IN_RECOMPOSE", "high", cat, path, line_of(text, m.start()),
                  "loadAd() is inside AndroidView(update = {...}), so it runs on every recomposition. Many requests get "
                  "matched and replaced before they are ever shown.",
                  "Load once: create and load the AdView in remember { } / factory = { }, never in update.")
        # loads in composable body (not in an effect)
        if "@Composable" in text:
            for m in re.finditer(r"\b(loadAd\s*\(|(InterstitialAd|RewardedAd|RewardedInterstitialAd|AppOpenAd)\.load\s*\()", text):
                fn = text.rfind("fun ", 0, m.start())
                if fn < 0 or "@Composable" not in text[max(0, fn - 80): fn]:
                    continue  # enclosing function is not a composable
                ctx = text[fn: m.start()]
                if re.search(r"LaunchedEffect|DisposableEffect|SideEffect|remember\s*(\(|\{)|factory\s*=|onClick|"
                             r"viewModelScope|rememberCoroutineScope|\.launch\s*\{|onAd\w+", ctx):
                    continue
                f.add("SR_LOAD_IN_COMPOSABLE", "high", cat, path, line_of(text, m.start()),
                      "An ad is loaded directly in a composable body, so each recomposition fires a new request.",
                      "Move loading to a ViewModel or an app-wide AdManager, or at least LaunchedEffect(Unit).")
        # loads in onResume/onStart
        for m in re.finditer(r"override\s+fun\s+(onResume|onStart)\s*\(\s*\)\s*\{", text):
            body = text[m.end(): m.end() + 1200]
            depth, end = 1, 0
            for i, ch in enumerate(body):
                depth += ch == "{"
                depth -= ch == "}"
                if depth == 0:
                    end = i
                    break
            body = body[:end or len(body)]
            lm = re.search(r"loadAd\s*\(|\w+Ad\.load\s*\(|load\w*Ad\s*\(", body)
            if lm:
                f.add("SR_LOAD_ON_RESUME", "medium", cat, path, line_of(text, m.end() + lm.start()),
                      f"An ad is (re)loaded in {m.group(1)}(): every return to the screen requests a new ad, and the "
                      "previous loaded one is thrown away unshown.",
                      "Load once and reuse: keep the loaded ad in an AdManager, and only load when none is cached.")
        # manual refresh timers
        for m in re.finditer(r"(postDelayed|Timer\(|scheduleAtFixedRate|while\s*\(\s*(true|isActive)\s*\)[\s\S]{0,200}?delay\()[\s\S]{0,300}?(loadAd|\.load\()", text):
            f.add("SR_MANUAL_REFRESH", "medium", cat, path, line_of(text, m.start()),
                  "Ads are reloaded on a timer. That adds requests even when the ad isn't visible, and it fights AdMob's own refresh.",
                  "Remove the manual timer, and set the refresh rate in the AdMob console (Google-optimized).")
        # full-screen loads inside Activity / Fragment
        if re.search(r"\b(InterstitialAd|RewardedAd|RewardedInterstitialAd)\.load\s*\(", text):
            load_fullscreen_files.append(path)
            if re.search(r":\s*\w*(Activity|Fragment)\s*\(", text):
                m = re.search(r"\b(InterstitialAd|RewardedAd|RewardedInterstitialAd)\.load\s*\(", text)
                f.add("SR_LOAD_PER_SCREEN", "medium", cat, path, line_of(text, m.start()),
                      f"{m.group(1)} is loaded inside a screen (Activity/Fragment). If the user leaves, or rotates, "
                      "before it's shown, the matched ad is wasted, and the next screen loads another.",
                      "Use one app-wide AdManager (object or Hilt @Singleton) that preloads one ad, shows it, then preloads the next.")
        # loaded every time, shown only every Nth time
        for m in re.finditer(r"%\s*\d+\s*==\s*0[\s\S]{0,250}?\.show\s*\(", text):
            if re.search(r"\.load\s*\(|loadAd\s*\(", text):
                f.add("SR_CONDITIONAL_SHOW", "medium", cat, path, line_of(text, m.start()),
                      "The ad is shown only every Nth time, but the code also loads ads. If a load happens each time, most "
                      "matched ads are never shown.",
                      "Load only when no ad is cached, and decide 'should I show' before requesting a new ad.")
        # app open: 4h expiry
        if "AppOpenAd" in text and not re.search(r"loadTime|currentTimeMillis|SystemClock|elapsedRealtime|Date\(\)\.time|Instant\.now", text):
            m = re.search(r"AppOpenAd", text)
            f.add("SR_APPOPEN_NO_EXPIRY", "medium", cat, path, line_of(text, m.start()),
                  "App open ad without a load-time check. Cached app open ads expire (Google's guide uses 4 hours), so "
                  "stale ads fail to show and show rate drops.",
                  "Store loadTime, and only show if it was loaded less than 4 hours ago; otherwise load a new one.")
        if re.search(r"AppOpenAd\.load", text) and re.search(r"onAdLoaded[\s\S]{0,400}?\.show\s*\(", text):
            m = re.search(r"AppOpenAd\.load", text)
            f.add("SR_APPOPEN_SPLASH_RACE", "medium", cat, path, line_of(text, m.start()),
                  "App open ad is shown inside onAdLoaded on a splash/launch. When it loads after the user has moved on, "
                  "it's never shown (a matched request with no impression).",
                  "Preload app open ads in the background (Application + ProcessLifecycleOwner). Show one only when the "
                  "app comes to the foreground and a fresh ad is cached; otherwise skip and load for next time.")
        # native ads
        if re.search(r"NativeAdView\b", text) and "setNativeAd(" not in prj.all_code:
            m = re.search(r"NativeAdView\b", text)
            f.add("SR_NATIVE_NOT_REGISTERED", "high", cat, path, line_of(text, m.start()),
                  "NativeAdView is used but setNativeAd() is never called, so impressions are not counted. Show rate looks "
                  "near 0% even though ads are on screen.",
                  "After binding the asset views, call nativeAdView.setNativeAd(nativeAd).")
        for m in re.finditer(r"loadAds\s*\([^,]+,\s*(\d+)\s*\)", text):
            if int(m.group(1)) > 1:
                f.add("SR_NATIVE_BATCH", "medium", cat, path, line_of(text, m.start()),
                      f"loadAds(..., {m.group(1)}) loads {m.group(1)} native ads at once. The ones never scrolled into view "
                      "count as matched with no impression.",
                      "Load natives one by one as their slot gets close to the screen, or load fewer.")
        for m in re.finditer(r"(onBindViewHolder|items\s*\(|itemsIndexed\s*\(|item\s*\{)[\s\S]{0,600}?(AdLoader\.Builder|forNativeAd|loadAd\s*\()", text):
            f.add("SR_NATIVE_PER_BIND", "high", cat, path, line_of(text, m.start()),
                  "A new ad is requested while binding a list item. Each scroll or rebind requests again, and most are dropped.",
                  "Load ads into a small cache outside the list, and only bind cached ads in the adapter/LazyColumn items.")
        if "AdView" in text and ".pause()" not in prj.all_code and re.search(r"AdView\s*\(|findViewById<AdView>|binding\.\w*ad", text, re.I):
            m = re.search(r"AdView", text)
            f.add("SR_BANNER_NO_PAUSE", "low", cat, path, line_of(text, m.start()),
                  "Banner AdView is never paused, so it can keep refreshing while the screen is in the background "
                  "(requests without impressions).",
                  "adView.pause() in onPause and adView.resume() in onResume (Compose: a LifecycleEventObserver).")
    if len(load_fullscreen_files) > 1:
        f.add("SR_MANY_LOADERS", "medium", cat, None, None,
              f"Full-screen ads are loaded in {len(load_fullscreen_files)} different files: "
              + ", ".join(os.path.basename(p) for p in load_fullscreen_files[:5])
              + ". Several copies get loaded, but only one can be shown at a time.",
              "Centralize in one AdManager with one cached ad per format/ad unit.")
    for path in prj.layouts:
        text = read(path)
        for m in re.finditer(r"<com\.google\.android\.gms\.ads\.(AdView|nativead\.NativeAdView)\b[^>]*android:visibility=\"(gone|invisible)\"", text):
            f.add("SR_HIDDEN_AD", "medium", cat, path, line_of(text, m.start()),
                  "The ad view starts hidden (gone/invisible). If it's loaded while hidden, the matched ad is never seen.",
                  "Only call loadAd when the view is (about to be) visible, or make it visible when onAdLoaded fires.")


def theme_or_test(path):
    p = path.replace("\\", "/").lower()
    return "/test/" in p or "/androidtest/" in p


# --------------------------------------------------------------------------- orientation, state, lifecycle, misc
def check_more(prj, f):
    manifest_text = "\n".join(read(m) for m in prj.manifests)
    back_optout = 'enableOnBackInvokedCallback="false"' in manifest_text
    has_textfield = re.search(r"\b(Outlined)?TextField\s*\(|BasicTextField\s*\(", prj.all_code) or \
        any("<EditText" in read(p) or "TextInputEditText" in read(p) for p in prj.layouts)
    ime_ok = re.search(r"imePadding|WindowInsets\.ime|consumeWindowInsets|Type\.ime\(\)", prj.all_code)
    if has_textfield and not ime_ok:
        f.add("PROJECT_KEYBOARD_COVERS", "medium", "Layout / screen sizes", None, None,
              "The app has text fields but never handles the keyboard (IME) insets. With edge-to-edge, adjustResize alone "
              "no longer works, so the keyboard covers fields and buttons at the bottom.",
              "Compose: Modifier.imePadding() on the form or Scaffold content. Views: handle WindowInsetsCompat.Type.ime().")

    for path, text in prj.code_text.items():
        if theme_or_test(path):
            continue
        # predictive back (targetSdk 36): onBackPressed not called on Android 16
        for m in re.finditer(r"override\s+fun\s+onBackPressed\s*\(|KEYCODE_BACK", text):
            if (prj.target_sdk or 0) >= 36 and not back_optout:
                f.add("CODE_ON_BACK_PRESSED", "high", "Navigation / back", path, line_of(text, m.start()),
                      "With targetSdk 36, Android 16 uses predictive back: onBackPressed() is NOT called and KEYCODE_BACK "
                      "is not delivered, so this back-button logic silently stops working.",
                      "Use onBackPressedDispatcher.addCallback(this) { ... } (Views) or BackHandler { ... } (Compose).")
            elif (prj.target_sdk or 0) >= 33:
                f.add("CODE_ON_BACK_PRESSED", "low", "Navigation / back", path, line_of(text, m.start()),
                      "onBackPressed()/KEYCODE_BACK is deprecated and stops working when targetSdk reaches 36.",
                      "Move to OnBackPressedCallback / BackHandler now.")
        # static leaks
        for m in re.finditer(r"companion\s+object\s*\{|^\s*object\s+\w+\s*\{", text, re.M):
            body = text[m.end(): m.end() + 800]
            body = body[: body.find("\n}") if "\n}" in body else len(body)]
            lm = re.search(r"va[rl]\s+(\w+)\s*:\s*[\w.]*(Activity|Context|View|Fragment|Binding)\b", body)
            if lm:
                f.add("CODE_STATIC_LEAK", "medium", "Performance / memory", path, line_of(text, m.end() + lm.start()),
                      f"'{lm.group(1)}' keeps a {lm.group(2)} in a static/object field, so every old screen stays in memory "
                      "(memory grows on each rotation).",
                      "Don't store Activity/View/Context statically; use applicationContext or pass it when needed.")
        # rotation / process-death state
        for m in re.finditer(r"by\s+remember\s*\{\s*mutableStateOf\(\s*(\"\"|TextFieldValue\()", text):
            f.add("COMPOSE_STATE_LOST_ROTATION", "medium", "Orientation / state", path, line_of(text, m.start()),
                  "Text the user types is kept in remember { }: it is lost on rotation, dark-mode switch, language change "
                  "and when Android kills the app in the background.",
                  "Use rememberSaveable { mutableStateOf(\"\") } or keep it in a ViewModel (SavedStateHandle).")
        for m in re.finditer(r"by\s+remember\s*\{\s*mutable(Int|Long|Float)?StateOf\((?!\s*\"\")", text):
            f.add("COMPOSE_REMEMBER_STATE", "low", "Orientation / state", path, line_of(text, m.start()),
                  "UI state in remember { } resets on rotation (selected tab, counters, open dialogs).",
                  "Use rememberSaveable for state that must survive rotation, or a ViewModel.")
        # heavy work in composition
        if "@Composable" in text:
            for m in re.finditer(r"\(\s*\d+\s*\.\.\s*(\d{5,})\s*\)|\.(sorted|sortedBy|sortedDescending)\w*\s*[\(\{]", text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                cur = text[line_start: line_end if line_end != -1 else len(text)]
                prev_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
                prev = text[prev_start: max(prev_start, line_start - 1)].rstrip()
                guard = r"remember\s*(\(|\{)|LaunchedEffect|withContext|derivedStateOf|viewModelScope|suspend fun|produceState"
                if re.search(guard, cur) or (re.search(guard, prev) and prev.endswith(("{", "->"))):
                    continue
                big = m.group(1) is not None
                f.add("COMPOSE_HEAVY_WORK", "medium" if big else "low", "Performance / memory", path,
                      line_of(text, m.start()),
                      "Heavy work (large loop / sorting) runs directly inside a composable, so it repeats on every "
                      "recomposition. This causes jank and freezes at launch.",
                      "Move it to a ViewModel, or wrap it: remember(key) { ... } / LaunchedEffect + withContext(Dispatchers.Default).")
        # raw threads
        for m in re.finditer(r"\bThread\s*\{|\bthread\s*(\(|\{)|Thread\(\s*Runnable", text):
            f.add("CODE_RAW_THREAD", "low", "Crash risk", path, line_of(text, m.start()),
                  "A raw Thread: any exception thrown in it kills the whole app, and it isn't cancelled when the screen closes.",
                  "Use coroutines (viewModelScope / lifecycleScope + Dispatchers.IO) with try/catch.")
        # landscape: full-height column that cannot scroll
        for m in re.finditer(r"Column\s*\(\s*(modifier\s*=\s*)?Modifier[^)]*fillMaxSize\(\)", text):
            region = text[m.start(): m.start() + 300]
            if "verticalScroll" not in region and "LazyColumn" not in text:
                f.add("COMPOSE_NO_SCROLL", "low", "Orientation / state", path, line_of(text, m.start()),
                      "A full-screen Column that can't scroll: in landscape or with a large font, the bottom content is unreachable.",
                      "Add .verticalScroll(rememberScrollState()), or use LazyColumn.")

    # release build config
    for g in prj.gradle:
        t = read(g)
        rel = re.search(r"(release|getByName\(\"release\"\))\s*\{([\s\S]{0,800}?)\n\s*\}", t)
        if not rel:
            continue
        body = rel.group(2)
        if re.search(r"(isDebuggable|debuggable)\s*(=\s*)?true", body):
            f.add("BUILD_RELEASE_DEBUGGABLE", "high", "Build", g, line_of(t, rel.start()),
                  "The release build is debuggable. Google Play rejects it, and it is a security risk.",
                  "Remove isDebuggable = true from release.")
        if re.search(r"(isMinifyEnabled|minifyEnabled)\s*(=\s*)?false", body):
            f.add("BUILD_NO_MINIFY", "low", "Build", g, line_of(t, rel.start()),
                  "Release build is not minified: the APK is bigger and the code is easy to read.",
                  "isMinifyEnabled = true and isShrinkResources = true. Then test the release build, because R8 can break reflection.")
    if 'usesCleartextTraffic="true"' in manifest_text:
        f.add("MANIFEST_CLEARTEXT", "low", "Build", prj.manifests[0] if prj.manifests else None, None,
              "usesCleartextTraffic=\"true\" allows unencrypted http:// traffic.",
              "Use https, or a network_security_config that allows only the hosts that need http.")
    # big images
    for dirpath, _, files in os.walk(prj.root):
        if "/build/" in dirpath.replace("\\", "/") + "/" or "/res/drawable" not in dirpath.replace("\\", "/") + "/":
            continue
        for fn in files:
            fp = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            if fn.lower().endswith((".png", ".jpg", ".jpeg")) and size > 400 * 1024:
                f.add("RES_BIG_IMAGE", "low", "Performance / memory", fp, None,
                      f"Image is {size // 1024} KB: a slow first draw and a risk of OutOfMemoryError on low-end phones.",
                      "Convert it to WebP, resize it to the displayed size, or use a vector drawable.")


# --------------------------------------------------------------------------- output
def to_markdown(prj, items):
    counts = defaultdict(int)
    for it in items:
        counts[it["severity"]] += 1
    out = ["# Static UI scan", "",
           f"- Project: `{prj.root}`",
           f"- targetSdk: {prj.target_sdk}, minSdk: {prj.min_sdk}",
           f"- Files: {len(prj.layouts)} layouts, {len(prj.code)} Kotlin/Java, {len(prj.values)} values",
           f"- Palette colors found: {len(prj.palette)}",
           f"- Findings: **{counts['high']} high**, {counts['medium']} medium, {counts['low']} low", ""]
    by_cat = defaultdict(list)
    for it in items:
        by_cat[it["category"]].append(it)
    for cat in sorted(by_cat, key=lambda c: min(SEV_ORDER[i["severity"]] for i in by_cat[c])):
        out.append(f"## {cat}")
        out.append("")
        for it in by_cat[cat]:
            where = it["file"]
            if it["lines"]:
                where += ":" + ",".join(str(x) for x in it["lines"][:5])
            more = f" (x{it['count']})" if it["count"] > 1 else ""
            out.append(f"- **[{it['severity'].upper()}] {it['rule']}**{more} — `{where}`  ")
            out.append(f"  {it['message']}  ")
            out.append(f"  Fix: {it['fix']}")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--out", help="write JSON findings here")
    ap.add_argument("--md", help="write Markdown summary here")
    args = ap.parse_args()
    if not os.path.isdir(args.project):
        sys.exit(f"Not a directory: {args.project}")
    prj = Project(args.project)
    if not (prj.layouts or prj.code or prj.manifests):
        sys.exit("No Android sources found (no layouts, Kotlin/Java or AndroidManifest.xml).")
    f = Findings(prj.root)
    for check in (check_gradle, check_layouts, check_values, check_compose_and_code, check_fonts, check_manifest,
                  check_ads, check_show_rate, check_more):
        check(prj, f)
    items = f.all()
    md = to_markdown(prj, items)
    for target, data in ((args.out, json.dumps({"targetSdk": prj.target_sdk, "minSdk": prj.min_sdk,
                                                "findings": items}, indent=2)), (args.md, md)):
        if target:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(data)
    print(md)


if __name__ == "__main__":
    main()
