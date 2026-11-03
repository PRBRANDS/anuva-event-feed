#!/usr/bin/env python3
"""Import Ticketmaster event candidates and their API-provided event images.

Event details remain unverified for Anuva users to confirm. Images are used
only when supplied by the Ticketmaster Discovery API, with source attribution.
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
ENDPOINT = "https://app.ticketmaster.com/discovery/v2/events.json"
USER_AGENT = "AnuvaEventFeed/1.0"
MAX_PAGES = 5
PAGE_SIZE = 200


def fetch_page(api_key, page):
    params = {
        "apikey": api_key,
        "latlong": "38.9072,-77.0369",
        "countryCode": "US",
        "radius": "50",
        "unit": "miles",
        "startDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sort": "date,asc",
        "size": PAGE_SIZE,
        "page": page,
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def price_label(event):
    ranges = event.get("priceRanges") or []
    if not ranges:
        return "Check organizer for price"
    item = ranges[0]
    currency = item.get("currency") or "USD"
    symbol = "$" if currency == "USD" else currency + " "
    low, high = item.get("min"), item.get("max")
    if low is None and high is None:
        return "Check organizer for price"
    if low is None:
        return "Up to " + symbol + str(high)
    if high is None or high == low:
        return symbol + str(low)
    return symbol + str(low) + "–" + symbol + str(high)


def ticketmaster_image(item):
    """Choose a real event image, preferring wide, non-fallback artwork."""
    images = [
        image for image in (item.get("images") or [])
        if isinstance(image, dict)
        and str(image.get("url", "")).startswith("https://")
        and not image.get("fallback", False)
    ]
    if not images:
        return None
    wide = [image for image in images if image.get("ratio") == "16_9"]
    pool = wide or images
    chosen = max(pool, key=lambda image: int(image.get("width") or 0) * int(image.get("height") or 0))
    return {
        "url": chosen["url"],
        "attribution": chosen.get("attribution") or "Image via Ticketmaster",
    }


def to_anuva_event(item):
    dates = item.get("dates", {}).get("start", {})
    local_date = dates.get("localDate")
    if not local_date:
        return None
    try:
        if date.fromisoformat(local_date) < date.today():
            return None
    except ValueError:
        return None

    venues = item.get("_embedded", {}).get("venues", [])
    venue = venues[0] if venues else {}
    city = venue.get("city", {}).get("name", "")
    state = venue.get("state", {}).get("stateCode", "")
    venue_name = venue.get("name", "")
    address = venue.get("address", {}).get("line1", "")
    location = ", ".join(x for x in [venue_name, address, city, state] if x)
    if not location:
        location = "Washington, DC area"

    classifications = item.get("classifications") or []
    category = "Local Events"
    if classifications:
        segment = classifications[0].get("segment", {})
        genre = classifications[0].get("genre", {})
        category = segment.get("name") or genre.get("name") or category

    start_time = dates.get("localTime", "")
    if start_time:
        start_time = start_time.rstrip("Z")
    end_date = dates.get("localDate")
    end_info = item.get("dates", {}).get("end", {})
    if end_info.get("localDate") and end_info["localDate"] >= local_date:
        end_date = end_info["localDate"]

    description = item.get("info") or item.get("pleaseNote") or "Event listing imported from Ticketmaster. Confirm the schedule, venue, price and availability with the organizer before making plans."
    if len(description) > 700:
        description = description[:697].rstrip() + "..."

    artwork = ticketmaster_image(item)
    event = {
        "id": "ticketmaster-" + str(item.get("id", "")),
        "title": item.get("name") or "Untitled event",
        "date": local_date,
        "time": start_time or "See organizer listing",
        "location": location,
        "category": category,
        "price": price_label(item),
        "description": description,
        "url": item.get("url") or "",
        "image": artwork["url"] if artwork else "",
        "imageAlt": (item.get("name") or "Event") + " event image",
        "status": "needs_review",
        "sourceName": "Ticketmaster",
        "sourceProvider": "Ticketmaster Discovery API",
        "verifiedAt": "",
        "imageSource": "Ticketmaster Discovery API" if artwork else "",
        "imageLicense": "Ticketmaster API content; subject to Ticketmaster Developer Terms" if artwork else "",
        "imageAttribution": artwork["attribution"] if artwork else "",
        "imagePermission": "approved" if artwork else "pending",
        "imageVerified": bool(artwork),
    }
    if end_date and end_date != local_date:
        event["endDate"] = end_date
    return event if event["url"].startswith("https://") else None


def identity(event):
    return (
        str(event.get("title", "")).strip().casefold(),
        str(event.get("date", "")),
        str(event.get("location", "")).strip().casefold(),
    )


def main():
    api_key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    if not api_key:
        print("ERROR: TICKETMASTER_API_KEY is not configured in GitHub Actions secrets.")
        sys.exit(1)

    data = json.loads(FEED.read_text(encoding="utf-8"))
    existing = data.get("events", [])
    today = date.today()
    # Expire only records imported by this integration; preserve manually curated listings.
    retained = []
    for event in existing:
        if event.get("sourceProvider") == "Ticketmaster":
            try:
                if date.fromisoformat(event.get("endDate") or event["date"]) < today:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
        retained.append(event)

    existing_ids = {event.get("id") for event in retained}
    existing_keys = {identity(event) for event in retained}
    imported = []
    pages_read = 0
    for page in range(MAX_PAGES):
        payload = fetch_page(api_key, page)
        pages_read += 1
        items = payload.get("_embedded", {}).get("events", [])
        for item in items:
            event = to_anuva_event(item)
            if not event:
                continue
            key = identity(event)
            if event["id"] in existing_ids or key in existing_keys:
                continue
            imported.append(event)
            existing_ids.add(event["id"])
            existing_keys.add(key)
        page_info = payload.get("page", {})
        if page + 1 >= page_info.get("totalPages", 1) or not items:
            break

    combined = retained + imported
    combined.sort(key=lambda e: (e.get("date", "9999-12-31"), e.get("title", "").casefold()))
    data["events"] = combined
    data["lastUpdated"] = today.isoformat()
    data["feedStatus"] = "mixed"
    data["automationNote"] = (
        "Ticketmaster Discovery API event candidates are imported automatically and remain needs_review. "
        "API-provided event images are displayed with source attribution; event details still require review. "
        "Expired Ticketmaster-imported listings are removed; manually curated listings are preserved."
    )
    FEED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Ticketmaster pages checked: {pages_read}")
    print(f"New unverified candidates added: {len(imported)}")
    print(f"Total feed listings: {len(combined)}")


if __name__ == "__main__":
    main()
