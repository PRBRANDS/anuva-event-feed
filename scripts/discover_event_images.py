#!/usr/bin/env python3
"""Discover official-page image candidates without granting reuse permission.

Candidates are saved as pending. The website must only display images whose
permission status has been explicitly approved.
"""
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "events.json"
UA = "AnuvaEventImageReviewBot/1.0 (+https://github.com/PRBRANDS/anuva-event-feed)"

class MetaImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        a = dict(attrs)
        key = (a.get("property") or a.get("name") or "").lower()
        content = (a.get("content") or "").strip()
        if key in ("og:image", "twitter:image") and content:
            self.images.append(content)

def discover(url):
    if not isinstance(url, str) or not url.startswith("https://"):
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if "text/html" not in response.headers.get("Content-Type", "").lower():
                return ""
            html = response.read(1_500_000).decode("utf-8", "replace")
            parser = MetaImages()
            parser.feed(html)
            for candidate in parser.images:
                if candidate.startswith("//"):
                    candidate = "https:" + candidate
                if candidate.startswith("https://") and re.match(r"^https://", candidate):
                    return candidate
    except Exception as exc:
        print(f"Could not inspect {url}: {exc}")
    return ""

data = json.loads(FEED.read_text(encoding="utf-8"))
changed = False
for event in data.get("events", []):
    event.setdefault("image", "")
    event.setdefault("imageSource", "")
    event.setdefault("imageLicense", "")
    event.setdefault("imageAttribution", "")
    event.setdefault("imagePermission", "pending")
    event.setdefault("imageVerified", False)
    if not event.get("image"):
        candidate = discover(event.get("url", ""))
        if candidate:
            event["imageCandidate"] = candidate
            event["imageCandidateSource"] = event.get("url", "")
            event["imageCandidateStatus"] = "pending_rights_review"
            print(f"Candidate found for: {event.get('title', event.get('id'))}")
            changed = True
if changed:
    FEED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
else:
    print("No new image candidates found.")
