# Doubles Conversion — Remaining Work

Status as of the current branch. The data model has been widened from 2 sides to 4
(`side_one_1`, `side_one_2`, `side_two_1`, `side_two_2`), but the turn-resolution
engine, search, bindings, and many per-move mechanics are still singles-shaped or
stubbed. The crate **does not compile** right now (`cargo check` → ~149 errors); a
large fraction of those errors are the concrete TODO list below.

Conventions assumed throughout:
- A `Side` now represents **one active slot**, not a player.
- Team One = `side_one_1` + `side_one_2` (allies). Team Two = `side_two_1` + `side_two_2` (allies).
- `SideReference` has 4 variants: `SideOne_1`, `SideOne_2`, `SideTwo_1`, `SideTwo_2`
  (`src/state.rs:13`).
- `get_other_side()` currently maps each slot to its *diagonal* counterpart
  (`SideOne_1 ↔ SideTwo_1`, `SideOne_2 ↔ SideTwo_2`, `src/state.rs:20`). This 1:1
  mapping is the singles assumption baked into most move code — see "Targeting" below.

---

## 0. Blocking compile errors that aren't conceptually "doubles" work

These are mechanical breakages (mostly from a partially-applied edit) that prevent
*any* progress; fix first so the rest can be iterated on.

- **`src/choices.rs:1702`** — missing comma after `target: MoveTarget::All` in the
  `BOOMBURST` definition. Causes a parser error that cascades. (`MoveTarget::All` is a
  new variant being introduced for spread moves — see §3.)
- **Missing constants** — many `cannot find value` errors for `WEATHER_ABILITY_TURNS`,
  `TYPE_MATCHUP_DAMAGE_MULTIPICATION`, `CRIT_MULTIPLIER`, `MAX_SLEEP_TURNS`,
  `HIT_SELF_IN_CONFUSION_CHANCE`, `CONSECUTIVE_PROTECT_CHANCE`, `BASE_CRIT_CHANCE`
  (in `src/genx/abilities.rs`, `damage_calc.rs`, `generate_instructions.rs`). These
  constants were removed/renamed or an import was dropped; restore them.
- **Local-variable typos / half-edits** in `src/genx/generate_instructions.rs`:
  `healing_wish_consumed` (~400), `damage_factor` (~3109), `damage_amount` (~3506).
- **`destinybond_before_move`** not found (`src/genx/choice_effects.rs:896`).
- **`!todo()`** used as an expression at `src/genx/generate_instructions.rs:645`
  (should be the `todo!()` macro, and ultimately real logic).

---

## 1. Speed / turn-order system  ★ (the headline item)

The entire ordering layer is stubbed and only understands 2 actors.

- **`SideMovesFirst` enum (`src/state.rs:138`)** still has only `SideOne`, `SideTwo`,
  `SpeedTie`. Doubles needs a full ordering over **all four** acting slots (plus speed
  ties between any subset). Recommended: stop modeling this as an enum of "who's first"
  and instead produce an **ordered list of `SideReference`** for the turn.
- **`moves_first()` (`src/genx/generate_instructions.rs:2589`)** is a stub that always
  returns `SideMovesFirst::SideOne_1` (which isn't even a valid variant — compile
  error). The entire real body is commented out and was singles-only anyway. It must be
  rewritten to:
  1. Compute effective speed for each of the 4 slots (`get_effective_speed`,
     `src/genx/generate_instructions.rs:2494`, already works per-slot).
  2. Sort the 4 actions by **priority bracket**, then speed, honoring **Trick Room**
     (`state.trick_room`), switches/Pursuit, and items like Custap Berry / Quick Claw /
     Lagging Tail / Full Incense / Quick Draw.
  3. Handle speed ties as probability branches (currently only a 2-way 50/50 split
     exists; with 4 actors ties can be among 2–4 actions).
  - Suggested approach already hinted in the TODO comment at line 2597: assign each
    action a sortable key of `priority * LARGE + speed` (negate under Trick Room) and
    sort, rather than the pairwise enum.
- **Turn resolution (`generate_instructions_from_move_pair`,
  `src/genx/generate_instructions.rs:4021`)**:
  - The `moves_first(...)` call at **line 4223** passes only 2 choices but the signature
    now takes 4 (`E0061`). Even once that's fixed, the `match` arms (lines 4229–4327)
    still branch on the old 2-side `SideMovesFirst::SideOne/SideTwo/SpeedTie` and call
    `handle_both_moves` with one pair. This must become a loop that executes up to 4
    actions in computed order, re-checking after each action (a slot may faint, switch,
    or have its target removed before it acts).
  - References to `state.side_one` / `state.side_two` and `SideReference::SideOne/SideTwo`
    throughout this function (lines 4203–4319) no longer exist — they must be expanded to
    the 4 concrete slots.
  - `handle_both_moves` (`src/genx/generate_instructions.rs:3929`) is hard-wired to
    exactly two actions (first mover + its `get_other_side()`). Needs a general
    "execute the i-th action in the order, then continue" structure.
  - End-of-turn handling (`add_end_of_turn_instructions`) and the
    `force_switch`/`replacing_fainted_pkmn` guards are written for 2 slots and reference
    the old fields; extend to all 4.

---

## 2. `SideReference` helpers needed

Move code calls methods that don't exist yet (compile errors at
`generate_instructions.rs:538–539`, `572–573`):

- **`get_other_sides()`** → the two opposing slots (e.g. `SideOne_1` → `[SideTwo_1, SideTwo_2]`).
- **`get_own_sides()`** → own team's slots (self + ally).
- Likely also want **`get_ally()`** → the partner slot, and a notion of "the slot
  directly across" (the current `get_other_side()`).
- Decide the semantics of single-target `get_other_side()` in doubles: it's currently
  used everywhere as "the defender," which is only correct in 1v1. Most single-target
  moves need an explicit chosen target instead (see §3).

---

## 3. Move targeting (no target is currently encoded)

This is the second-biggest design gap after speed.

- **`MoveChoice` (`src/genx/state.rs:45`)** encodes `Move(PokemonMoveIndex)` with **no
  target**. In doubles a slot choosing an attack must also choose *which* of the (up to)
  two opponents — or its ally — to hit. `MoveChoice::Move` needs a target field
  (e.g. `Move(PokemonMoveIndex, MoveTarget/SideReference)`), and option generation must
  enumerate target choices.
- **Option generation** (`get_all_options` / `add_actions_for_slot`,
  `src/genx/state.rs:988` / `1174`): `add_actions_for_slot` is **declared with 4 params
  but called with 3** (`state.rs:1147` vs `1174` — compile error), and it currently
  takes a single opponent. It must take both opponents (and the ally) and produce one
  `MoveChoice` per legal (move, target) combination. Spread moves and self/ally-target
  moves should collapse to a single option.
- **Move execution** still resolves a single defender via
  `attacking_side_reference.get_other_side()` (e.g.
  `generate_instructions.rs:643, 832, 980, 1139`, and damage application). These must
  use the chosen target from `MoveChoice`.
- **`MoveTarget` (`src/choices.rs:19350`)** is gaining `All` / `Opponents` variants
  (referenced at `generate_instructions.rs:538, 572, 645`) but the match arms are
  incomplete (`Opponents` unbound, `MoveTarget::All | Opponents => !todo()`); finish the
  enum and every `match` over it.

### Spread moves & redirection (new doubles mechanics, not yet implemented)
- **Spread damage**: moves hitting both opponents (Earthquake, Rock Slide, Dazzling
  Gleam, etc.) deal 0.75× damage when >1 target. New damage path + new target resolution.
- **Earthquake/Surf-style** moves that also hit the **ally**.
- **Redirection**: Follow Me / Rage Powder / Lightning Rod / Storm Drain redirect
  single-target moves to another slot. Requires a redirection check during target
  resolution.
- **Protection variants** that only matter in doubles: **Wide Guard**, **Quick Guard**,
  **Crafty Shield**, **Mat Block** (the `PokemonSideCondition` variants already exist in
  `src/state.rs:30`, but no logic consumes them).
- **Ally-affecting effects**: Helping Hand, Beat Up, Instruct, Decorate, Coaching,
  Ally Switch, and abilities like **Friend Guard**, **Battery**, **Power Spot**.
- **Side conditions are per-team, not per-slot**: Reflect/Light Screen/Tailwind/Spikes
  etc. currently live on a single `Side`. With two `Side`s per team these must be shared
  or mirrored across the ally pair, and `get_own_sides()`/`get_other_sides()` loops in
  `generate_instructions_from_increment_side_condition` (line 530) must not double-apply.

---

## 4. Abilities & field effects that change in doubles

- **Intimidate** should drop Attack on **both** opposing actives (currently single
  target via `get_other_side`, `src/genx/abilities.rs`).
- **Weather/Terrain-setting abilities** (Drizzle/Drought/Sand Stream/etc.) interact with
  ally abilities and ordering — verify only one application and correct ordering.
- Audit every `get_other_side()` call in `src/genx/abilities.rs` (many — see grep) for
  "should this be both opponents / include the ally?".
- **Trick Room**, **Tailwind**, weather turn counters: confirm they're decremented once
  per turn, not once per active slot, now that there are 4 slots in end-of-turn.

---

## 5. Search / decision layer

- **MCTS (`src/mcts.rs`)**:
  - `children` map key is a **3-tuple** `(usize, usize, usize)` (`mcts.rs:112`) but the
    code builds **5-tuples** `(node, s1_1, s1_2, s2_1, s2_2)` (`mcts.rs:123`) — type
    mismatch (`E0308`). The whole children-keying scheme must move to 4 move-indices.
  - `expand()` references undefined `s1_1_mc_index … s2_2_mc_index` at `mcts.rs:191`
    (should use the `*_move_index` params).
  - **Backpropagation** (`mcts.rs:196`) splits the score as `score` vs `1.0 - score`
    for two players. With 4 slots across 2 teams, the two **allies on a team must share
    the same team score**; verify the four `MoveNode` updates assign team-correct values.
  - `MctsResult` (`mcts.rs:280`) still exposes `s1`/`s2`; needs four option lists
    (or two, keyed by team but reporting both slots).
- **`src/mcts_threaded.rs`** (new, untracked file) is still entirely 2-side
  (`options.s1`/`options.s2`, `MctsResult { s1, s2 }`, 2-arg `generate_instructions_from_move_pair`).
  Either port it to 4 slots or exclude it from the build until ready.
- **`src/search.rs`** (alpha-beta / iterative deepening) is still 2-side: undefined
  `next_turn_side_two_1_options`, `side_two_options`, `worst_case_this_row`; returns
  2-tuples where 4 are expected; iterates over a `MoveChoice` as if it were a list
  (`search.rs:181`). Decide whether to keep this path or rely on MCTS only for doubles.

---

## 6. I/O, bindings, and the Python side

- **`src/io.rs`**: pervasively references `state.side_one`/`state.side_two`,
  `MctsResult.s1`/`.s2`, and calls the option/instruction functions with the old 2-arg
  arities (~40 errors). Printing, serialization round-trips, and the CLI command parsing
  all need to handle 4 slots.
- **State (de)serialization**: `State::serialize`/`deserialize` (`src/state.rs:2179`,
  `2379`) already use 4 sides (`=`-separated). Confirm the foul-play side and any saved
  fixtures match the new 4-side format.
- **Rust↔Python binding (`poke-engine-py/src/lib.rs`)** and the `.pyi` /
  `__init__.py` (`poke-engine-py/python/poke_engine/`): the constructor, `get_all_options`,
  and the MCTS result type must expose 4 slots. These are modified in the working tree —
  finish and keep them in sync with the Rust `MctsResult` shape.
- **foul-play (Python client)**: `fp/battle.py`, `fp/battle_modifier.py`,
  `fp/run_battle.py`, `fp/search/*` are modified to talk doubles to Showdown. Needs an
  end-to-end pass once the engine compiles: request parsing (each turn Showdown asks for
  2 choices per player, with target indices), and mapping Showdown target slots
  (`+2`/`-1` etc.) to engine `MoveChoice` targets.

---

## 7. Evaluation & win condition

- **`battle_is_over()` (`src/state.rs:1297`)** is already updated: a team loses only
  when **both** of its slots' full rosters are fainted. Good — just verify it's called
  after every faint and that "one of two actives down but reserves remain" forces a
  switch rather than ending the game.
- **`evaluate()` (`src/genx/evaluate.rs:159`)** appears extended to sum all four sides —
  audit that it doesn't double-count shared side conditions and that the sign/scale is
  still team-relative (Team One positive, Team Two negative).
- **Forced switches**: when one slot faints mid-turn the engine must request a single
  replacement for that slot without re-requesting the surviving ally's action. The
  `force_switch` plumbing in option generation (`state.rs:1115`) handles per-slot flags;
  verify the mid-turn (not just start-of-turn) faint path.

---

## 8. Other generations

`gen1`, `gen2`, `gen3` (`src/gen{1,2,3}/`) are **still singles** (2-tuple
`get_all_options`, 2-arg `generate_instructions_from_move_pair`, 2-variant
`SideMovesFirst`). Decide scope:
- If doubles is genx-only, ensure the older gens still compile against the shared
  `State`/`SideReference` (they reference the now-4-variant types) and are gated so they
  don't pull singles assumptions into the doubles build.
- The shared `state.rs` types are used by all gens, so widening `SideReference`/`State`
  already affects them.

---

## 9. Tests

- `src/state.rs` doctests and the `#[cfg(test)]` blocks still use `state.side_one` /
  `state.side_two` and 2-side `SideMovesFirst` (e.g. `generate_instructions.rs:7511`,
  `9074+`; `state.rs` doc comments at `2362+`). All need migrating to the 4-slot API.
- `tests/test_battle_mechanics.rs` and `tests/test_gen3.rs` (modified) will need a
  doubles harness: a helper to build a 4-slot `State` and assert per-target outcomes.
- Add new tests specifically for: turn order across 4 actors (incl. Trick Room &
  priority), spread-move 0.75× damage, redirection, Wide/Quick Guard, and ally-target
  moves.

---

## Suggested order of attack

1. **§0** — get it compiling again (mechanical fixes + restore constants).
2. **§2 + §1** — `SideReference` helpers, then the speed/turn-order rewrite (unblocks the
   core engine loop). Start with priority+speed sort ignoring redirection.
3. **§3** — add targets to `MoveChoice`, fix option generation and single-target
   execution; then spread moves and redirection.
4. **§5** — MCTS keying/backprop for 4 slots (search.rs/mcts_threaded can come later).
5. **§6** — io + bindings + foul-play end-to-end.
6. **§4, §7, §9** — ability/field correctness, evaluation audit, and tests throughout.
