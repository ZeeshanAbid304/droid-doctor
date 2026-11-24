#!/usr/bin/env python3
"""
droid-doctor: crash / ANR report parser.

Reads crash and ANR data from any of:
  - text pasted from Firebase Crashlytics, Play Console (Android vitals), logcat, bug reports
  - Crashlytics MCP tool output saved to a file (JSON)
  - Crashlytics BigQuery export (JSON / JSON lines with exceptions[].frames[])
  - CSV exports (any columns; stack-trace-looking cells are parsed, and count/user columns are used)

Groups them into issues (exception type + first app frame), marks ANRs, detects obfuscated
(R8/ProGuard) traces, and maps app frames to files in the project with a code snippet.

Usage:
    crash_parse.py <file> [<file> ...] --package com.example.app [--project .]
                   [--md qa-report/crashes/issues.md] [--json qa-report/crashes/issues.json]
    (use '-' to read stdin)
Standard library only.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from collections import OrderedDict

FRAME = re.compile(r"^\s*(?:at\s+)?([\w$.<>]+)\.([\w$<>-]+)\(([^)]*)\)\s*$")
EXC_LINE = re.compile(r"^\s*(?:Fatal Exception:\s*|FATAL EXCEPTION:.*?|Caused by:\s*|Non-fatal Exception:\s*)?"
                      r"((?:[a-z_][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable|Exception\$\w+)|"
                      r"[A-Z]\w*(?:Exception|Error))(?::\s*(.*))?$")
ANR_HINTS = re.compile(r"\bANR\b|Application Not Responding|Input dispatching timed out|"
                       r"executing service|Broadcast of Intent|did not then call Service\.startForeground|"
                       r"ContentProvider not responding|\"main\" (?:prio|tid)", re.I)
COUNT_COLS = re.compile(r"^(events?|crashes|count|occurrences|event count|total events|anrs?)$", re.I)
USER_COLS = re.compile(r"^(users?|affected users|impacted users|distinct users)$", re.I)


def flatten_json(obj, out):
    """Turn Crashlytics/BigQuery-like JSON into stack-trace text blocks."""
    if isinstance(obj, dict):
        exs = obj.get("exceptions") or obj.get("exception")
        if isinstance(exs, dict):
            exs = [exs]
        if isinstance(exs, list) and exs and isinstance(exs[0], dict):
            lines = []
            for i, ex in enumerate(exs):
                t = ex.get("type") or ex.get("exceptionType") or ex.get("title") or "Exception"
                msg = ex.get("exception_message") or ex.get("exceptionMessage") or ex.get("message") or ""
                lines.append(("Caused by: " if i else "Fatal Exception: ") + f"{t}: {msg}".rstrip(": "))
                for fr in ex.get("frames") or []:
                    sym = fr.get("symbol") or fr.get("method") or ""
                    fl = fr.get("file") or fr.get("fileName") or "Unknown Source"
                    ln = fr.get("line") or fr.get("lineNumber") or ""
                    lines.append(f"at {sym}({fl}{':' + str(ln) if ln else ''})")
            meta = {}
            for k in ("eventCount", "event_count", "events", "count"):
                if k in obj:
                    meta["events"] = obj[k]
            for k in ("impactedUsers", "userCount", "users", "affected_users"):
                if k in obj:
                    meta["users"] = obj[k]
            if obj.get("errorType") == "ANR" or obj.get("error_type") == "ANR" or obj.get("isAnr"):
                lines.insert(0, "ANR")
            out.append(("\n".join(lines), meta))
            return
        if "stacktrace" in obj or "stackTrace" in obj:
            st = obj.get("stacktrace") or obj.get("stackTrace")
            out.append((st if isinstance(st, str) else json.dumps(st), {
                "events": obj.get("eventCount") or obj.get("events"), "users": obj.get("impactedUsers") or obj.get("users")}))
            return
        for v in obj.values():
            flatten_json(v, out)
    elif isinstance(obj, list):
        for v in obj:
            flatten_json(v, out)
    elif isinstance(obj, str) and ("\tat " in obj or "\n at " in obj or "at " in obj and "Exception" in obj):
        out.append((obj, {}))


def load_blocks(paths):
    blocks = []
    for p in paths:
        raw = sys.stdin.read() if p == "-" else open(p, encoding="utf-8-sig", errors="replace").read()
        s = raw.strip()
        if s.startswith(("{", "[")):
            try:
                flatten_json(json.loads(s), blocks)
                continue
            except json.JSONDecodeError:
                pass
            jl = []
            for line in s.splitlines():
                try:
                    jl.append(json.loads(line))
                except json.JSONDecodeError:
                    jl = None
                    break
            if jl:
                flatten_json(jl, blocks)
                continue
        if p.lower().endswith((".csv", ".tsv")):
            try:
                dialect = csv.Sniffer().sniff(s[:4000], delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.reader(io.StringIO(s), dialect))
            if rows:
                head = [h.strip() for h in rows[0]]
                ci = next((i for i, h in enumerate(head) if COUNT_COLS.match(h)), None)
                ui = next((i for i, h in enumerate(head) if USER_COLS.match(h)), None)
                for r in rows[1:]:
                    text = "\n".join(c for c in r if re.search(r"Exception|Error|\bat\s|ANR", c))
                    if text:
                        meta = {}
                        if ci is not None and ci < len(r):
                            meta["events"] = r[ci]
                        if ui is not None and ui < len(r):
                            meta["users"] = r[ui]
                        blocks.append((text, meta))
                continue
        # plain text: split on crash starts
        parts = re.split(r"(?m)^(?=.*(?:FATAL EXCEPTION|Fatal Exception:|Non-fatal Exception:|^ANR in |"
                         r"Application Not Responding|^-{3,}\s*pid\s+\d+))", raw)
        for part in parts:
            if part.strip() and (re.search(r"Exception|Error", part) or ANR_HINTS.search(part)):
                blocks.append((part, {}))
    return blocks


def parse_block(text, pkg):
    lines = [re.sub(r"^.*?(AndroidRuntime|CrashlyticsCore|System\.err)[^:]*:\s?", "", ln) for ln in text.splitlines()]
    exc = msg = None
    causes = []
    frames = []
    for ln in lines:
        m = EXC_LINE.match(ln.strip())
        if m and not FRAME.match(ln):
            if exc is None:
                exc, msg = m.group(1), (m.group(2) or "").strip()
            else:
                causes.append(f"{m.group(1)}: {(m.group(2) or '').strip()}".rstrip(": "))
            continue
        fm = FRAME.match(ln)
        if fm:
            frames.append({"cls": fm.group(1), "method": fm.group(2), "loc": fm.group(3)})
    head = text[:600]
    explicit = re.search(r"(?i)\bANR\b|Application Not Responding|Input dispatching timed out|"
                         r"ContentProvider not responding|executing service|Broadcast of Intent", head)
    is_anr = bool(explicit) if exc else bool(ANR_HINTS.search(text))
    if is_anr and not exc:
        exc = "ANR"
        m = re.search(r"(Input dispatching timed out[^\n]*|executing service[^\n]*|Broadcast of Intent[^\n]*|"
                      r"did not then call Service\.startForeground[^\n]*|ContentProvider not responding[^\n]*)", text)
        msg = m.group(1).strip() if m else "Application Not Responding"
    if not exc and not frames:
        return None
    app_frames = [f for f in frames if pkg and f["cls"].startswith(pkg)]
    obf = sum(1 for f in frames if re.fullmatch(r"([a-z]{1,2}\.){1,4}[a-zA-Z]{1,2}", f["cls"])
              or "Unknown Source" in f["loc"] or "SourceFile" in f["loc"])
    root = causes[-1] if causes else None
    return {"type": "ANR" if is_anr else "Crash", "exception": exc or "Unknown", "message": (msg or "")[:300],
            "root_cause": root, "frames": frames[:40], "app_frames": app_frames[:10],
            "obfuscated": obf >= max(3, len(frames) // 2) if frames else False}


def signature(it):
    top = it["app_frames"][0] if it["app_frames"] else (it["frames"][0] if it["frames"] else None)
    where = f"{top['cls']}.{top['method']}" if top else "?"
    return f"{it['type']}|{it['exception']}|{where}"


def to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def index_project(project):
    idx = {}
    if not project:
        return idx
    for dp, dn, fn in os.walk(project):
        dn[:] = [d for d in dn if d not in ("build", ".gradle", ".git", ".idea")]
        for f in fn:
            if f.endswith((".kt", ".java")):
                idx.setdefault(f, []).append(os.path.join(dp, f))
    return idx


def locate(frame, idx, project):
    m = re.match(r"([\w$]+\.(?:kt|java)):(\d+)", frame["loc"])
    if not m:
        return None
    fname, line = m.group(1), int(m.group(2))
    cands = idx.get(fname, [])
    if not cands:
        return None
    pkg_path = "/".join(frame["cls"].split(".")[:-1])
    best = next((c for c in cands if pkg_path and pkg_path in c.replace("\\", "/")), cands[0])
    try:
        src = open(best, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        src = []
    snip = "\n".join(f"{i:>5}{'>' if i == line else ' '} {src[i - 1]}"
                     for i in range(max(1, line - 2), min(len(src), line + 2) + 1)) if src else ""
    return {"file": os.path.relpath(best, project), "line": line, "snippet": snip}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--package", "-p", default="", help="app package prefix, e.g. com.example.app")
    ap.add_argument("--project", default="")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args()

    blocks = load_blocks(a.files)
    issues = OrderedDict()
    for text, meta in blocks:
        it = parse_block(text, a.package)
        if not it:
            continue
        sig = signature(it)
        cur = issues.get(sig)
        ev = to_int(meta.get("events")) if meta else None
        us = to_int(meta.get("users")) if meta else None
        if cur:
            cur["occurrences"] += 1
            cur["events"] = (cur["events"] or 0) + (ev or 0) if ev else cur["events"]
            cur["users"] = max(cur["users"] or 0, us or 0) or None
        else:
            it.update(occurrences=1, events=ev, users=us, signature=sig)
            issues[sig] = it
    idx = index_project(a.project)
    items = list(issues.values())
    for it in items:
        it["locations"] = [loc for loc in (locate(f, idx, a.project) for f in it["app_frames"][:3]) if loc]
    items.sort(key=lambda x: (-(x["events"] or 0), -x["occurrences"]))

    L = ["# Crash / ANR issues", "",
         f"Parsed {len(blocks)} report block(s) into **{len(items)} unique issue(s)**: "
         f"{sum(1 for i in items if i['type'] == 'Crash')} crash, {sum(1 for i in items if i['type'] == 'ANR')} ANR.", ""]
    if any(i["obfuscated"] for i in items):
        L += ["> **Obfuscated stack traces found.** Retrace them with the release `mapping.txt` "
              "(app/build/outputs/mapping/release/mapping.txt) before fixing: "
              "`retrace mapping.txt stacktrace.txt` (Android SDK cmdline-tools), or upload the mapping file to Crashlytics.", ""]
    for n, it in enumerate(items, 1):
        cnt = []
        if it["events"]:
            cnt.append(f"{it['events']:,} events")
        if it["users"]:
            cnt.append(f"{it['users']:,} users")
        cnt.append(f"{it['occurrences']} sample(s)")
        L.append(f"## {n}. [{it['type']}] {it['exception']}" + (f": {it['message'][:120]}" if it["message"] else ""))
        L.append(f"- Volume: {', '.join(cnt)}")
        if it["root_cause"]:
            L.append(f"- Root cause (last 'Caused by'): {it['root_cause'][:200]}")
        if it["app_frames"]:
            L.append("- App frames: " + "; ".join(f"`{f['cls']}.{f['method']}({f['loc']})`" for f in it["app_frames"][:4]))
        elif it["frames"]:
            L.append("- No app frames (crash inside a library/system). Top frames: "
                     + "; ".join(f"`{f['cls']}.{f['method']}`" for f in it["frames"][:3]))
        if it["obfuscated"]:
            L.append("- Obfuscated: retrace first")
        for loc in it["locations"]:
            L.append(f"- Code: `{loc['file']}:{loc['line']}`")
            if loc["snippet"]:
                L += ["```", loc["snippet"], "```"]
        L.append("")
    md = "\n".join(L)
    for target, data in ((a.md, md), (a.json, json.dumps(items, indent=2, default=str))):
        if target:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(data)
    print(md)


if __name__ == "__main__":
    main()
