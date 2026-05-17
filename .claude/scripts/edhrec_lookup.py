#!/usr/bin/env python3
"""EDHRec JSON API lookup utility.

Usage:
    python3 .claude/scripts/edhrec_lookup.py commander "Commander Name"
    python3 .claude/scripts/edhrec_lookup.py commander "Commander Name" theme
    python3 .claude/scripts/edhrec_lookup.py card "Card Name"
    python3 .claude/scripts/edhrec_lookup.py top

Outputs JSON to stdout.
"""

import json
import re
import subprocess
import sys

API_BASE = "https://json.edhrec.com"


def fetch(url):
    result = subprocess.run(
        ["curl", "-s", url],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return {"error": f"curl failed: {result.stderr}"}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON response", "raw": result.stdout[:200]}
    return data


def slugify(name):
    slug = name.lower()
    slug = re.sub(r"[',.]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def commander(name, theme=None):
    slug = slugify(name)
    if theme:
        url = f"{API_BASE}/pages/commanders/{slug}/{theme}.json"
    else:
        url = f"{API_BASE}/pages/commanders/{slug}.json"
    data = fetch(url)
    if "error" in data:
        return data
    result = {
        "commander": name,
        "slug": slug,
        "theme": theme,
    }
    if "container" in data:
        container = data["container"]
        result["num_decks"] = container.get("json_dict", {}).get("numDecks", 0)
    cardlists = data.get("cardlists", [])
    for cl in cardlists:
        tag = cl.get("tag", "")
        cards = []
        for card in cl.get("cardviews", [])[:30]:
            cards.append({
                "name": card.get("name", ""),
                "synergy": card.get("synergy", 0),
                "inclusion": card.get("inclusion", 0),
                "num_decks": card.get("num_decks", 0),
                "label": card.get("label", ""),
            })
        if cards:
            result[tag] = cards
    return result


def card(name):
    slug = slugify(name)
    url = f"{API_BASE}/pages/cards/{slug}.json"
    return fetch(url)


def top():
    url = f"{API_BASE}/pages/top/week.json"
    data = fetch(url)
    if "error" in data:
        return data
    commanders = []
    for entry in data.get("cardlists", [{}])[0].get("cardviews", [])[:20]:
        commanders.append({
            "name": entry.get("name", ""),
            "num_decks": entry.get("num_decks", 0),
            "label": entry.get("label", ""),
        })
    return {"trending": commanders}


def read_stdin_args():
    """Read arguments from stdin, one per line."""
    import select
    if select.select([sys.stdin], [], [], 0.0)[0]:
        return [line.strip() for line in sys.stdin if line.strip()]
    return []


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: edhrec_lookup.py <command> [args...]"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "commander":
        if len(sys.argv) >= 3:
            name = sys.argv[2]
            theme = sys.argv[3] if len(sys.argv) > 3 else None
        else:
            stdin_args = read_stdin_args()
            if not stdin_args:
                print(json.dumps({"error": "Provide a commander name"}))
                sys.exit(1)
            name = stdin_args[0]
            theme = stdin_args[1] if len(stdin_args) > 1 else None
        result = commander(name, theme)
        print(json.dumps(result, indent=2))

    elif command == "card":
        if len(sys.argv) >= 3:
            name = " ".join(sys.argv[2:])
        else:
            stdin_args = read_stdin_args()
            name = " ".join(stdin_args) if stdin_args else ""
        if not name:
            print(json.dumps({"error": "Provide a card name"}))
            sys.exit(1)
        result = card(name)
        print(json.dumps(result, indent=2))

    elif command == "top":
        result = top()
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
