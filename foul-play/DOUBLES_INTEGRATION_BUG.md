# foul-play ↔ poke-engine Doubles Integration: Bug + Fix Plan

**Status: FIXED + integrated. foul-play code updated to the 4-side API; the local gen9
`poke_engine` extension was rebuilt and installed; the fix is smoke-tested (move-pair
selection reads the ally slots, targeting math verified). Ready for live testing. The one
thing to confirm live is the Showdown foe target-number reversal (see ⚠️ below).**

### Build/install that was done (gen9)
```
pip install maturin
cd poke-engine/poke-engine-py
maturin build --release --no-default-features --features poke-engine/gen9 --interpreter <python311>
pip install --force-reinstall --no-deps ../target/wheels/poke_engine-0.0.46-cp311-cp311-win_amd64.whl
```
This replaced the stale `poke-engine 0.0.47` wheel with the local gen9 build. Verified:
`State.side_one_1` present, `generate_instructions` takes 4 moves, `MctsResult` has four
slot lists. **Re-run this build whenever the Rust engine changes** (there is no venv, so it
installs into the global Python311 — consider a venv).

## ⛔ Critical blocker discovered: the installed `poke_engine` is stale
`python -c "import poke_engine; print(hasattr(poke_engine.State(), 'side_one_1'))"` →
**False** (it still has the old `side_one`/`side_two`). The package is installed at the
global `Python311\Lib\site-packages\poke_engine\` and was **not** rebuilt from the local
doubles engine — and **maturin is not installed / there is no venv**. So:
- The Rust engine was rebuilt (`cargo`), but the **Python extension foul-play imports was
  never rebuilt**. None of the doubles work (4 sides, targeting) is active at runtime.
- The pre-fix foul-play "ran" only because both it and the installed extension were the old
  2-side API.
- **The implemented fix below targets the new 4-side API and will raise
  `AttributeError`/`TypeError` against the stale extension until it is rebuilt + installed.**

### Required to integrate (run before live testing)
```bash
pip install maturin
cd poke-engine/poke-engine-py
# pick the feature matching your battle's generation:
#   gen9 (tera/doubles): maturin develop --release --no-default-features --features poke-engine/gen9
#   gen4 (current default): maturin develop --release
```
`maturin develop` builds the local crate and installs `poke_engine` into the active Python.
(The engine compiles under both gen4 and gen9.) **The feature must match the
`--pokemon-format` generation you run** (a gen9 format with a gen4 engine will misbehave).
Consider a venv to avoid touching the global site-packages.

## Implemented (foul-play code)
- `fp/search/poke_engine_helpers.py::battle_to_poke_engine_state` now builds **four** sides
  (`user_1→side_one_1, user_2→side_one_2, opponent_1→side_two_1, opponent_2→side_two_2`)
  via the new `PokeEngineState(side_one_1=, side_one_2=, side_two_1=, side_two_2=, ...)`.
- `fp/search/main.py::select_move_pair_from_mcts_results` now reads the two **ally** policies
  `side_one_1` (p1a) and `side_one_2` (p3b) — fixing the p3b-uses-p2a's-moves bug.
  `select_move_from_mcts_results` updated to `side_one_1` too.
- `fp/run_battle.py` doubles **targeting**: `_split_engine_target` peels the engine's
  relative-target token off each move; `format_decision` appends a Showdown target location
  (`_showdown_target_loc`) for single-target moves (`all_move_json[move]["target"]`).
  ⚠️ The foe target-number reversal is my best reading of Showdown's `getAtLoc` — **verify
  against a live `|error|` response** and flip the two foe values if needed (documented in
  the helper).

---

## (original diagnosis below)

**Status: diagnosis + plan only. No code changed yet — to be refined first.**

## Symptom
In a multi-battle, the master bot's first slot (**p1a**) searches the correct moveset, but
its ally slot (**p3b**) is searched/selected from the **first opponent's (p2a's)** moveset.

## Player ↔ battler ↔ engine-side mapping (the mental model)
Showdown multi-battle has 4 players; `fp/run_battle.py:293-297` assigns:

| Showdown | foul-play `Battle` field | Role            | Correct engine slot |
|----------|--------------------------|-----------------|---------------------|
| p1a      | `battle.user_1`          | master bot      | `side_one_1`        |
| p3b      | `battle.user_2`          | ally bot        | `side_one_2`        |
| p2a      | `battle.opponent_1`      | opponent        | `side_two_1`        |
| p4b      | `battle.opponent_2`      | opponent's ally | `side_two_2`        |

The bot's **two** moves must come from **`side_one_1` and `side_one_2`** (its own team).
The opponents are `side_two_1` / `side_two_2`.

## Root cause (entirely in the foul-play bridge — the Rust engine is correct)
The engine and Python binding now use four slots
(`side_one_1, side_one_2, side_two_1, side_two_2`). The foul-play bridge was written
against the **old 2-side** engine and "faked" doubles by reinterpreting `side_one`/
`side_two` as the two allied bots. Three concrete defects:

1. **Result mis-mapping (the actual symptom).**
   `fp/search/main.py::select_move_pair_from_mcts_results` builds the pair as:
   - left move ← `mcts_result.side_one`  (Bot1 = user_1 = p1a) ✅
   - right move ← `mcts_result.side_two` (treated as "Bot2") ❌
   But `side_two` is the **opponent** (p2a). So p3b's move is chosen from p2a's options.
   This is exactly the reported behavior.

2. **State builder is 2-side.**
   `fp/search/poke_engine_helpers.py::battle_to_poke_engine_state` (line ~294) builds only
   `side_one = user_1` and `side_two = opponent_1`, **ignores `user_2` and `opponent_2`
   entirely**, and constructs `PokeEngineState(side_one=..., side_two=...)` — the **old**
   keyword args. So the engine never sees p3b or p4b, and the 2v2 game is searched as 1v1.
   (Has an inline `#TODO pokeEngineState may need revamped to account for doubles`.)

3. **Stale 2-side binding API.**
   `main.py` reads `mcts_result.side_one` / `.side_two` and `monte_carlo_tree_search(state,
   time)` returns a result with those fields. The **rebuilt** binding exposes
   `side_one_1/side_one_2/side_two_1/side_two_2` (and `IterativeDeepeningResult` likewise).
   → If the extension is rebuilt with the new binding, this path raises `AttributeError`.
   → The bot currently "works" only because it's running the **old** compiled extension.

A 4th, related gap (not the cause of this symptom but needed for legal doubles play):

4. **No targeting in the dispatch.**
   `fp/run_battle.py::format_decision` emits `"/choose move {decision}"` with **no target
   slot**. Showdown doubles requires an explicit target for most moves (e.g.
   `/choose move tackle 1`, `... tackle -2`). And `convert_mcts_choice_to_move_name` strips
   `-tera`/`-mega` but not the engine's new target suffix (the engine encodes non-diagonal
   targets as e.g. `"tackle opp2"`).

## Is there a poke-engine (Rust) issue?
**No.** The engine's four sides are correct (`side_one_1`/`side_one_2` are allies), the
binding's `generate_instructions` takes four moves, `mcts`/`id` return four slot results,
and `State::serialize`/`deserialize` round-trip four sides. The bug is the foul-play
mapping. The only engine-side thing to *use* correctly is the 4-slot result shape.

## Proposed fix plan (refine before implementing)

### 0. Rebuild the extension
Build & install the updated `poke-engine` extension (maturin/pip) so foul-play imports the
4-slot binding. Everything below assumes the new API
(`side_one_1/side_one_2/side_two_1/side_two_2`, `generate_instructions(s1_1, s1_2, s2_1,
s2_2)`, `mcts(state, ms)` → 4 slot lists). *(Confirm the build/install command used.)*

### 1. `battle_to_poke_engine_state` → four sides
Build all four `PokeEngineSide`s and use the new constructor:
```
side_one_1 = battler_to_poke_engine_side(battle.user_1, force_switch=...)
side_one_2 = battler_to_poke_engine_side(battle.user_2, force_switch=...)
side_two_1 = battler_to_poke_engine_side(battle.opponent_1, stayed_in_on_switchout_move=...)
side_two_2 = battler_to_poke_engine_side(battle.opponent_2, ...)
PokeEngineState(side_one_1=..., side_one_2=..., side_two_1=..., side_two_2=..., ...)
```
- Decide per-slot `force_switch` / `slow_uturn` flags (today only user_1/opponent_1 are
  considered — extend the `opponent_switchout_move_stayed_in` logic to both ally pairs).
- Revisit the `swap` parameter (used elsewhere?) — with four explicit slots it likely
  becomes unnecessary or means "swap teams".

### 2. `select_move_pair_from_mcts_results` → correct slots
- left move ← `mcts_result.side_one_1` (user_1 / p1a)
- right move ← `mcts_result.side_one_2` (user_2 / p3b)
- (the opponents `side_two_1` / `side_two_2` are not selected — they're searched, not chosen)
- Update all `.side_one`/`.side_two` reads in `main.py`
  (`select_move_from_mcts_results`, the `select_move_pair_*` aggregation, and the logging).

### 3. Targeting in the dispatch (`run_battle.py`)
- `convert_mcts_choice_to_move_name`: split off the engine's trailing target token
  (`opp` / `opp2` / `ally` / `self`, where empty = diagonal) before/after `-tera`/`-mega`.
- `format_decision`: translate the engine target → Showdown target index for that slot.
  In multi-battle the foe slots are `1`/`2` and allies are `-1`/`-2` (verify signs/indices
  against the live protocol). Map `DiagonalOpponent`/`OtherOpponent`/`Ally` accordingly,
  per which user slot is acting (p1a vs p3b have different "diagonal" foes).
- Spread/self/no-target moves: omit the target (Showdown rejects a target on those).

### 4. Audit the other 2-side bridge users
- `poke_engine_get_damage_rolls` / `calculate_damage` call: still 2-side
  (`side_one_move, side_two_move`). Decide whether the damage-roll feature is used in
  doubles; if so, give it a 4-slot-aware path or restrict it.
- `search_time_num_battles_*` already read `opponent_1`+`opponent_2` — fine.
- Team preview (`handle_team_preview`) builds a 4-mon-ish team order — re-check indices for
  multi-battle.

### 5. Sanity test before live play
- Add a small offline test: build a `Battle` with distinct movesets on user_1/user_2/
  opponent_1/opponent_2, call `battle_to_poke_engine_state(...).to_string()`, and assert the
  four serialized sides match the intended battlers (catches the mapping regression).
- Then live-test: confirm p3b's considered moves come from p3b's own moveset.

## Open questions for refinement
- **Rebuild status:** are you currently on the old or newly-built extension? (Determines
  whether you'll first hit `AttributeError`s or the silent mis-mapping.)
- **Search model:** one MCTS over the full 4-slot state and read both ally policies
  (`side_one_1`, `side_one_2`) — confirmed the intended approach? (vs. two separate
  searches.)
- **Targeting source of truth:** should foul-play trust the engine's chosen target suffix,
  or pick targets itself and pass them into `generate_instructions`? (The engine's option
  list already encodes targets; simplest is to trust it.)
- **Showdown target indices** for multi-battle (signs for foes vs allies) — confirm against a
  real request/`|choose|` exchange.
