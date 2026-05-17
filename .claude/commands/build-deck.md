# Build Deck

Build a complete Commander/EDH deck from scratch given a commander, optional theme, and budget.

## Usage

```
/build-deck <commander name> [theme:<theme>] [budget:<amount>] [bling:yes]
```

Examples:
- `/build-deck Karumonix, the Rat King theme:tribal budget:150`
- `/build-deck Atraxa, Praetors' Voice theme:superfriends budget:300`
- `/build-deck Rankle, Master of Pranks budget:75`
- `/build-deck Tymna the Weaver theme:lifegain budget:500 bling:yes`

## Arguments

Parse the following from `$ARGUMENTS`:
- **Commander** (required): The commander card name. Everything before `theme:` or `budget:` keywords.
- **Theme** (optional): Deck archetype/theme (e.g., tribal, aristocrats, voltron, combo, control, tokens, superfriends, reanimator). Keyword: `theme:<value>`
- **Budget** (optional but ask if missing): Total deck budget in USD excluding the commander. Keyword: `budget:<value>`
- **Bling** (optional, default: no): Whether to look up premium printings. Keyword: `bling:yes`

## Missing Information Protocol

All prompting MUST happen BEFORE the pipeline starts. Once Phase 0 begins, the pipeline runs silently to completion with no user interaction.

If the commander is not provided or `$ARGUMENTS` is empty, use AskUserQuestion to gather:
1. Commander name (required)
2. Theme/archetype (optional, offer common ones based on the commander's colors/abilities)
3. Budget in USD (required — offer tiers: $50, $100, $150, $250, $500, no limit)

If only the budget is missing, ask for it before starting the pipeline. If theme is missing, do NOT ask — infer it from the commander's abilities in Phase 1.

## Orchestration Pipeline

Execute this pipeline. All phases run silently — no user interaction after start.

**TOKEN EFFICIENCY RULES**:
- Agents write intermediate results to `tmp/` files. Downstream agents read from those files via the Read tool.
- Do NOT paste full agent output into downstream prompts. Pass only: commander name/identity, theme, budget, and which files to read.
- Use model overrides on each agent to avoid inheriting the expensive parent model. See per-phase notes for which model to use.

**BASH COMMAND RULES** (include verbatim in EVERY agent prompt):
1. NEVER use `python3 -c` — it triggers security prompts. ALL work must use the helper scripts.
2. Use pipe syntax for queries with special chars: `echo "query" | python3 .claude/scripts/scryfall_lookup.py search`
3. All bash commands MUST be single-line. No newlines inside quoted arguments.
4. NEVER chain commands with `&&` or `;` — compound commands trigger permission prompts. Run each command as a separate Bash call.
5. Use `--limit N` to cap search results. Use `--max-price N` to filter by price.
6. The scripts handle ALL filtering — never write custom Python to parse results.

Examples:
```bash
python3 .claude/scripts/scryfall_lookup.py named "Sol Ring"
echo "id<=ub o:draw f:commander" | python3 .claude/scripts/scryfall_lookup.py search --limit 15 --max-price 10
echo "Karumonix, the Rat King" | python3 .claude/scripts/edhrec_lookup.py commander
python3 .claude/scripts/scryfall_lookup.py cheapest "Sol Ring" "Arcane Signet"
```

### Phase 0: Commander Validation (INLINE — no agent)

Run directly via Bash — do NOT spawn an agent. Run these as TWO SEPARATE Bash calls (do NOT chain with `&&` — compound commands trigger permission prompts):
1. `mkdir -p tmp`
2. `python3 .claude/scripts/scryfall_lookup.py named "Commander Name"`

Parse the JSON and validate:
1. **Exists**: No error in response
2. **Commander-legal**: `legalities.commander` equals `"legal"`
3. **Can be commander**: type_line contains "Legendary Creature" OR oracle_text contains "can be your commander"
4. **Not banned**

If any check fails, report to user and stop. On success, extract and remember: full name, color_identity, oracle_text, mana_cost, cmc.

### Phase 1: Research (3 agents, parallel)

Spawn ALL THREE agents in a SINGLE message.

**Research file format**: One line per card — `- Card Name {mana_cost} — reason` (5-10 words max per card). Be comprehensive but dense. No filler text, no explanatory paragraphs. More cards surfaced = better deck.

**Scryfall search coverage**: Scryfall returns results alphabetically, so `--limit 15` only gets A-E cards. To get full-alphabet coverage, run multiple searches with different criteria, sort orders, or keyword variations. For example, search for the mechanic keyword, then search for related effects with different wording. Aim for 30-50 unique cards per agent across all searches.

**Agent A — EDHRec + Core Synergy** (model: "haiku"):
- Prompt: commander name, oracle text, color identity, theme, budget, BASH COMMAND RULES
- Query EDHRec: `python3 .claude/scripts/edhrec_lookup.py commander "Commander Name"`
  - If a theme was specified: `python3 .claude/scripts/edhrec_lookup.py commander "Commander Name" theme`
- Run 3-4 Scryfall searches for theme-specific synergy cards with `--limit 20 --max-price N`, varying search terms to avoid alphabetical overlap
- Use the Write tool to save to `tmp/research_synergy.md`:
  - EDHRec top synergy cards (name + synergy score)
  - Scryfall search hits organized by role

**Agent B — Commander Mechanic Payoffs** (model: "haiku"):
- Prompt: commander name, oracle text, color identity, theme, budget, BASH COMMAND RULES
- This agent focuses specifically on cards that SYNERGIZE with the commander's unique mechanic — not generic good cards, but cards whose value multiplies because of what the commander does
- Analyze the commander's oracle text and identify the key mechanical interactions (e.g., ETB doubling for Elesh Norn, no-draw lock for Maralen, rat tribal for Karumonix)
- Run 4-5 targeted Scryfall searches with `--limit 20 --max-price N` for:
  - Cards that directly benefit from the commander's ability
  - Cards that enable or protect the commander's strategy
  - Win conditions that leverage the commander's unique angle
  - Use varied search terms (different keywords, different oracle text fragments) to avoid alphabetical clustering
- Use the Write tool to save to `tmp/research_payoffs.md`:
  - Cards grouped by how they interact with the commander
  - Explain the specific synergy in the reason field (not just "good card" — HOW does it interact with the commander?)

**Agent C — Draw, Ramp, Removal, Lands** (model: "haiku"):
- Prompt: commander name, oracle text, color identity, theme, budget, BASH COMMAND RULES
- Run 4-5 Scryfall searches with `--limit 20 --max-price N` for:
  - Card draw engines in color identity
  - Ramp sources (2-CMC preferred, MUST be unconditional — no "if opponent has more lands" unless the deck specifically wants that)
  - Removal/interaction in color identity
  - Utility lands for the strategy
- Use the Write tool to save to `tmp/research_infra.md`:
  - Cards grouped by role (## Draw, ## Ramp, ## Removal, ## Lands)
  - For ramp cards, explicitly note whether they are conditional or unconditional

### Phase 2: Build (1 agent)

Spawn ONE agent (model: "sonnet"):

**Agent — Deck Builder**:
- Prompt: commander name, oracle text, color identity, theme, budget, BASH COMMAND RULES
- MUST read ALL THREE research files using the Read tool:
  - `tmp/research_synergy.md` (EDHRec data + core synergy)
  - `tmp/research_payoffs.md` (commander-specific mechanic payoffs)
  - `tmp/research_infra.md` (draw, ramp, removal, lands)
- Build the 100-card list following targets:
  - Lands: 35-37
  - Ramp: 10-12
  - Card draw: 10-12
  - Removal/interaction: 8-12
  - Win conditions: 3-5
  - Core synergy: fill remaining slots
- Card selection priorities:
  1. High-synergy cards from EDHRec that fit within budget
  2. Commander-specific payoffs from research_payoffs.md — these are the cards that make the deck feel unique
  3. Format staples for the color identity
  4. Cards that serve multiple roles
  5. Budget-appropriate alternatives to expensive staples
- **Prefer cards from the research files**, but if a category is underfilled (e.g., not enough payoffs, weak ramp options), run additional Scryfall searches to fill the gap rather than including weak cards. Every card should earn its slot.
- **Validate EVERY non-land card via Scryfall** after drafting the list:
  - Run `python3 .claude/scripts/scryfall_lookup.py named "Card1" "Card2" ...` in batches of 20
  - For each card, read the full oracle_text and verify it actually synergizes with the deck's strategy
  - Verify color_identity is within the commander's colors
  - If a card doesn't fit the theme or has incorrect color identity, replace it
- **Ramp quality check**: Every ramp card must be unconditional unless the deck specifically benefits from the condition. Cards like "if an opponent controls more lands" are conditional — flag and replace with unconditional alternatives unless there's a specific reason to keep them.
- **Tag each card by its ACTUAL function** based on oracle text, not assumptions:
  - A card that draws cards is #Draw regardless of what section it came from in research
  - A card that ramps is #Ramp
  - Only tag cards as synergy/theme if their oracle text directly interacts with the deck's strategy
- **Self-validate before writing**:
  - Exactly 100 cards (99 + commander)
  - No duplicate card names
  - All cards confirmed within commander's color identity via Scryfall results
  - Reasonable mana curve (avg CMC 2.5-3.2)
- **Mana base optimization**:
  - Include dual land cycles appropriate for budget (see Mana Base Guidelines in CLAUDE.md)
  - Minimize basics: 8-15 for 2-color, 5-10 for 3-color
  - 2-4 utility lands that advance the strategy
- Use the Write tool to save to `tmp/decklist.txt`:
  - One card per line, grouped under `## Category` headers
  - Categories should be functional: Ramp, Draw, Removal, Creatures, Synergy, Finishers, Lands, etc.
  - Commander on its own line at the top marked `## Commander`
  - Tags must reflect verified oracle text function, not guesses

### Phase 3: Deck Analyst (1 agent)

Spawn ONE agent (model: "opus"):

**Agent — Deck Analyst**:
- Prompt: commander name, oracle text, color identity, theme, budget, BASH COMMAND RULES
- Read `tmp/decklist.txt` using the Read tool
- **Validate every non-land, non-basic card via Scryfall** in batches of 20:
  - `python3 .claude/scripts/scryfall_lookup.py named "Card1" "Card2" ...`
  - Verify each card exists, is Commander-legal, and is within color identity
  - Read oracle_text and confirm the card actually does what it's included for
- **Synergy audit**: For each card, evaluate whether it meaningfully interacts with the commander's ability. Flag cards that are generically good but don't leverage the commander (e.g., a vanilla beater in a combo deck, a flicker spell with no ETB targets)
- **Category balance check**:
  - Count cards in each functional category (ramp, draw, removal, synergy, finishers, lands)
  - Flag if any category is under or over target (see targets in Phase 2)
  - Verify ramp is unconditional (flag conditional ramp cards)
- **Mana base audit**:
  - Count total lands, basics, utility lands
  - Check color distribution matches the deck's pip requirements
  - Flag taplands that don't justify their tempo loss
  - Flag if basic count is too high for the budget level
- **Curve analysis**: Calculate average CMC of non-land cards. Flag if outside 2.5-3.2 range.
- **Dead card check**: Identify cards that conflict with the commander or other cards in the deck (nonbos). Example: draw-dependent cards in a no-draw commander, sacrifice outlets without fodder, etc.
- Write findings to `tmp/deck_review.md`:
  - List of specific problems found (card name + issue)
  - Suggested replacements for each problem card (with Scryfall search if needed)
  - Overall assessment: category balance, curve, mana base grade
- If problems are found, update `tmp/decklist.txt` with the fixes (read it, apply swaps, write it back)

### Phase 4: Price + Compile (1 agent)

Spawn ONE agent (model: "haiku"):

**Agent — Pricer + Compiler**:
- Prompt: commander name, theme, budget, bling flag, output filename (slugified commander name + theme), BASH COMMAND RULES
- Read `tmp/decklist.txt` using the Read tool
- **Price all non-basic-land cards** in batches of 20:
  - Default: `python3 .claude/scripts/scryfall_lookup.py cheapest "Card1" "Card2" ...`
  - Bling: `python3 .claude/scripts/best_printing.py "Card1" "Card2" ...`
- If total exceeds budget:
  - Identify most expensive non-essential cards (generic staples, not key synergy pieces)
  - Search for budget alternatives via `--limit 5 --max-price N`
  - Swap and re-price only the changed cards
- **Compile the final markdown file** to the `decks/` directory (create it if it doesn't exist with `mkdir -p decks`):
  1. **Commander & Strategy**: 2-3 sentence summary
  2. **Theme** section (YAML-style metadata block inside a code block tagged `theme`). This section is machine-readable by the update-deck pipeline so it knows what the deck is trying to do and which cards are theme-critical. Format:
     ````
     ```theme
     commander: Full Commander Name
     archetype: one-word archetype (e.g., flicker, lock, tribal, aristocrats, voltron)
     strategy: 1-2 sentence description of the core game plan
     key_mechanics:
       - mechanic 1 (e.g., "ETB doubling", "no-draw lock", "rat tribal")
       - mechanic 2
     protected_cards:
       - Card Name — why this card is essential to the theme (one line each)
       - Card Name — reason
     ```
     ````
     The `protected_cards` list should include 10-15 cards that are specifically chosen for this deck's unique theme — not generic staples like Sol Ring, but cards that would look off-theme to an update pipeline that doesn't understand the strategy. These cards should NOT be cut during updates unless the user explicitly changes the theme.
  3. **Moxfield Import**: complete 100-card decklist in a code block
     - Format: `1 Card Name #Tag` (no set codes unless bling)
     - Tags: functional categories (#Commander, #Ramp, #Draw, #Removal, #Creatures, #Combo, #Lands, etc.)
     - If bling: `1 Card Name (SET) collector_number #Tag`
  4. **TCGPlayer Shopping List**: all non-basic cards
     - Format: `1 Card Name [SET] collector_number`
     - If set code unlikely to resolve on TCGPlayer, omit it and add to a Printing guide table below
- **Verify total = exactly 100 cards** before writing the file
- Include total deck cost at the top

### Phase 5: Summary (orchestrator)

Read the output file. Present to the user:
- Commander & strategy (2-3 sentences)
- Total deck cost vs budget
- Card count verification (must be 100)
- Notable includes and synergies
- Path to the output file

## Budget Allocation Guide

Distribute the budget roughly as:
- Mana base (lands + ramp): 30-40% of budget
- Core strategy cards: 30-40% of budget
- Interaction/removal: 10-15% of budget
- Card draw/advantage: 10-15% of budget

If total exceeds budget during Phase 3, replace the most expensive non-essential cards with budget alternatives. Never cut essential synergy pieces for budget — cut generic staples first.

## Error Recovery

- If a card fails validation, find a replacement via Scryfall search with similar criteria
- If EDHRec returns no data (new commander), rely more heavily on Scryfall searches by color/type/keyword
- If budget is impossible (commander requires expensive pieces), warn the user and suggest a realistic minimum
- If rate-limited by Scryfall, wait and retry — do not skip validation
