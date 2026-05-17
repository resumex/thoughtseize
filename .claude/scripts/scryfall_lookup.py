#!/usr/bin/env python3
"""Scryfall API batch lookup utility.

Usage:
    python3 .claude/scripts/scryfall_lookup.py named "Card Name 1" "Card Name 2" ...
    python3 .claude/scripts/scryfall_lookup.py search "scryfall query string" [--limit N] [--max-price N]
    python3 .claude/scripts/scryfall_lookup.py set_card SET collector_number
    python3 .claude/scripts/scryfall_lookup.py cheapest "Card 1" "Card 2" ...
    python3 .claude/scripts/scryfall_lookup.py printings "Card Name"

    Pipe syntax (for queries with special chars):
    echo "query" | python3 .claude/scripts/scryfall_lookup.py search [--limit N] [--max-price N]

Options:
    --limit N       Max results to return (default: 30 for search)
    --max-price N   Exclude cards with USD price above N

Outputs JSON to stdout. Respects Scryfall rate limits.
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


def extract_card(c):
    if c.get("object") == "error":
        return {"error": c.get("details", "Not found")}
    return {
        "name": c.get("name", ""),
        "mana_cost": c.get("mana_cost", ""),
        "cmc": c.get("cmc", 0),
        "type_line": c.get("type_line", ""),
        "oracle_text": c.get("oracle_text", ""),
        "color_identity": c.get("color_identity", []),
        "legalities": c.get("legalities", {}),
        "set": c.get("set", ""),
        "collector_number": c.get("collector_number", ""),
        "prices": c.get("prices", {}),
        "keywords": c.get("keywords", []),
        "power": c.get("power"),
        "toughness": c.get("toughness"),
    }


def lookup_named(names):
    results = []
    for i, name in enumerate(names):
        if i > 0:
            delay = BATCH_DELAY if i % BATCH_SIZE == 0 else RATE_LIMIT_DELAY
            time.sleep(delay)
        encoded = encode_name(name)
        url = f"{API_BASE}/cards/named?fuzzy={encoded}"
        data = fetch(url)
        results.append(extract_card(data))
    return results


def search(query, limit=30, max_price=None):
    results = []
    encoded = quote(query)
    url = f"{API_BASE}/cards/search?q={encoded}"
    while url:
        data = fetch(url)
        if data.get("object") == "error":
            return [{"error": data.get("details", "Search failed")}]
        for card in data.get("data", []):
            if max_price is not None:
                price_str = card.get("prices", {}).get("usd")
                if price_str and float(price_str) > max_price:
                    continue
            results.append(extract_card(card))
            if limit and len(results) >= limit:
                return results
        if data.get("has_more") and data.get("next_page"):
            time.sleep(RATE_LIMIT_DELAY)
            url = data["next_page"]
        else:
            url = None
    return results


def set_card(set_code, collector_number):
    url = f"{API_BASE}/cards/{set_code}/{collector_number}"
    data = fetch(url)
    return extract_card(data)


def cheapest(names):
    """Return cheapest printing info from /cards/named (no printings lookup needed)."""
    results = []
    for i, name in enumerate(names):
        if i > 0:
            delay = BATCH_DELAY if i % BATCH_SIZE == 0 else RATE_LIMIT_DELAY
            time.sleep(delay)
        encoded = encode_name(name)
        url = f"{API_BASE}/cards/named?fuzzy={encoded}"
        data = fetch(url)
        if data.get("object") == "error":
            results.append({"name": name, "error": data.get("details", "Not found")})
            sys.stderr.write(f"[{i+1}/{len(names)}] {name}: ERROR\n")
            continue
        price_str = data.get("prices", {}).get("usd") or data.get("prices", {}).get("usd_foil") or "0"
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            price = 0
        entry = {
            "name": data.get("name", ""),
            "set": data.get("set", ""),
            "collector_number": data.get("collector_number", ""),
            "price": price,
        }
        results.append(entry)
        sys.stderr.write(f"[{i+1}/{len(names)}] {entry['name']}: {entry['set']} #{entry['collector_number']} ${price:.2f}\n")
    total = sum(r.get("price", 0) for r in results if "price" in r)
    sys.stderr.write(f"\nTotal: ${total:.2f}\n")
    return results


def printings(name):
    encoded = encode_name(name)
    url = f"{API_BASE}/cards/named?exact={encoded}"
    data = fetch(url)
    if data.get("object") == "error":
        url = f"{API_BASE}/cards/named?fuzzy={encoded}"
        data = fetch(url)
    if data.get("object") == "error":
        return [{"error": data.get("details", "Not found")}]
    prints_uri = data.get("prints_search_uri")
    if not prints_uri:
        return [extract_card(data)]
    results = []
    time.sleep(RATE_LIMIT_DELAY)
    while prints_uri:
        pdata = fetch(prints_uri)
        if pdata.get("object") == "error":
            break
        for card in pdata.get("data", []):
            results.append({
                "name": card.get("name", ""),
                "set": card.get("set", ""),
                "set_name": card.get("set_name", ""),
                "collector_number": card.get("collector_number", ""),
                "prices": card.get("prices", {}),
                "frame": card.get("frame", ""),
                "full_art": card.get("full_art", False),
                "border_color": card.get("border_color", ""),
                "finishes": card.get("finishes", []),
            })
        if pdata.get("has_more") and pdata.get("next_page"):
            time.sleep(RATE_LIMIT_DELAY)
            prints_uri = pdata["next_page"]
        else:
            prints_uri = None
    return results


def read_stdin_args():
    """Read arguments from stdin, one per line."""
    import select
    if select.select([sys.stdin], [], [], 0.0)[0]:
        return [line.strip() for line in sys.stdin if line.strip()]
    return []


def parse_flags(args):
    """Extract --limit and --max-price flags from args, return (remaining_args, limit, max_price)."""
    remaining = []
    limit = 30
    max_price = None
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--max-price" and i + 1 < len(args):
            max_price = float(args[i + 1])
            i += 2
        elif args[i] == "--no-limit":
            limit = None
            i += 1
        else:
            remaining.append(args[i])
            i += 1
    return remaining, limit, max_price


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: scryfall_lookup.py <command> [args...]"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "named":
        names = sys.argv[2:] if len(sys.argv) > 2 else read_stdin_args()
        if not names:
            print(json.dumps({"error": "Provide at least one card name"}))
            sys.exit(1)
        results = lookup_named(names)
        print(json.dumps(results, indent=2))

    elif command == "search":
        raw_args = sys.argv[2:] if len(sys.argv) > 2 else []
        query_parts, limit, max_price = parse_flags(raw_args)
        query = " ".join(query_parts)
        if not query:
            stdin_args = read_stdin_args()
            query = " ".join(stdin_args) if stdin_args else ""
        if not query:
            print(json.dumps({"error": "Provide a search query"}))
            sys.exit(1)
        results = search(query, limit=limit, max_price=max_price)
        print(json.dumps(results, indent=2))

    elif command == "set_card":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Provide set code and collector number"}))
            sys.exit(1)
        result = set_card(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif command == "cheapest":
        names = sys.argv[2:] if len(sys.argv) > 2 else read_stdin_args()
        if not names:
            print(json.dumps({"error": "Provide at least one card name"}))
            sys.exit(1)
        results = cheapest(names)
        print(json.dumps(results, indent=2))

    elif command == "printings":
        if len(sys.argv) > 2:
            name = " ".join(sys.argv[2:])
        else:
            stdin_args = read_stdin_args()
            name = " ".join(stdin_args) if stdin_args else ""
        if not name:
            print(json.dumps({"error": "Provide a card name"}))
            sys.exit(1)
        results = printings(name)
        print(json.dumps(results, indent=2))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
