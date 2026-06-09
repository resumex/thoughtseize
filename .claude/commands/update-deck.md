# Update Deck

Analyze an existing decklist and produce an optimized version with recommended swaps.

## Usage

```
/update-deck <decklist source> [budget:<amount>] [cuts:<number>] [bling:yes]
```

Examples:
- `/update-deck paste budget:100 cuts:15`
- `/update-deck karumonix-rats.md budget:50 cuts:10`
- `/update-deck https://www.moxfield.com/decks/xxxxx budget:200`
- `/update-deck rankle-pranks.md budget:75 bling:yes`

## Arguments

Parse from `$ARGUMENTS`:
- **Source** (required): One of:
  - `paste` — Prompt the user to paste their decklist
  - A filename in the project directory (e.g., `karumonix-rats.md`)
  - A Moxfield URL (fetch and parse)
- **Budget** (optional but ask if missing): Budget for upgrades/replacements in USD. Keyword: `budget:<value>`
- **Cuts** (optional, default 10-15): Maximum number of swaps to suggest. Keyword: `cuts:<value>`
- **Bling** (optional, default: no): Whether to look up premium printings. Keyword: `bling:yes`

## Missing Information Protocol

All prompting MUST happen BEFORE the pipeline starts. Once Phase 0 begins, the pipeline runs silently to completion with no user interaction.

If source is not provided or `$ARGUMENTS` is empty, use AskUserQuestion to gather:
1. Decklist source (paste, file, or URL)
2. Budget for changes
3. Number of swaps desired (offer: 5-8 minor tweaks, 10-15 meaningful upgrade, 20+ major overhaul)
4. Any specific concerns or focus areas (mana base, win conditions, interaction, etc.)

If only the budget is missing, ask for it before starting the pipeline.

## Orchestration Pipeline

Execute this pipeline. All phases run silently — no user interaction after start.

**TOKEN EFFICIENCY RULES**:
- Agents write intermediate results to `tmp/` files. Downstream agents read from those files via the Read tool.
- Do NOT paste full agent output into downstream prompts. Pass only: commander name/identity, theme, budget, swap count, and which files to read.
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

### Phase 0: Parse Decklist + Validate Commander (INLINE — no agent)

Run directly — do NOT spawn an agent for this phase.

**Step 1 — Load the decklist**:
- **File source**: Read the file with the Read tool. Extract card names from the Moxfield Import code block (lines like `1 Card Name #Tag` → extract `Card Name`). The `#Commander` tagged card is the commander.
- **Also extract the Theme section** if present (the `theme` code block). Parse the `archetype`, `strategy`, `key_mechanics`, and `protected_cards` fields. These will be passed to research agents so they know which cards are theme-critical and should not be cut.
- **Paste source**: Prompt user to paste, then parse each line (`1 Card Name` or `1 Card Name #Tag` or `1 Card Name (SET) number`).
- **URL source**: Fetch via `curl -s "https://api2.moxfield.com/v3/decks/all/<deck_id>"` (extract deck_id from URL). Parse the JSON for mainboard card names and commander.

**Step 2 — Write parsed decklist**:
```bash
mkdir -p tmp
```
Use the Write tool to save the parsed card list to `tmp/current_decklist.txt` — one card per line, commander marked with `## Commander` header at top. If a Theme section was found, append it at the bottom under a `## Theme` header so research agents can read it.

**Step 3 — Validate commander**:
```bash
python3 .claude/scripts/scryfall_lookup.py named "Commander Name"
```
Validate: exists, `legalities.commander == "legal"`, type_line has "Legendary Creature" or oracle_text has "can be your commander", not banned.

If validation fails, stop and report. On success, extract: full name, color_identity, oracle_text, mana_cost, cmc.

### Phase 1: Research (2 agents, parallel)

Spawn BOTH agents in a SINGLE message. Each reads the current decklist from file and writes findings to a file.

**Research file format**: One line per card — `- Card Name {mana_cost} — reason` (5-10 words max per card). Be comprehensive but dense. No filler text, no explanatory paragraphs.

**Scryfall search coverage**: Scryfall returns results alphabetically, so `--limit 15` only gets A-E cards. To get full-alphabet coverage, run multiple searches with different criteria, sort orders, or keyword variations. Aim for 20-30 unique candidates per agent across all searches.

**Agent A — EDHRec + Synergy Analysis** (model: "haiku"):
- Prompt: commander name, oracle text, color identity, budget, swap count, theme info (if available), BASH COMMAND RULES
- Read `tmp/current_decklist.txt` using the Read tool
- **If a `## Theme` section exists at the bottom of the file**, read and respect it:
  - Cards listed in `protected_cards` should NOT be suggested as cuts unless they are actual nonbos with the commander
  - Use the `strategy` and `key_mechanics` fields to understand the deck's intent when evaluating synergy
- Query EDHRec: `python3 .claude/scripts/edhrec_lookup.py commander "Commander Name"`
- Cross-reference EDHRec data against current decklist:
  - High-synergy cards NOT in the deck → potential additions
  - Cards in the deck with low/no EDHRec synergy → potential cuts (but NOT protected cards)
- Run 3-4 Scryfall searches for gap-filling cards with `--limit 20 --max-price N`, varying search terms to avoid alphabetical overlap
- Analyze the commander's specific mechanic and flag cards in the current list that don't meaningfully interact with it (nonbos, dead cards, conditional effects that rarely trigger)
- Use the Write tool to save to `tmp/research_additions.md`:
  - **Potential additions**: top 25-30 cards (name, mana cost, 5-10 word reason, explain the specific synergy with the commander)
  - **Potential cuts**: bottom 10-15 cards from current list (name, why it's weak or off-theme). Never suggest cutting a protected card unless it's a confirmed nonbo.
  - **Nonbos/dead cards**: any cards that actively conflict with the commander's strategy (protected cards CAN appear here if they genuinely conflict)

**Agent B — Mana Base + Interaction Audit** (model: "sonnet"):
- Prompt: commander name, color identity, budget, BASH COMMAND RULES
- Read `tmp/current_decklist.txt` using the Read tool
- Analyze the current mana base from card names:
  - Count lands, basics, duals, utility lands
  - Estimate color ratio from known land names
  - Identify taplands that could be upgraded
- Analyze removal/interaction package from card names
- **Ramp audit**: Identify every ramp card in the list. Flag conditional ramp (e.g., "if opponent controls more lands") separately from unconditional ramp. If the deck has more than 2 conditional ramp sources, flag this as a problem.
- Run 2-3 Scryfall searches for upgrade lands/removal with `--limit 20 --max-price N`, varying search terms for coverage
- Use the Write tool to save to `tmp/research_fixes.md`:
  - Mana base summary (land count, basic count, issues)
  - Ramp audit results (conditional vs unconditional breakdown)
  - Up to 5 land swap recommendations (cut X → add Y, one-line reason)
  - Up to 3 removal swap recommendations if interaction is weak
  - Up to 3 ramp swap recommendations if conditional ramp is excessive

### Phase 2: Build Swaps + Validate (1 agent)

Spawn ONE agent (model: "sonnet"):

**Agent — Swap Builder**:
- Prompt: commander name, oracle text, color identity, budget, swap count (from `cuts` parameter), BASH COMMAND RULES
- Read ALL THREE files using the Read tool:
  - `tmp/current_decklist.txt` (current deck)
  - `tmp/research_additions.md` (synergy gaps + potential cuts)
  - `tmp/research_fixes.md` (mana base + removal fixes)
- Build the swap list:
  - Prioritize cuts: lowest synergy + highest CMC + weakest effect first
  - Match each cut with the best available replacement from research
  - Respect the requested swap count
  - Maintain or improve category balance (don't gut ramp or draw)
  - Apply mana base upgrades from research_fixes
- **Validate ALL new additions via Scryfall** before finalizing:
  - Run `python3 .claude/scripts/scryfall_lookup.py named "Card1" "Card2" ...` for all additions in a batch
  - Read each card's full oracle_text to confirm it actually does what you expect
  - Verify color_identity is within the commander's colors
  - If a card doesn't fit, find a replacement from research or via Scryfall search
- **Self-validate**:
  - Post-swap deck is exactly 100 cards
  - No duplicate card names
  - All new cards confirmed within color identity via Scryfall results
  - Category balance maintained
- Use the Write tool to save to `tmp/swap_plan.md`:
  - Swap table: `| Cut | Add | Reason |` (one row per swap)
  - Complete post-swap decklist (one card per line, grouped by `## Category`)

### Phase 3: Swap Analyst (1 agent)

Spawn ONE agent (model: "fable"):

**Agent — Swap Analyst**:
- Prompt: commander name, oracle text, color identity, budget, BASH COMMAND RULES
- Read `tmp/swap_plan.md` using the Read tool
- **Validate every new addition via Scryfall** in batches of 20:
  - `python3 .claude/scripts/scryfall_lookup.py named "Card1" "Card2" ...`
  - Verify each card exists, is Commander-legal, and is within color identity
  - Read oracle_text and confirm the card actually does what it's included for
- **Synergy audit**: For each new addition, verify it meaningfully interacts with the commander's ability. Flag additions that are generically good but don't leverage the commander.
- **Category balance check**: Verify the post-swap deck maintains healthy category balance (ramp 10-12, draw 10-12, removal 8-12). Flag if any category got gutted by the swaps.
- **Ramp quality check**: Verify all ramp in the post-swap list is unconditional (flag conditional ramp).
- **Dead card / nonbo check**: Look for cards in the post-swap list that conflict with the commander or with newly added cards.
- Write findings to `tmp/swap_review.md`:
  - List of problems found (card name + issue)
  - Suggested fixes for each problem
- If problems are found, update `tmp/swap_plan.md` with fixes (read it, apply corrections, write it back)

### Phase 4: Price + Compile (1 agent)

Spawn ONE agent (model: "haiku"):

**Agent — Pricer + Compiler**:
- Prompt: commander name, budget, bling flag, output filename (same as source file if updating, or slugified commander name), BASH COMMAND RULES
- Read `tmp/swap_plan.md` using the Read tool
- **Price ONLY the new additions** (not the full deck) in batches of 20:
  - Default: `python3 .claude/scripts/scryfall_lookup.py cheapest "Card1" "Card2" ...`
  - Bling: `python3 .claude/scripts/best_printing.py "Card1" "Card2" ...`
- If total upgrade cost exceeds budget:
  - Flag which additions are over-budget
  - Search for cheaper alternatives with `--limit 5 --max-price N`
  - Swap and re-price only the changed cards
- **Compile the final markdown file** to the `decks/` directory (create it if it doesn't exist with `mkdir -p decks`):
  1. **Commander & Strategy**: 2-3 sentence summary
  2. **Theme** section — if the source deck already had a `theme` block, preserve it and update `protected_cards` to reflect any swaps made. If no theme block existed, generate one based on the deck's strategy. Format:
     ````
     ```theme
     commander: Full Commander Name
     archetype: one-word archetype
     strategy: 1-2 sentence core game plan
     key_mechanics:
       - mechanic 1
       - mechanic 2
     protected_cards:
       - Card Name — why this card is essential to the theme
     ```
     ````
     Include 10-15 theme-critical cards in `protected_cards` (not generic staples).
  3. **Swap Table**:
     ```
     | Cut | Add | Reason |
     |-----|-----|--------|
     ```
     Include set code + collector number + finish marker for additions.
  4. **Moxfield Import**: complete post-swap 100-card decklist in a code block
     - Format: `1 Card Name #Tag` (no set codes unless bling)
     - Tags: functional categories (#Commander, #Ramp, #Draw, #Removal, #Creatures, etc.)
     - If bling: `1 Card Name (SET) collector_number #Tag`
  5. **TCGPlayer Shopping List**: ONLY the new additions
     - Format: `1 Card Name [SET] collector_number`
     - If set code unlikely to resolve on TCGPlayer, omit it and add to a Printing guide table
- **Verify total = exactly 100 cards** before writing
- Include total upgrade cost at the top

### Phase 5: Summary (orchestrator)

Read the output file. Present to the user:
- Number of swaps made
- Total upgrade cost vs budget
- Card count verification (must be 100)
- Key improvements (what got better: curve, synergy, mana base, interaction)
- Path to the output file

## Error Recovery

- If a card fails validation, find a replacement via Scryfall search with similar criteria
- If EDHRec returns no data (new commander), rely more heavily on Scryfall searches by color/type/keyword
- If budget is impossible (upgrades require expensive pieces), warn the user and suggest a realistic minimum
- If rate-limited by Scryfall, wait and retry — do not skip validation
- If the decklist source can't be parsed, stop and ask the user to provide the list in a different format
