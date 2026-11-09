#!/usr/bin/env python3
"""Import Ticketmaster event candidates and their API-provided event images.

Prioritizes free / low-cost events and DC-area listings for Anuva.
Event details remain unverified for users to confirm. Images are used
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
        "radius": "40",          # tighter DC + nearby focus
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

def is_likely_free(event):
    """Strict detection of genuinely free events."""
    price = str(event.get("price") or "").lower().strip()
    title = str(event.get("title") or "").lower()
    desc = str(event.get("description") or "").lower()

    # Clear free signals only
    if price in ("free", "free admission", "free entry", "free event"):
        return True
    if price.startswith("free ") or price.startswith("free,"):
        return True

    free_phrases = [
        "free admission", "free entry", "free and open to the public",
        "no charge", "no cost", "complimentary admission",
        "donation optional", "pay what you can", "suggested donation"
    ]
    if any(p in price or p in title or p in desc for p in free_phrases):
        return True

    # Strong rejection of common false positives
    reject = [
        "vip", "upsell", "package", "meet & greet", "meet and greet",
        "early entry", "laminate", "merch", "ticket required",
        "general admission", "ga ticket", "separate admission",
        "free throw", "free parking", "free wifi", "free drink"
    ]
    if any(r in title or r in desc for r in reject):
        return False

    # Reject anything that looks like a price range or paid amount
    if any(c in price for c in ["$", "–", "-", "to", "from"]) and "free" not in price:
        return False
    if price in ("$0.0", "$0.00", "0.0", "0.00", "check organizer for price"):
        return False

    return False
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


def is_likely_free(event):
    """Detect free or very low-cost events from price, title and description."""
    price = str(event.get("price") or "").lower()
    title = str(event.get("title") or "").lower()
    desc = str(event.get("description") or "").lower()
    free_words = [
        "free", "no charge", "complimentary", "open to the public",
        "donation optional", "pay what you can", "suggested donation"
    ]
    return any(w in price or w in title or w in desc for w in free_words)


def ticketmaster_image(item):
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

    # Free + DC priority
    event["isFree"] = is_likely_free(event)
    event["priority"] = 10 if event["isFree"] else 0
    loc_lower = location.lower()
    if any(x in loc_lower for x in ["washington", " dc", "district of columbia"]):
        event["priority"] += 4
    elif any(x in loc_lower for x in ["arlington", "alexandria", "silver spring", "bethesda", "takoma"]):
        event["priority"] += 2

        # Free + DC priority
    event["isFree"] = is_likely_free(event)
    event["priority"] = 10 if event["isFree"] else 0
    loc_lower = location.lower()
    if any(x in loc_lower for x in ["washington", " dc", "district of columbia"]):
        event["priority"] += 4
    elif any(x in loc_lower for x in ["arlington", "alexandria", "silver spring", "bethesda"]):
        event["priority"] += 2

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

    retained = []
    old_ticketmaster = {}
    for event in existing:
        if (
            event.get("sourceProvider") in ("Ticketmaster", "Ticketmaster Discovery API")
            or str(event.get("id", "")).startswith("ticketmaster-")
        ):
            try:
                if date.fromisoformat(event.get("endDate") or event["date"]) < today:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            old_ticketmaster[event.get("id")] = event
        else:
            retained.append(event)

    existing_ids = {event.get("id") for event in retained}
    existing_keys = {identity(event) for event in retained}
    refreshed_ticketmaster = {}
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
            event_id = event["id"]
            key = identity(event)
            if event_id in old_ticketmaster:
                refreshed_ticketmaster[event_id] = event
                continue
            if event_id in existing_ids or key in existing_keys:
                continue
            imported.append(event)
            existing_ids.add(event_id)
            existing_keys.add(key)
        page_info = payload.get("page", {})
        if page + 1 >= page_info.get("totalPages", 1) or not items:
            break

    ticketmaster_records = [
        refreshed_ticketmaster.get(event_id, old_event)
        for event_id, old_event in old_ticketmaster.items()
    ]
    combined = retained + ticketmaster_records + imported

    # Free + DC first, then by date
    combined.sort(key=lambda e: (-e.get("priority", 0), e.get("date", "9999-12-31"), e.get("title", "").casefold()))

    data["events"] = combined
    data["lastUpdated"] = today.isoformat()
    data["feedStatus"] = "mixed"
    data["automationNote"] = (
        "Ticketmaster Discovery API event candidates are imported automatically and remain needs_review. "
        "Free and DC-area events are prioritized. API-provided event images are displayed with source attribution. "
        "Expired Ticketmaster-imported listings are removed; manually curated listings are preserved."
    )
    FEED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    free_count = sum(1 for e in combined if e.get("isFree"))
    print(f"Ticketmaster pages checked: {pages_read}")
    print(f"Existing Ticketmaster listings refreshed: {len(refreshed_ticketmaster)}")
    print(f"New unverified candidates added: {len(imported)}")
    print(f"Free / low-cost events detected: {free_count}")
    print(f"Total feed listings: {len(combined)}")


if __name__ == "__main__":
    main()
