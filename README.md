# Thoughtseize

*Look at the entire card pool. Take the best ones.*

An agentic Commander (EDH) deck builder and optimizer for Magic: The Gathering, built on [Claude Code](https://claude.ai/code) agent pipelines.

## Quick Start

```bash
git clone https://github.com/resumex/thoughtseize.git
cd thoughtseize
claude
```

Then inside Claude Code:

```bash
# Build a new deck from scratch
/build-deck Karumonix, the Rat King theme:tribal budget:150

# Update an existing deck
/update-deck mydeckfile.md budget:50 cuts:10

# Prefer full-art/borderless printings
/build-deck Tymna the Weaver theme:lifegain budget:500 bling:yes
```

## How It Works

`/build-deck` runs 6 agents across 6 phases:

1. **Validate** — confirms the commander is legal via Scryfall
2. **Research** — 3 agents run in parallel, each searching different angles to avoid overlapping results:
   - *EDHRec + Synergy* — pulls top synergy cards and staples from EDHRec, cross-references with Scryfall
   - *Mechanic Payoffs* — finds cards that specifically exploit the commander's unique ability
   - *Infrastructure* — sources draw, ramp, removal, and lands for the color identity
3. **Build** — reads all research files and assembles a 100-card list, validating every card against Scryfall
4. **Analyze** — independent audit for nonbos, dead cards, category imbalance, and mana base issues
5. **Price & Compile** — prices the deck, swaps cards if over budget, and writes the final output file
6. **Summary** — reports the deck to the user

`/update-deck` follows the same pattern: 2 research agents analyze the existing list for weaknesses, a swap builder proposes upgrades, a swap analyst validates the changes, and a pricer compiles the result.

## Output

Each deck produces a markdown file in `decks/` containing:
- **Moxfield Import** — 100-card list with `#Tag` categories, copy-paste ready
- **TCGPlayer Shopping List** — cards with set codes and collector numbers
- **Theme metadata** — machine-readable block so `/update-deck` knows which cards are theme-critical

## Requirements

- [Claude Code](https://claude.ai/code) CLI
- `curl` and `python3` in PATH
- Internet access (Scryfall + EDHRec APIs)
