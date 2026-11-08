#!/usr/bin/env python3
"""Import free and low-cost Eventbrite events around Washington DC for Anuva.
Improved version with better error reporting.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "events.json"
USER_AGENT = "AnuvaEventFeed/1.0"
ENDPOINT = "https://www.eventbriteapi.com/v3/events/search/"

LAT = "38.9072"
LON = "-77.0369"
RADIUS = "40mi"


def fetch_events(api_key, page=1):
    params = {
        "location.latitude": LAT,
        "location.longitude": LON,
        "location.within": RADIUS,
        "start_date.range_start": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sort_by": "date",
        "expand": "venue,category",
        "page": page,
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            print(f"Page {page} status: OK")
            print(f"Events returned on this page: {len(data.get('events') or [])}")
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP Error {e.code}: {body[:500]}")
        raise
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        raise


def to_anuva_event(item):
    name = item.get("name", {}).get("text") or "Untitled free event"
    start = item.get("start", {})
    local_date = (start.get("local") or "")[:10]
    if not local_date:
        return None
    try:
        if date.fromisoformat(local_date) < date.today():
            return None
    except ValueError:
        return None

    # Only keep free or very low cost
    is_free = item.get("is_free", False)
    if not is_free:
        return None

    venue = item.get("venue") or {}
    address = venue.get("address") or {}
    location_parts = [
        venue.get("name"),
        address.get("localized_address_display") or address.get("address_1"),
        address.get("city"),
        address.get("region"),
    ]
    location = ", ".join(p for p in location_parts if p) or "Washington, DC area"

    description = (item.get("description") or {}).get("text") or "Free event. Confirm details with the organizer."
    if len(description) > 700:
        description = description[:697].rstrip() + "..."

    category = "Local Events"
    cats = item.get("category") or {}
    if cats.get("name"):
        category = cats["name"]

    event = {
        "id": "eventbrite-" + str(item.get("id", "")),
        "title": name,
        "date": local_date,
        "time": (start.get("local") or "")[11:16] or "See organizer listing",
        "location": location,
        "category": category,
        "price": "Free",
        "description": description,
        "url": item.get("url") or "",
        "image": "",
        "imageAlt": name + " event image",
        "status": "needs_review",
        "sourceName": "Eventbrite",
        "sourceProvider": "Eventbrite API",
        "verifiedAt": "",
        "imageSource": "",
        "imageLicense": "",
        "imageAttribution": "",
        "imagePermission": "pending",
        "imageVerified": False,
        "isFree": True,
        "priority": 15,
    }

    loc_lower = location.lower()
    if any(x in loc_lower for x in ["washington", " dc", "district of columbia"]):
        event["priority"] += 3

    return event if event["url"].startswith("https://") else None


def identity(event):
    return (
        str(event.get("title", "")).strip().casefold(),
        str(event.get("date", "")),
        str(event.get("location", "")).strip().casefold(),
    )


def main():
    api_key = os.environ.get("EVENTBRITE_API_KEY", "").strip()
    if not api_key:
        print("ERROR: EVENTBRITE_API_KEY is not configured.")
        sys.exit(1)

    print("Starting Eventbrite free events import...")
    data = json.loads(FEED.read_text(encoding="utf-8"))
    existing = data.get("events", [])
    today = date.today()

    retained = []
    old_eventbrite = {}
    for event in existing:
        if str(event.get("id", "")).startswith("eventbrite-") or event.get("sourceProvider") == "Eventbrite API":
            try:
                if date.fromisoformat(event.get("endDate") or event["date"]) < today:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            old_eventbrite[event.get("id")] = event
        else:
            retained.append(event)

    existing_ids = {e.get("id") for e in retained}
    existing_keys = {identity(e) for e in retained}
    imported = []
    pages_read = 0

    for page in range(1, 4):
        try:
            payload = fetch_events(api_key, page)
        except Exception:
            break
        pages_read += 1
        items = payload.get("events") or []
        for item in items:
            event = to_anuva_event(item)
            if not event:
                continue
            eid = event["id"]
            key = identity(event)
            if eid in existing_ids or key in existing_keys or eid in old_eventbrite:
                continue
            imported.append(event)
            existing_ids.add(eid)
            existing_keys.add(key)

        pagination = payload.get("pagination") or {}
        if not pagination.get("has_more_items"):
            break

    combined = retained + list(old_eventbrite.values()) + imported
    combined.sort(key=lambda e: (-e.get("priority", 0), e.get("date", "9999-12-31"), e.get("title", "").casefold()))

    data["events"] = combined
    data["lastUpdated"] = today.isoformat()
    data["feedStatus"] = "mixed"
    data["automationNote"] = (
        "Free Eventbrite events are imported automatically and prioritized. "
        "Ticketmaster candidates remain needs_review. "
        "Expired listings are removed; manually curated listings are preserved."
    )
    FEED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Eventbrite pages checked: {pages_read}")
    print(f"New free events added: {len(imported)}")
    print(f"Total feed listings: {len(combined)}")


if __name__ == "__main__":
    main()
