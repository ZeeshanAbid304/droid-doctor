#!/usr/bin/env python3
"""
droid-doctor: ads show-rate analyzer.

Show rate = impressions / matched requests (AdMob definition).

Mode 1: AdMob report export (CSV/TSV, also Google Sheets download or a table
        pasted into a .txt file)
    showrate.py report.csv [more.csv] [--threshold 70] [--project .] [--md out.md] [--json out.json]

    Needs columns for the ad unit plus Matched requests and Impressions (or a
    Show rate column). Optional: Ad unit ID, Format, App, Requests, Date.
    Rows for the same ad unit (e.g. one per day) are summed.

Mode 2: local show rate from the debug logger the fixer adds (logcat lines)
    showrate.py --logcat qa-report/device/logcat.txt [--threshold 70]

    Expects lines containing:  QA_ADS event=<request|loaded|failed|shown|impression> unit=<name> format=<fmt>

Standard library only.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict

COLS = {
    "unit": [r"^ad unit$", r"^ad unit name$", r"^ad_unit$", r"^adunit$", r"^ad unit \(name\)$", r"^ad unit"],
    "unit_id": [r"ad unit id", r"^ad_unit_id$", r"^unit id$"],
    "format": [r"^format$", r"ad format"],
    "app": [r"^app$", r"^app name$", r"^application$"],
    "requests": [r"^ad requests$", r"^requests$"],
    "matched": [r"matched requests", r"^matched$"],
    "impressions": [r"^impressions$", r"^ad impressions$"],
    "show_rate": [r"show rate"],
    "match_rate": [r"match rate"],
    "earnings": [r"estimated earnings", r"^earnings", r"^revenue"],
}
UNIT_ID_RE = re.compile(r"ca-app-pub-\d{16}/\d{10}")


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace("\u00a0", "").replace(" ", "")
    if s in ("", "-", "--", "N/A", "n/a"):
        return None
    s = re.sub(r"[^\d.,%-]", "", s)
    pct = s.endswith("%")
    s = s.rstrip("%")
    if s.count(",") and s.count("."):
        s = s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[1]) != 3:
        s = s.replace(",", ".")  # 65,4 -> 65.4
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def read_table(path):
    raw = open(path, encoding="utf-8-sig", errors="replace").read()
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    # markdown table pasted?
    if sum(1 for ln in lines if ln.strip().startswith("|")) >= 2:
        rows = []
        for ln in lines:
            if not ln.strip().startswith("|") or re.fullmatch(r"\|[\s:\-|]+\|?", ln.strip()):
                continue
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
        return rows
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    return list(csv.reader(io.StringIO("\n".join(lines)), dialect))


def find_header(rows):
    for i, r in enumerate(rows[:30]):
        low = [c.strip().lower() for c in r]
        if any("matched" in c for c in low) or any("show rate" in c for c in low):
            return i
    return None


def map_cols(header):
    out = {}
    low = [h.strip().lower() for h in header]
    for key, pats in COLS.items():
        for pat in pats:
            for i, h in enumerate(low):
                if i in out.values():
                    continue
                if re.search(pat, h):
                    out[key] = i
                    break
            if key in out:
                break
    return out


def load_reports(paths):
    units = defaultdict(lambda: {"requests": 0.0, "matched": 0.0, "impressions": 0.0, "earnings": 0.0,
                                 "show_rates": [], "unit_id": "", "format": "", "app": "", "rows": 0})
    for p in paths:
        rows = read_table(p)
        hi = find_header(rows)
        if hi is None:
            sys.exit(f"{p}: could not find a header with 'Matched requests' or 'Show rate'. "
                     "Export the AdMob report with the Ad unit dimension and the Matched requests, Impressions "
                     "(and Show rate) metrics.")
        cols = map_cols(rows[hi])
        if "unit" not in cols and "unit_id" not in cols:
            sys.exit(f"{p}: no 'Ad unit' column. Add the Ad unit dimension to the report.")
        for r in rows[hi + 1:]:
            if not r or all(not c.strip() for c in r):
                continue
            get = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None
            name = (get("unit") or get("unit_id") or "").strip()
            if not name or name.lower() in ("total", "totals", "grand total"):
                continue
            u = units[name]
            u["rows"] += 1
            for k in ("requests", "matched", "impressions", "earnings"):
                v = num(get(k))
                if v is not None:
                    u[k] += v
            sr = num(get("show_rate"))
            if sr is not None:
                u["show_rates"].append(sr if sr > 1 else sr * 100)
            uid = get("unit_id") or ""
            m = UNIT_ID_RE.search(uid) or UNIT_ID_RE.search(name)
            if m:
                u["unit_id"] = m.group(0)
            u["format"] = u["format"] or (get("format") or "").strip()
            u["app"] = u["app"] or (get("app") or "").strip()
    result = []
    for name, u in units.items():
        if u["matched"] > 0:
            show = u["impressions"] / u["matched"] * 100
            src = "impressions / matched"
        elif u["show_rates"]:
            show = sum(u["show_rates"]) / len(u["show_rates"])
            src = "report show rate (avg)"
        else:
            show, src = None, "no data"
        match = (u["matched"] / u["requests"] * 100) if u["requests"] else None
        wasted = max(0.0, u["matched"] - u["impressions"]) if u["matched"] else None
        result.append({"unit": name, "unit_id": u["unit_id"], "format": u["format"], "app": u["app"],
                       "requests": u["requests"], "matched": u["matched"], "impressions": u["impressions"],
                       "show_rate": show, "match_rate": match, "wasted_matched": wasted,
                       "earnings": u["earnings"], "source": src})
    result.sort(key=lambda x: (x["show_rate"] is None, x["show_rate"] if x["show_rate"] is not None else 0))
    return result


def code_locations(project, unit):
    """Find where an ad unit is referenced: by ID, else by name-derived identifiers."""
    if not project or not os.path.isdir(project):
        return []
    needles = []
    if unit.get("unit_id"):
        needles.append(unit["unit_id"])
        needles.append(unit["unit_id"].split("/")[-1])
    words = [w for w in re.split(r"[^A-Za-z0-9]+", unit["unit"]) if len(w) > 1]
    if words:
        needles.append("_".join(words).lower())
        needles.append("".join(words).lower())
    hits = []
    for dp, dn, fn in os.walk(project):
        dn[:] = [d for d in dn if d not in ("build", ".gradle", ".git", ".idea", "node_modules")]
        for f in fn:
            if not f.endswith((".kt", ".java", ".xml", ".kts", ".gradle", ".properties", ".json")):
                continue
            path = os.path.join(dp, f)
            try:
                lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines, 1):
                low = ln.lower().replace("-", "_")
                if any(n and n.lower() in (ln if n.startswith("ca-app") or n.isdigit() else low) for n in needles):
                    hits.append(f"{os.path.relpath(path, project)}:{i}")
                    if len(hits) >= 8:
                        return hits
    return hits


def fmt(v, pct=False):
    if v is None:
        return "-"
    return f"{v:.1f}%" if pct else f"{v:,.0f}"


def report_md(units, threshold, project):
    low = [u for u in units if u["show_rate"] is not None and u["show_rate"] < threshold]
    L = ["# Ads show rate", "",
         f"Show rate = impressions / matched requests. Threshold: **{threshold:.0f}%**. "
         f"Units below threshold: **{len(low)} of {len(units)}**.", "",
         "| Ad unit | Format | Matched | Impressions | Show rate | Match rate | Wasted matched | Status |",
         "|---|---|---|---|---|---|---|---|"]
    for u in units:
        status = "LOW" if u in low else ("ok" if u["show_rate"] is not None else "no data")
        L.append(f"| {u['unit']} | {u['format'] or '-'} | {fmt(u['matched'])} | {fmt(u['impressions'])} | "
                 f"{fmt(u['show_rate'], True)} | {fmt(u['match_rate'], True)} | {fmt(u['wasted_matched'])} | {status} |")
    if low:
        L += ["", "## Units to fix (lowest first)", ""]
        for u in low:
            locs = code_locations(project, u) if project else []
            L.append(f"### {u['unit']} — {fmt(u['show_rate'], True)}")
            L.append(f"- Format: {u['format'] or 'unknown'}; unit id: {u['unit_id'] or 'not in report'}")
            L.append(f"- {fmt(u['wasted_matched'])} matched ads were never shown")
            L.append("- Code references: " + (", ".join(f"`{x}`" for x in locs) if locs else
                                              "not found automatically (search for how this unit's ID is loaded)"))
            L.append("")
    return "\n".join(L), low


def logcat_mode(path, threshold):
    ev = defaultdict(lambda: defaultdict(int))
    fmt_of = {}
    for ln in open(path, encoding="utf-8", errors="replace"):
        if "QA_ADS" not in ln:
            continue
        e = re.search(r"event=(\w+)", ln)
        u = re.search(r"unit=([^\s]+)", ln)
        f = re.search(r"format=([^\s]+)", ln)
        if e and u:
            ev[u.group(1)][e.group(1)] += 1
            if f:
                fmt_of[u.group(1)] = f.group(1)
    if not ev:
        sys.exit("No QA_ADS lines found. Add the debug ad logger (see fix patterns) and run the app first.")
    L = ["# Local ad show rate (this test session)", "",
         "| Ad unit | Format | Requests | Loaded | Failed | Shown | Impressions | Show rate | Status |",
         "|---|---|---|---|---|---|---|---|---|"]
    for unit, c in sorted(ev.items()):
        loaded = c["loaded"]
        imp = c["impression"] or c["shown"]
        sr = imp / loaded * 100 if loaded else None
        status = "LOW" if sr is not None and sr < threshold else ("ok" if sr is not None else "-")
        L.append(f"| {unit} | {fmt_of.get(unit, '-')} | {c['request']} | {loaded} | {c['failed']} | {c['shown']} | "
                 f"{c['impression']} | {fmt(sr, True)} | {status} |")
    L += ["", "Notes: loaded-but-never-shown ads are what lowers show rate. A unit with many 'request' and few "
               "'loaded' has a match/fill problem instead (not a code bug)."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="*")
    ap.add_argument("--threshold", type=float, default=70.0)
    ap.add_argument("--project", default="")
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--logcat")
    a = ap.parse_args()
    if a.logcat:
        md = logcat_mode(a.logcat, a.threshold)
    else:
        if not a.reports:
            ap.error("give an AdMob report file, or --logcat")
        units = load_reports(a.reports)
        md, low = report_md(units, a.threshold, a.project)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"threshold": a.threshold, "units": units,
                           "low": [u["unit"] for u in low]}, fh, indent=2)
    if a.md:
        os.makedirs(os.path.dirname(os.path.abspath(a.md)), exist_ok=True)
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    print(md)


if __name__ == "__main__":
    main()
