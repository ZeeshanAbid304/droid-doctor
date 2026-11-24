#!/usr/bin/env python3
"""
Analyze uiautomator dumps captured by device_check.sh.

For each <config>.xml (+ <config>.meta) in a screens folder, finds:
  - views drawn under the status bar or the navigation/gesture bar
  - views cut off at the screen edge
  - overlapping text
  - truncated text (ending in an ellipsis)
  - touch targets smaller than 48dp
  - screens with no views from the app (blank screen / app not in front)
  - ads (AdMob banners, native ads) that overlap buttons/content, sit under the
    navigation bar, or touch a button (accidental-click risk, AdMob policy)

Works on device_check.sh screens/ and tap_explorer.py explore/ folders.

Usage:
    python3 analyze_ui_dump.py <dir> [<dir> ...] -p <package> [--md out.md]
"""
import argparse
import os
import re
import sys
from xml.etree import ElementTree as ET

BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_meta(path):
    meta = {}
    if os.path.exists(path):
        for tok in open(path).read().split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                meta[k] = v
    w = h = None
    if re.fullmatch(r"\d+x\d+", meta.get("size", "")):
        w, h = map(int, meta["size"].split("x"))
    dens = int(meta["density"]) if meta.get("density", "").isdigit() else 420
    sb = int(meta.get("status_bar_bottom", 0) or 0)
    nb = int(meta.get("nav_bar_top", 0) or 0)
    return w, h, dens, sb, nb


AD_RE = re.compile(r"(^|[/_.:])(ad_?view|adview|ad_?container|banner_?ad|ad_?banner|native_?ad|nativead|ad_?frame|admob)", re.I)
AD_TEXT = re.compile(r"^(test ad|advertisement|ad|sponsored|install|open)$", re.I)


def is_ad(n):
    cls = n.get("class", "")
    rid = n.get("resource-id", "")
    desc = (n.get("content-desc") or "").strip()
    if "gms.ads" in cls or "AdView" in cls or "NativeAdView" in cls:
        return True
    if AD_RE.search(rid):
        return True
    if re.fullmatch(r"(test ad|advertisement)", desc, re.I):
        return True
    return False


def overlap(a, c):
    ix = min(a[2], c[2]) - max(a[0], c[0])
    iy = min(a[3], c[3]) - max(a[1], c[1])
    return (ix * iy) if ix > 0 and iy > 0 else 0


def label(n):
    t = n.get("text") or n.get("content-desc") or n.get("resource-id") or n.get("class", "")
    return t[:50]


def analyze(xml_path, meta_path, pkg):
    issues = []
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError) as e:
        return [("high", "No UI dump", f"could not read dump ({e}); app may have crashed or shows a secure/animated screen")]
    w, h, dens, sb, nb = parse_meta(meta_path)
    nodes = []
    for n in root.iter("node"):
        if n.get("package") != pkg:
            continue
        m = BOUNDS.fullmatch(n.get("bounds", ""))
        if not m:
            continue
        b = tuple(map(int, m.groups()))
        if b[2] <= b[0] or b[3] <= b[1]:
            continue
        nodes.append((n, b))
    if not nodes:
        return [("high", "Blank or foreign screen", "no views from the app are on screen (crash, ANR dialog, or blank screen)")]
    if w is None:
        w = max(b[2] for _, b in nodes)
        h = max(b[3] for _, b in nodes)
    px48 = 48 * dens / 160.0 * 0.9  # small tolerance

    def is_content(n):
        return bool((n.get("text") or "").strip() or (n.get("content-desc") or "").strip()
                    or n.get("clickable") == "true")

    for n, b in nodes:
        if not is_content(n):
            continue
        name = label(n)
        if sb and b[1] < sb and b[3] > 0 and (b[3] - b[1]) < h * 0.5:
            issues.append(("high", "Under status bar",
                           f"'{name}' at {b} overlaps the status bar (0..{sb}px). Missing status bar insets."))
        if nb and nb < h and b[3] > nb and n.get("clickable") == "true" and (b[3] - b[1]) < h * 0.5:
            issues.append(("high", "Under navigation bar",
                           f"clickable '{name}' at {b} goes into the nav/gesture bar (y>{nb}px). Missing nav bar insets."))
        if b[0] < 0 or b[2] > w + 2:
            issues.append(("medium", "Cut off at edge",
                           f"'{name}' at {b} goes past the screen width {w}px."))
        txt = (n.get("text") or "").rstrip()
        if txt.endswith("…") or txt.endswith("..."):
            issues.append(("medium", "Truncated text", f"'{txt[:60]}' is cut with an ellipsis."))
        if n.get("clickable") == "true" and ((b[2] - b[0]) < px48 or (b[3] - b[1]) < px48):
            issues.append(("low", "Small touch target",
                           f"'{name}' is {(b[2]-b[0])*160//dens}x{(b[3]-b[1])*160//dens}dp (< 48dp)."))

    texts = [(n, b) for n, b in nodes if (n.get("text") or "").strip()]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            (n1, a), (n2, c) = texts[i], texts[j]
            ix = min(a[2], c[2]) - max(a[0], c[0])
            iy = min(a[3], c[3]) - max(a[1], c[1])
            if ix > 4 and iy > 4:
                small = min((a[2]-a[0])*(a[3]-a[1]), (c[2]-c[0])*(c[3]-c[1]))
                if small and ix * iy > 0.25 * small and a != c:
                    issues.append(("medium", "Overlapping text",
                                   f"'{label(n1)}' and '{label(n2)}' overlap."))
    # ---- ads
    parent = {c: p for p in root.iter() for c in p}
    ad_nodes = []
    for n in root.iter("node"):
        m = BOUNDS.fullmatch(n.get("bounds", ""))
        if not m:
            continue
        b = tuple(map(int, m.groups()))
        txt = (n.get("text") or "").strip()
        ad = is_ad(n)
        if not ad and txt.lower() == "test ad":
            # "Test Ad" label: the ad is its banner-sized ancestor
            p = parent.get(n)
            while p is not None and p.tag == "node":
                pm = BOUNDS.fullmatch(p.get("bounds", ""))
                if pm:
                    pb = tuple(map(int, pm.groups()))
                    if (pb[3] - pb[1]) > (b[3] - b[1]) * 2:
                        n, b, ad = p, pb, True
                        break
                p = parent.get(p)
        if ad and b[2] > b[0] and b[3] > b[1]:
            if not any(b == x[1] for x in ad_nodes):
                ad_nodes.append((n, b))
    ad_ids = set()
    for an, _ in ad_nodes:
        for d in an.iter("node"):
            ad_ids.add(id(d))
    gap_px = 8 * dens / 160.0
    for an, ab in ad_nodes:
        aname = an.get("resource-id", "").split("/")[-1] or "ad"
        for n, b in nodes:
            if id(n) in ad_ids or n is an:
                continue
            if b[0] <= ab[0] and b[1] <= ab[1] and b[2] >= ab[2] and b[3] >= ab[3]:
                continue  # container of the ad
            if not is_content(n):
                continue
            ov = overlap(ab, b)
            if ov > 0:
                sev = "high" if n.get("clickable") == "true" else "medium"
                issues.append((sev, "Ad overlaps content",
                               f"ad '{aname}' {ab} covers '{label(n)}' {b}. "
                               "Ads must not cover app content or buttons (AdMob policy, accidental clicks)."))
            elif n.get("clickable") == "true":
                vgap = max(b[1] - ab[3], ab[1] - b[3])
                hgap = max(b[0] - ab[2], ab[0] - b[2])
                if 0 <= vgap < gap_px and hgap < 0:
                    issues.append(("medium", "Ad too close to button",
                                   f"ad '{aname}' is only {int(vgap*160/dens)}dp from button '{label(n)}' "
                                   "(accidental clicks; keep clear space)."))
        if nb and ab[3] > nb + 2:
            issues.append(("high", "Ad under navigation bar",
                           f"ad '{aname}' {ab} extends into the nav/gesture bar (y>{nb}px)."))
        if sb and ab[1] < sb:
            issues.append(("high", "Ad under status bar", f"ad '{aname}' {ab} is under the status bar."))
        if ab[2] > w + 2 or ab[0] < 0:
            issues.append(("medium", "Ad cut off", f"ad '{aname}' {ab} is wider than the screen ({w}px)."))

    # dedupe
    seen, out = set(), []
    for it in issues:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", help="folders with <name>.xml + <name>.meta")
    ap.add_argument("-p", "--package", required=True)
    ap.add_argument("--md")
    a = ap.parse_args()
    lines = ["# UI dump analysis", ""]
    order = {"high": 0, "medium": 1, "low": 2}
    total = 0
    for d in a.dirs:
        if not os.path.isdir(d):
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith(".xml"))
        for f in files:
            cfg = f[:-4]
            meta = os.path.join(d, cfg + ".meta")
            where = ""
            if os.path.exists(meta):
                m = re.search(r"path=(.*)", open(meta).read())
                where = f" — reached by: {m.group(1).strip()}" if m else ""
            res = analyze(os.path.join(d, f), meta, a.package)
            total += len(res)
            png = os.path.join(os.path.basename(os.path.normpath(d)), cfg + ".png")
            lines.append(f"## {cfg}  ({len(res)} issue(s)){where}  — `{png}`")
            for sev, kind, msg in sorted(res, key=lambda r: order[r[0]]):
                lines.append(f"- [{sev.upper()}] {kind}: {msg}")
            if not res:
                lines.append("- no automatic issues found (still review the screenshot)")
            lines.append("")
    if total == 0 and len(lines) == 2:
        sys.exit("No .xml dumps found in: " + ", ".join(a.dirs))
    md = "\n".join(lines)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    print(md)


if __name__ == "__main__":
    main()
