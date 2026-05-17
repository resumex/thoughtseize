# Thoughtseize — MTG Commander/EDH Deck Builder

## Purpose

This project uses `/build-deck` and `/update-deck` pipelines to build and optimize Commander (EDH) decks. For ad-hoc card lookups and manual advice outside the pipelines, use the Scryfall and EDHRec APIs via the helper scripts in `.claude/scripts/`.

## Scryfall API Usage Guidelines

- **Rate limit**: Scryfall enforces < 10 requests/second. When batch-looking up cards, use `time.sleep(0.15)` between requests minimum. If making many requests (20+), use `time.sleep(0.2)` to stay safe.
- **Preferred lookup method**: Use `curl` via `subprocess.run()` in Python, not `urllib.request` (which has encoding issues with card names containing apostrophes and special characters). Example:
  ```python
  result = subprocess.run(
      ["curl", "-s", f"https://api.scryfall.com/cards/named?fuzzy={encoded}"],
      capture_output=True, text=True
  )
  c = json.loads(result.stdout)
  ```
- **Card name encoding**: Replace spaces with `+`, encode apostrophes as `%27`. Let curl handle the rest.
- **Batch strategy**: For large lookups (30+ cards), split into batches of ~20 with a 2-second pause between batches to avoid 429 errors. If rate-limited, wait 60 seconds before retrying. **Never run multiple batch lookups in parallel** — this doubles the request rate and triggers rate limiting immediately.
- **Search endpoint**: `/cards/search` is better for discovery queries (finding cards by criteria). `/cards/named` is better for validating specific known cards.
- **Error handling**: Always check for `c.get('object') == 'error'` before accessing card fields. Rate limit errors return status 429.

## Mana Base Guidelines

A well-tuned Commander mana base should minimize basic lands unless the deck is budget or has a basics-matter theme. Evaluate the mana base separately from the rest of the deck:

- **Land count**: 34-37 depending on curve and ramp density. MDFCs count as half a land.
- **Color ratio**: Match the pip distribution of the deck. A deck with {1}{B}{B} rats needs more B than U.
- **Untapped sources**: Prioritize lands that enter untapped. Tapped lands should have high utility to justify the tempo loss.
- **Dual land priority** (budget-conscious, roughly $1-10 each):
  - Fast lands (untapped if ≤2 other lands)
  - Check lands (untapped if you control a matching basic type)
  - Slow lands (untapped if ≥2 other lands)
  - Reveal lands (untapped if you show a basic from hand)
  - Pathway MDFCs (always untapped, choose one color)
  - Pain lands (always untapped, costs 1 life for colored)
  - Tainted cycle (untapped UB/UR/etc. if you control a Swamp)
  - Exotic Orchard (always produces what opponents have)
- **Utility lands**: Include 2-4 utility lands that advance the game plan (Reliquary Tower, Swarmyard, tribal lands, Bojuka Bog, etc.)
- **Synergy lands**: Consider lands that interact with the deck's engines (e.g., Urborg + Cabal Coffers for black-heavy decks)
- **Avoid**: Guildgates, gain-1-life taplands, or other strictly-worse duals unless budget demands it
- **Basic land count target**: 8-15 basics total for a 2-color deck with a proper mana base. More than 18 basics in a non-budget 2-color deck is a red flag.

## Rules & Constraints

- All 100 cards must be Commander-legal (check format legality via Scryfall)
- Respect color identity of the commander
- No banned cards (check the official Commander banlist)
- Only one copy of each card (except basic lands)
- Validate that recommended cards actually exist and do what you claim (use Scryfall oracle text)
- **Check for Secret Lair / reskin duplicates**: Cards like "Rodents of Unusual Size" are cosmetic reskins of existing cards (in this case, Pack Rat). Before recommending an addition, verify the card isn't already in the deck under a different name by checking the Scryfall API using the set code and collector number (e.g., `https://api.scryfall.com/cards/{set}/{collector_number}`) for any unfamiliar card names
