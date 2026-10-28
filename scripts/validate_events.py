#!/usr/bin/env python3
"""Validate Anuva's public event feed and report organizer-link reachability."""
import json, os, sys, urllib.request, urllib.error
from datetime import date
from pathlib import Path

FEED = Path("events.json")
REPORT = Path("maintenance-report.md")
errors, warnings = [], []
try:
    data = json.loads(FEED.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"ERROR: events.json is not valid JSON: {exc}")
    sys.exit(1)

if not isinstance(data.get("events"), list):
    errors.append("Top-level 'events' must be an array.")
events = data.get("events", [])
required = ("id", "title", "date", "location", "category", "price", "description", "url", "status", "sourceName")
seen = set()
today = date.today()
for i, e in enumerate(events):
    where = f"events[{i}]"
    if not isinstance(e, dict):
        errors.append(f"{where} must be an object.")
        continue
    for key in required:
        if not e.get(key):
            errors.append(f"{where} missing required field: {key}")
    eid = e.get("id")
    if eid in seen:
        errors.append(f"Duplicate event id: {eid}")
    if eid:
        seen.add(eid)
    try:
        start = date.fromisoformat(e["date"])
        end = date.fromisoformat(e.get("endDate") or e["date"])
        if end < start:
            errors.append(f"{eid}: endDate is earlier than date.")
        if end < today:
            warnings.append(f"Expired listing: {e.get('title')} (ended {end.isoformat()})")
    except (KeyError, TypeError, ValueError):
        errors.append(f"{where} has invalid ISO date/endDate.")
    url = e.get("url", "")
    if not isinstance(url, str) or not url.startswith("https://"):
        errors.append(f"{eid or where}: URL must start with https://")
    elif os.getenv("CHECK_LINKS", "true").lower() == "true":
        req = urllib.request.Request(url, headers={"User-Agent":"AnuvaEventFeedValidator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status >= 400:
                    warnings.append(f"Link returned HTTP {response.status}: {url}")
        except Exception as exc:
            warnings.append(f"Could not confirm link (not proof it's broken): {url} — {exc}")

lines = [
    "# Anuva event-feed maintenance report",
    "",
    f"- Run date: {today.isoformat()}",
    f"- Events in feed: {len(events)}",
    f"- Result: {'FAILED' if errors else 'PASSED'}",
    "",
    "## Errors",
]
lines += [f"- {x}" for x in errors] or ["- None"]
lines += ["", "## Warnings (review manually; link checks do not verify event details)"]
lines += [f"- {x}" for x in warnings] or ["- None"]
REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
if errors:
    sys.exit(1)
