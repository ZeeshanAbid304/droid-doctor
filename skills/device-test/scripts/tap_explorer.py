#!/usr/bin/env python3
"""
Tap explorer for droid-doctor.

Starts the app fresh, finds every clickable element on the screen, taps each one
(re-launching the app before every tap so results don't mix), and records what
happened:
    OK          nothing bad
    NAVIGATED   opened another screen (explored up to --depth)
    CRASH       app threw an exception (exception + first app stack frame)
    FREEZE/ANR  main thread blocked (input not handled for 3 s+; ANR if Android said so)
    CLOSED      app process disappeared without a Java crash

For every new screen it also:
    - saves a screenshot + UI dump (+ meta) for analyze_ui_dump.py
    - types text into the first text field, rotates to landscape and back, and
      reports a crash on rotation or lost state (typed text / visible content gone)

Buttons whose label looks dangerous (delete, logout, buy, pay, send, ...) are
skipped unless --allow-risky is given.

Usage:
    tap_explorer.py -p <package> -c <pkg/.Activity> [-s SERIAL] [-o out_dir]
                    [--max-taps 40] [--depth 2] [--max-minutes 15] [--allow-risky]
Standard library only.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

DANGER = re.compile(
    r"\b(delete|remove|erase|clear\s*(all|data|history)|reset|log\s*out|sign\s*out|uninstall|"
    r"pay|buy|purchase|subscribe|checkout|place\s*order|send|call|dial|share|rate\s*us|report|"
    r"exit|quit|close\s*app|factory)\b", re.I)
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
TYPED = "qa123"


class Dev:
    def __init__(self, serial, pkg, comp):
        self.base = ["adb"] + (["-s", serial] if serial else [])
        self.pkg, self.comp = pkg, comp

    def run(self, *args, timeout=30, binary=False):
        try:
            r = subprocess.run(self.base + list(args), capture_output=True, timeout=timeout)
            out = r.stdout
        except subprocess.TimeoutExpired:
            return None
        return out if binary else out.decode("utf-8", "replace").replace("\r", "")

    def sh(self, cmd, timeout=30):
        return self.run("shell", cmd, timeout=timeout)

    def timed_sh(self, cmd, timeout):
        t0 = time.time()
        out = self.sh(cmd, timeout=timeout)
        return out is not None, time.time() - t0

    # ---- state
    def pid(self):
        return (self.sh(f"pidof {self.pkg}") or "").strip()

    def crash_count(self):
        return (self.run("logcat", "-b", "crash", "-d") or "").count("FATAL EXCEPTION")

    def crash_after(self, n):
        log = self.run("logcat", "-b", "crash", "-d") or ""
        blocks = log.split("FATAL EXCEPTION")
        if len(blocks) - 1 <= n:
            return None
        block = blocks[n + 1]
        exc = frame = ""
        for line in block.splitlines():
            body = re.sub(r"^.*?AndroidRuntime:\s*", "", line).strip()
            if not exc and re.search(r"(Exception|Error)\b", body) and not body.startswith("Process:"):
                exc = body
            if not frame and body.startswith("at " + self.pkg):
                frame = body
            if exc and frame:
                break
        return (exc or "unknown exception")[:200], frame[:200]

    def anr_logged(self, since_lines):
        log = self.run("logcat", "-b", "main,system", "-d") or ""
        lines = log.splitlines()[since_lines:]
        return any(("ANR in " + self.pkg) in ln for ln in lines)

    def log_len(self):
        return len((self.run("logcat", "-b", "main,system", "-d") or "").splitlines())

    def focus(self):
        out = self.sh("dumpsys window") or ""
        m = re.search(r"mCurrentFocus=(.*)", out)
        return m.group(1) if m else ""

    def size_density(self):
        s = self.sh("wm size") or ""
        d = self.sh("wm density") or ""
        sz = re.findall(r"(\d+)x(\d+)", s)
        dn = re.findall(r"density: (\d+)", d)
        w, h = (int(sz[-1][0]), int(sz[-1][1])) if sz else (1080, 2400)
        return w, h, int(dn[-1]) if dn else 420

    def bars(self):
        out = self.sh("dumpsys window") or ""
        sb = re.search(r"(?:statusBars|ITYPE_STATUS_BAR) frame=\[\d+,\d+\]\[\d+,(\d+)\]", out)
        nb = re.search(r"(?:navigationBars|ITYPE_NAVIGATION_BAR) frame=\[\d+,(\d+)\]\[\d+,\d+\]", out)
        return int(sb.group(1)) if sb else 0, int(nb.group(1)) if nb else 0

    # ---- actions
    def wake(self):
        self.sh("input keyevent KEYCODE_WAKEUP")
        self.sh("wm dismiss-keyguard")

    def launch(self):
        self.sh(f"am force-stop {self.pkg}")
        self.wake()
        self.sh(f"am start -W -n {self.comp}", timeout=40)
        time.sleep(2.0)

    def rotate(self, r):
        self.sh("settings put system accelerometer_rotation 0")
        self.sh(f"settings put system user_rotation {r}")
        time.sleep(2.5)

    def dump(self):
        for _ in range(3):
            self.sh("uiautomator dump /data/local/tmp/qa_explore.xml", timeout=25)
            xml = self.run("exec-out", "cat", "/data/local/tmp/qa_explore.xml", timeout=15)
            if xml and "<hierarchy" in xml:
                try:
                    return ET.fromstring(xml[xml.find("<hierarchy"):]), xml
                except ET.ParseError:
                    pass
            time.sleep(1)
        return None, None

    def screenshot(self, path):
        png = self.run("exec-out", "screencap", "-p", binary=True, timeout=20)
        if png:
            with open(path, "wb") as fh:
                fh.write(png)


# --------------------------------------------------------------------------- UI helpers
def parse_bounds(n):
    m = BOUNDS.fullmatch(n.get("bounds", ""))
    return tuple(map(int, m.groups())) if m else None


def subtree_text(n, limit=3):
    out = []
    for c in n.iter("node"):
        t = (c.get("text") or c.get("content-desc") or "").strip()
        if t:
            out.append(t)
        if len(out) >= limit:
            break
    return " ".join(out)


def clickables(root, pkg):
    items, seen = [], set()
    for n in root.iter("node"):
        if n.get("package") != pkg or n.get("clickable") != "true" or n.get("enabled") == "false":
            continue
        b = parse_bounds(n)
        if not b or b[2] - b[0] < 4 or b[3] - b[1] < 4:
            continue
        label = subtree_text(n) or n.get("resource-id", "").split("/")[-1] or n.get("class", "").split(".")[-1]
        label = re.sub(r"\s+", " ", label)[:80]
        key = label + "|" + n.get("class", "")
        if key in seen:
            key += f"|{b[0]},{b[1]}"
        seen.add(key)
        items.append({"label": label, "key": key, "bounds": b,
                      "editable": "EditText" in n.get("class", "") or n.get("focusable") == "true" and "Edit" in n.get("class", "")})
    return items


def editables(root, pkg):
    out = []
    for n in root.iter("node"):
        if n.get("package") == pkg and "EditText" in n.get("class", ""):
            b = parse_bounds(n)
            if b:
                out.append(b)
    return out


def visible_texts(root, pkg):
    return {(n.get("text") or "").strip() for n in root.iter("node")
            if n.get("package") == pkg and (n.get("text") or "").strip()}


def signature(root, pkg):
    parts = sorted(c["key"] for c in clickables(root, pkg))
    if not parts:
        parts = sorted(visible_texts(root, pkg))[:20]
    return hashlib.md5("\n".join(parts).encode()).hexdigest()[:10]


def center(b):
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


# --------------------------------------------------------------------------- explorer
class Explorer:
    def __init__(self, dev, out, max_taps, depth, max_minutes, allow_risky):
        self.d, self.out = dev, out
        self.max_taps, self.depth = max_taps, depth
        self.deadline = time.time() + max_minutes * 60
        self.allow_risky = allow_risky
        self.results, self.screens, self.rotation = [], {}, []
        self.taps = 0
        os.makedirs(out, exist_ok=True)

    def note(self, msg):
        print(msg, flush=True)

    def goto(self, path):
        """Fresh launch, then replay taps by label. Returns (root, xml) or (None, None)."""
        self.d.launch()
        root, xml = self.d.dump()
        for label in path:
            if root is None:
                return None, None
            target = next((c for c in clickables(root, self.d.pkg) if c["label"] == label), None)
            if not target:
                return None, None
            x, y = center(target["bounds"])
            self.d.sh(f"input tap {x} {y}", timeout=6)
            time.sleep(1.5)
            root, xml = self.d.dump()
        return root, xml

    def save_screen(self, root, xml, path):
        sig = signature(root, self.d.pkg)
        if sig in self.screens:
            return sig, False
        idx = len(self.screens) + 1
        name = f"screen_{idx:02d}"
        self.screens[sig] = {"name": name, "path": path}
        w, h, dens = self.d.size_density()
        sb, nb = self.d.bars()
        with open(os.path.join(self.out, name + ".xml"), "w", encoding="utf-8") as fh:
            fh.write(xml)
        with open(os.path.join(self.out, name + ".meta"), "w") as fh:
            fh.write(f"size={w}x{h} density={dens} status_bar_bottom={sb} nav_bar_top={nb} "
                     f"config=explore path={'>'.join(path) or 'start'}\n")
        self.d.screenshot(os.path.join(self.out, name + ".png"))
        self.note(f"[screen] {name}: {' > '.join(path) or 'start screen'}")
        return sig, True

    def rotation_test(self, root, path, name):
        pkg = self.d.pkg
        typed = False
        eds = editables(root, pkg)
        if eds:
            x, y = center(eds[0])
            self.d.sh(f"input tap {x} {y}", timeout=6)
            time.sleep(0.5)
            self.d.sh(f"input text {TYPED}", timeout=6)
            self.d.sh("input keyevent KEYCODE_BACK")  # hide keyboard
            time.sleep(0.8)
            typed = True
        before_root, _ = self.d.dump()
        before = visible_texts(before_root, pkg) if before_root is not None else set()
        pid0, n0 = self.d.pid(), self.d.crash_count()
        self.d.rotate(1)
        land_root, land_xml = self.d.dump()
        if land_root is not None:
            w, h, dens = self.d.size_density()
            sb, nb = self.d.bars()
            with open(os.path.join(self.out, name + "_land.xml"), "w", encoding="utf-8") as fh:
                fh.write(land_xml)
            with open(os.path.join(self.out, name + "_land.meta"), "w") as fh:
                fh.write(f"size={h if w < h else w}x{w if w < h else h} density={dens} "
                         f"status_bar_bottom={sb} nav_bar_top={nb} config=explore-landscape\n")
            self.d.screenshot(os.path.join(self.out, name + "_land.png"))
        crash = self.d.crash_after(n0)
        self.d.rotate(0)
        after_root, _ = self.d.dump()
        after = visible_texts(after_root, pkg) if after_root is not None else set()
        pid1 = self.d.pid()
        res = {"screen": name, "path": " > ".join(path) or "start"}
        if crash:
            res.update(result="CRASH ON ROTATION", detail=f"{crash[0]} {crash[1]}")
        elif not pid1:
            res.update(result="CLOSED ON ROTATION", detail="process gone after rotation")
        elif typed and not any(TYPED in t for t in after):
            res.update(result="STATE LOST", detail=f"text typed into the field ('{TYPED}') disappeared after rotation")
        else:
            lost = sorted(t for t in before - after if not re.fullmatch(r"[\d:.,%\s]+", t))
            if after_root is not None and before and len(lost) >= max(2, len(before) // 3):
                res.update(result="SCREEN CHANGED", detail="after rotation these texts are gone: " + "; ".join(lost[:5]))
            else:
                res.update(result="OK", detail="typed text kept" if typed else "")
        if pid0 and pid1 and pid0 != pid1 and res["result"] == "OK":
            res.update(result="RESTARTED", detail="app process restarted on rotation")
        self.rotation.append(res)
        self.note(f"[rotate] {name}: {res['result']} {res['detail']}")

    def observe_tap(self, x, y):
        """Tap and classify the outcome."""
        n0, l0, pid0 = self.d.crash_count(), self.d.log_len(), self.d.pid()
        ok, dt = self.d.timed_sh(f"input tap {x} {y}", timeout=4)
        frozen = not ok or dt > 3.0
        time.sleep(1.2)
        if not frozen:
            # a second input event: if the main thread is blocked, it won't be handled
            ok2, dt2 = self.d.timed_sh("input keyevent KEYCODE_SHIFT_LEFT", timeout=4)
            frozen = not ok2 or dt2 > 2.5
        if frozen:
            t_end = time.time() + 12
            anr = False
            while time.time() < t_end:
                if self.d.anr_logged(l0) or "isn't responding" in self.d.focus() or "Application Not Responding" in self.d.focus():
                    anr = True
                    break
                time.sleep(1)
            crash = self.d.crash_after(n0)
            if crash:
                return "CRASH", f"{crash[0]} {crash[1]}"
            return ("ANR", "Android showed 'isn't responding' (main thread blocked)") if anr else \
                   ("FREEZE", "main thread did not handle input for 3s+ (would ANR on next touch)")
        crash = self.d.crash_after(n0)
        if crash:
            return "CRASH", f"{crash[0]} {crash[1]}"
        time.sleep(1.0)
        crash = self.d.crash_after(n0)  # background-thread crashes come a bit later
        if crash:
            return "CRASH", f"{crash[0]} {crash[1]}"
        if not self.d.pid():
            return "CLOSED", "app process ended (finish() or native crash)"
        if self.d.anr_logged(l0):
            return "ANR", "ANR logged"
        if self.d.pkg not in self.d.focus():
            return "LEFT APP", self.d.focus()[:120]
        return "OK", ""

    def run(self):
        queue = [[]]
        tested = set()
        while queue and self.taps < self.max_taps and time.time() < self.deadline:
            path = queue.pop(0)
            root2, xml = self.goto(path)
            if root2 is None:
                self.note(f"[skip] could not reach {' > '.join(path)}")
                continue
            sig, new = self.save_screen(root2, xml or "", path)
            name = self.screens[sig]["name"]
            if new:
                self.rotation_test(root2, path, name)
            items = clickables(root2, self.d.pkg)
            fresh = False  # rotation test touched the screen -> relaunch before first tap
            for it in items:
                if self.taps >= self.max_taps or time.time() > self.deadline:
                    break
                key = (sig, it["key"])
                if key in tested:
                    continue
                tested.add(key)
                if it["editable"]:
                    continue
                if DANGER.search(it["label"]) and not self.allow_risky:
                    self.results.append({"screen": name, "button": it["label"], "result": "SKIPPED",
                                         "detail": "looks dangerous (use --allow-risky)"})
                    continue
                if not fresh:
                    r, _ = self.goto(path)
                    if r is None:
                        continue
                    cur = next((c for c in clickables(r, self.d.pkg) if c["key"] == it["key"]), None)
                    if not cur:
                        continue
                    it = dict(it, bounds=cur["bounds"])
                fresh = False
                x, y = center(it["bounds"])
                self.taps += 1
                result, detail = self.observe_tap(x, y)
                if result == "OK":
                    after, _ = self.d.dump()
                    if after is not None and signature(after, self.d.pkg) != sig:
                        result = "NAVIGATED"
                        if len(path) < self.depth:
                            queue.append(path + [it["label"]])
                self.results.append({"screen": name, "button": it["label"], "result": result, "detail": detail})
                self.note(f"[tap] {name} / {it['label']}: {result} {detail}")
                if result in ("CRASH", "ANR", "FREEZE", "CLOSED"):
                    self.d.sh(f"am force-stop {self.d.pkg}")
        self.d.rotate(0)
        self.write()

    def write(self):
        with open(os.path.join(self.out, "results.json"), "w", encoding="utf-8") as fh:
            json.dump({"taps": self.results, "rotation": self.rotation,
                       "screens": {v["name"]: v["path"] for v in self.screens.values()}}, fh, indent=2)
        bad = [r for r in self.results if r["result"] in ("CRASH", "ANR", "FREEZE", "CLOSED")]
        rbad = [r for r in self.rotation if r["result"] not in ("OK",)]
        L = [f"- Screens explored: {len(self.screens)}, buttons tapped: {self.taps}, "
             f"problems: {len(bad)} button(s), {len(rbad)} rotation issue(s)"]
        for r in bad:
            L.append(f"  - **{r['result']}** tapping '{r['button']}' on {r['screen']}: {r['detail']}")
        for r in rbad:
            L.append(f"  - **{r['result']}** rotating {r['screen']} ({r['path']}): {r['detail']}")
        skipped = [r["button"] for r in self.results if r["result"] == "SKIPPED"]
        if skipped:
            L.append(f"  - Skipped as risky: {', '.join(skipped[:10])}")
        L.append("  - Full table: explore/results.md, screenshots: explore/screen_*.png")
        with open(os.path.join(self.out, "summary.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(L) + "\n")
        T = ["# Tap explorer results", "", "| Screen | Button | Result | Detail |", "|---|---|---|---|"]
        for r in self.results:
            T.append(f"| {r['screen']} | {r['button'].replace('|', '/')} | {r['result']} | {r['detail'].replace('|', '/')} |")
        T += ["", "## Rotation", "", "| Screen | Path | Result | Detail |", "|---|---|---|---|"]
        for r in self.rotation:
            T.append(f"| {r['screen']} | {r['path']} | {r['result']} | {r['detail'].replace('|', '/')} |")
        with open(os.path.join(self.out, "results.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(T) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--package", required=True)
    ap.add_argument("-c", "--component", required=True, help="launcher component, e.g. com.x/.MainActivity")
    ap.add_argument("-s", "--serial", default="")
    ap.add_argument("-o", "--out", default="qa-report/device/explore")
    ap.add_argument("--max-taps", type=int, default=40)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--max-minutes", type=float, default=15)
    ap.add_argument("--allow-risky", action="store_true")
    a = ap.parse_args()
    dev = Dev(a.serial, a.package, a.component)
    ex = Explorer(dev, a.out, a.max_taps, a.depth, a.max_minutes, a.allow_risky)
    try:
        ex.run()
    except KeyboardInterrupt:
        ex.write()
    finally:
        dev.sh("settings put system user_rotation 0")


if __name__ == "__main__":
    main()
