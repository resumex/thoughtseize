#!/usr/bin/env python3
"""Find best printing for each card based on budget/bling preferences.

Usage:
    python3 .claude/scripts/best_printing.py "Card 1" "Card 2" ...

Selection logic:
1. Filter to non-foil printings (must have 'nonfoil' in finishes)
2. Among those with a USD price, find cheapest
3. If a full_art or borderless printing is within $2 of cheapest, prefer it
4. Output JSON with selected printing for each card

Rate limits: 0.15s between requests, 2s between batches of 20.
"""

import json
import subprocess
import sys
import time
from urllib.parse import quote

API_BASE = "https://api.scryfall.com"
RATE_LIMIT_DELAY = 0.15
BATCH_DELAY = 2.0
BATCH_SIZE = 20
RATE_LIMIT_WAIT = 60


def fetch(url):
    result = subprocess.run(
        ["curl", "-s", url],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return {"object": "error", "details": f"curl failed: {result.stderr}"}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"object": "error", "details": "Invalid JSON response"}
    if data.get("status") == 429:
        time.sleep(RATE_LIMIT_WAIT)
        return fetch(url)
    return data


def encode_name(name):
    return name.replace(" ", "+").replace("'", "%27")


def get_printings(name):
    encoded = encode_name(name)
    url = f"{API_BASE}/cards/named?fuzzy={encoded}"
    data = fetch(url)
    if data.get("object") == "error":
        return None, data.get("details", "Not found")
    prints_uri = data.get("prints_search_uri")
    if not prints_uri:
        return [data], None
    results = []
    time.sleep(RATE_LIMIT_DELAY)
    while prints_uri:
        pdata = fetch(prints_uri)
        if pdata.get("object") == "error":
            break
        for card in pdata.get("data", []):
            results.append(card)
        if pdata.get("has_more") and pdata.get("next_page"):
            time.sleep(RATE_LIMIT_DELAY)
            prints_uri = pdata["next_page"]
        else:
            prints_uri = None
    return results, None


def select_best(printings):
    """Select best printing: cheapest non-foil, prefer full-art/borderless within $2."""
    # Filter to non-foil printings with a USD price
    candidates = []
    for p in printings:
        finishes = p.get("finishes", [])
        # Must be available in nonfoil
        if "nonfoil" not in finishes:
            continue
        price_str = p.get("prices", {}).get("usd")
        if not price_str:
            continue
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            continue
        candidates.append({
            "name": p.get("name", ""),
            "set": p.get("set", ""),
            "set_name": p.get("set_name", ""),
            "collector_number": p.get("collector_number", ""),
            "price": price,
            "full_art": p.get("full_art", False),
            "border_color": p.get("border_color", ""),
            "frame_effects": p.get("frame_effects", []),
            "promo_types": p.get("promo_types", []),
        })

    if not candidates:
        # Fallback: try etched or any finish
        for p in printings:
            price_str = p.get("prices", {}).get("usd") or p.get("prices", {}).get("usd_etched")
            if not price_str:
                continue
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                continue
            candidates.append({
                "name": p.get("name", ""),
                "set": p.get("set", ""),
                "set_name": p.get("set_name", ""),
                "collector_number": p.get("collector_number", ""),
                "price": price,
                "full_art": p.get("full_art", False),
                "border_color": p.get("border_color", ""),
                "frame_effects": p.get("frame_effects", []),
                "promo_types": p.get("promo_types", []),
            })

    if not candidates:
        return None

    # Sort by price
    candidates.sort(key=lambda x: x["price"])
    cheapest = candidates[0]

    # Look for bling within $2 of cheapest
    bling_threshold = cheapest["price"] + 2.0
    bling_candidates = []
    for c in candidates:
        if c["price"] > bling_threshold:
            break
        is_bling = (
            c["full_art"]
            or c["border_color"] == "borderless"
            or "extendedart" in c.get("frame_effects", [])
            or "showcase" in c.get("frame_effects", [])
        )
        if is_bling:
            bling_candidates.append(c)

    if bling_candidates:
        # Pick cheapest bling option
        return bling_candidates[0]
    return cheapest


def main():
    cards = sys.argv[1:]
    if not cards:
        print(json.dumps({"error": "Provide card names as arguments"}))
        sys.exit(1)

    results = []
    for i, name in enumerate(cards):
        if i > 0:
            delay = BATCH_DELAY if i % BATCH_SIZE == 0 else RATE_LIMIT_DELAY
            time.sleep(delay)

        printings, error = get_printings(name)
        if error or not printings:
            results.append({"name": name, "error": error or "No printings found"})
            sys.stderr.write(f"[{i+1}/{len(cards)}] {name}: ERROR - {error}\n")
            continue

        best = select_best(printings)
        if best:
            results.append(best)
            sys.stderr.write(f"[{i+1}/{len(cards)}] {name}: {best['set']} #{best['collector_number']} ${best['price']:.2f}\n")
        else:
            results.append({"name": name, "error": "No valid printing found"})
            sys.stderr.write(f"[{i+1}/{len(cards)}] {name}: NO VALID PRINTING\n")

    # Summary
    total = sum(r.get("price", 0) for r in results if "price" in r)
    sys.stderr.write(f"\nTotal: ${total:.2f}\n")

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
