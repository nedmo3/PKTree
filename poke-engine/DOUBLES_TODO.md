# Doubles Conversion — Remaining Work (genx only)

Status as of the current branch. Scope is **genx only** — `gen1/2/3` are explicitly out
of scope (see §8). The data model has been widened from 2 sides to 4 (`side_one_1`,
`side_one_2`, `side_two_1`, `side_two_2`), but the turn-resolution engine, search,
bindings, and many per-move mechanics are still singles-shaped or stubbed. The crate
**does not compile** right now (`cargo check` → ~149 errors); a large fraction of those
errors are the concrete TODO items below.

Conventions assumed throughout:
- A `Side` now represents **one active slot**, not a player.
- Team One = `side_one_1` + `side_one_2` (allies). Team Two = `side_two_1` + `side_two_2` (allies).
- `SideReference` has 4 variants: `SideOne_1`, `SideOne_2`, `SideTwo_1`, `SideTwo_2`
  (`src/state.rs:13`).
- `get_other_side()` currently maps each slot to its *diagonal* counterpart
  (`SideOne_1 ↔ SideTwo_1`, `SideOne_2 ↔ SideTwo_2`, `src/state.rs:20`). This 1:1
  mapping is the singles assumption baked into nearly all move code — see §3.

---

## ✅ Resolved design decisions

1. **Roster / bench model — each ally slot owns its OWN bench of up to 3 Pokémon.**
   (Confirmed.) The two ally slots have **disjoint rosters** (3 + 3 = 6 per team, no
   shared bench). Consequences:
   - `battle_is_over()` (`src/state.rs:1297`) — checking that *both* ally rosters are
     fully fainted — is **correct** as written.
   - `evaluate()` (`src/genx/evaluate.rs:159`) summing all four rosters is **correct** —
     no double-count, because the rosters are disjoint.
   - Switching stays **independent per slot**: each slot switches only within its own
     ≤3 bench.
   - **New constraint:** the `pokemon: [Pokemon; 6]` array (`src/state.rs:355`) is now
     oversized — only up to 3 entries are real. Ensure unused entries (indices 3–5) are
     inert (fainted/`NONE`) so they're never offered as switch targets or counted by
     `add_switches` / team-preview option generation / `battle_is_over` / `evaluate`.

2. **Side-condition representation — PER-TEAM (shared).** (Confirmed.) Both allies share
   one set of side conditions (Reflect/Light Screen/Tailwind/hazards/Safeguard/etc.).
   - Currently `side_conditions` lives on each `Side` (`src/state.rs:998`) and damage calc
     reads it from the single defending slot (`src/genx/damage_calc.rs:593-657`).
   - **Refactor to per-team semantics:** either (a) move `side_conditions` to a per-team
     struct that both ally `Side`s reference, or (b) keep it per-`Side` but mirror every
     write to both ally slots and read from the correct slot consistently. (a) is cleaner
     and avoids drift. A single Spikes/Reflect use must apply **once** to the team and be
     visible when either ally is targeted.
   - The in-progress `get_own_sides()`/`get_other_sides()` loops in
     `generate_instructions_from_increment_side_condition` (`src/genx/generate_instructions.rs:530`)
     iterate both ally slots — with option (b) this would **double-apply** a layer; with a
     per-team struct it must apply once. Reconcile the loop with whichever representation
     you choose.

---

## 0. Blocking compile errors that aren't conceptually "doubles" work

Mechanical breakages (mostly a partially-applied edit) that prevent *any* progress; fix
first so the rest can be iterated on.

- **`src/choices.rs:1702`** — missing comma after `target: MoveTarget::All` in the
  `BOOMBURST` definition; causes a parser error that cascades. (`MoveTarget::All` is a
  new variant being introduced for spread moves — see §3.)
- ~~**Missing constants**~~ **RESOLVED — they were never missing.** The
  `cannot find value WEATHER_ABILITY_TURNS / CRIT_MULTIPLIER / BASE_CRIT_CHANCE / …`
  errors only appear when building **without a generation feature**. Those constants are
  `#[cfg(feature = "gen3..gen9")]`-gated and `default = []` in `Cargo.toml` selects none.
  **Fix: always build/test with a gen feature** — `cargo check --features gen9`
  (the Python crate uses `poke-engine/gen4`). **Do NOT add them back ungated** (would cause
  duplicate-definition errors when a gen feature is active). Same for the earlier-reported
  `destinybond_before_move` and similar — all resolve under a gen feature.
- **Local-variable typos / half-edits** in `src/genx/generate_instructions.rs`:
  `healing_wish_consumed` (~400), `damage_factor` (~3109), `damage_amount` (~3506).
- **`destinybond_before_move`** not found (`src/genx/choice_effects.rs:896`).
- **`!todo()`** used as an expression at `src/genx/generate_instructions.rs:645`
  (should be the `todo!()` macro, and ultimately real logic).
- **`return;` in a non-`()` function** at `src/genx/generate_instructions.rs:1108`.

After §0 the crate should compile (or be very close), making everything below testable
incrementally.

---

## 1. Speed / turn-order system  ★ (the headline item)

The entire ordering layer is stubbed and only understands 2 actors.

- **`SideMovesFirst` enum (`src/state.rs:138`)** still has only `SideOne`, `SideTwo`,
  `SpeedTie`. Doubles needs a full ordering over **all four** acting slots. **Recommended:
  retire this enum** and instead have the turn driver produce an **ordered `Vec` of the
  acting `SideReference`s** for the turn.
- **`moves_first()` (`src/genx/generate_instructions.rs:2589`)** is a stub returning the
  nonexistent `SideMovesFirst::SideOne_1`. Replace it with a function that returns an
  **ordered `Vec<SideReference>`** (retire `SideMovesFirst` entirely). Build it with this
  deliberately simplified scheme (per project decisions):
  1. Per-slot effective speed already exists: `get_effective_speed`
     (`src/genx/generate_instructions.rs:2494`) works on one slot — call it for all 4.
  2. For each acting slot compute one sortable key: **`priority * LARGE_CONST + speed`**,
     where `LARGE_CONST` exceeds any possible speed so the priority bracket always
     dominates. Sort the four slots by this key, **highest first** — and **this sorted
     order is the single source of truth for the turn.**
  3. **No speed-tie probability branching.** Break ties deterministically by list order
     (use a stable sort over a fixed slot ordering). We intentionally do **not** model the
     50/50 — it isn't crucial. This **removes the entire `SpeedTie` branch** (lines 4274+
     in `generate_instructions_from_move_pair`).
  4. **Trick Room:** simply **reverse the sorted list** when `state.trick_room.active` —
     no special-casing inside the comparator.
  5. **Pursuit:** **ignore** its "act before a switching target" special case — treat it
     as a normal-priority move.
  6. **Switches:** still resolve before moves; give switch actions a priority bracket
     above any move so they sort to the front of the key naturally.
  7. *(Optional / later)* speed-mutating pre-move items (Custap Berry, Quick Claw, Quick
     Draw, Lagging Tail / Full Incense) — fold into the priority/speed key when wanted.
     The old body pushed a `ChangeItem` instruction for Custap; not required for the
     initial version.
- **Turn resolution (`generate_instructions_from_move_pair`,
  `src/genx/generate_instructions.rs:4021`)** — this is where the new order is consumed:
  - The `moves_first(...)` call at **line 4223** passes 2 choices but the signature takes
    4 (`E0061`). Fix the call, then replace the 3-arm `match` (lines 4229–4327) — which
    still branches on `SideMovesFirst::SideOne/SideTwo/SpeedTie` and references the
    nonexistent `state.side_one`/`side_two` and `SideReference::SideOne/SideTwo` — with a
    **loop that executes the ordered actions one at a time**.
  - After **each** action, re-check the state: a slot may have fainted, been forced to
    switch, had its target faint (→ retarget or fizzle), or had its move disrupted. The
    current `handle_both_moves` (`src/genx/generate_instructions.rs:3929`) hard-codes
    exactly two actions (first mover + its `get_other_side()`); replace it with a
    general "execute action `i`, branch instructions, continue with action `i+1`"
    structure that threads the growing `Vec<StateInstructions>`.
  - **Tera/Mega for 4 slots**: the per-slot tera toggles (lines 4162–4201) are done, but
    `mega_evolve` is still called with `SideReference::SideOne/SideTwo` (lines 4203–4212)
    — fix to the 4 concrete slots.
  - **End-of-turn**: `add_end_of_turn_instructions` and the
    `force_switch`/`replacing_fainted_pkmn` guards (lines 4242–4319) are written for 2
    slots and reference old fields — extend to all 4, and ensure once-per-turn field
    effects (weather/Trick Room/Tailwind counters) tick exactly once, not once per slot.

> **Coupling note:** the turn loop you build here consumes `MoveChoice`, which currently
> carries no target (§3). You can build the loop first against the diagonal-opponent
> assumption, but it will need a small rework once targets are added. Consider settling
> the `MoveChoice` shape (§3 data model) **before or alongside** this section to avoid
> redoing the execution path.

---

## 2. `SideReference` helpers needed

Move code already calls methods that don't exist (compile errors at
`src/genx/generate_instructions.rs:538-539, 572-573`):

- **`get_other_sides()`** → the two opposing slots (e.g. `SideOne_1` → `[SideTwo_1, SideTwo_2]`).
- **`get_own_sides()`** → own team's slots (self + ally).
- Add **`get_ally()`** → the partner slot, and keep `get_other_side()` for the "slot
  directly across" notion where it's still meaningful.
- Decide the role of `get_other_side()` in doubles: it's used everywhere as "the
  defender," correct only in 1v1. Most single-target moves need an **explicit chosen
  target** instead (§3).

---

## 3. Move targeting (no target is currently encoded)

Second-biggest design gap after speed.

### Data model (CONFIRMED: relative target enum)
- Add a **`RelativeTarget`** enum (genx) with variants:
  `DiagonalOpponent`, `OtherOpponent`, `Ally`, `User`. Resolution against the attacker's
  `SideReference` `a`:
  - `DiagonalOpponent` → `a.get_other_side()`
  - `OtherOpponent`    → `a.get_other_side().get_ally()` (the opposing ally)
  - `Ally`             → `a.get_ally()`
  - `User`             → `a`
  Provide `RelativeTarget::resolve(&self, attacker: SideReference) -> SideReference`.
- **`MoveChoice` (`src/genx/state.rs:45`)** — add the target to the move variants:
  `Move(PokemonMoveIndex, RelativeTarget)`, `MoveTera(PokemonMoveIndex, RelativeTarget)`,
  `MoveMega(PokemonMoveIndex, RelativeTarget)`. `Switch`/`None` unchanged.
- **Option generation** emits target variants based on the move's `Choice.target`
  (`MoveTarget`):
  - `Opponent` → one option per **living** opposing slot (`DiagonalOpponent`, and
    `OtherOpponent` if alive). If only one opponent is alive, just that one.
  - `User` → single option, `RelativeTarget::User`.
  - `Opponents` / `All` (spread/field) → **single** option (no target choice); store a
    don't-care `RelativeTarget` (e.g. `DiagonalOpponent`) — execution derives the real
    target set from the move's `MoveTarget`, not from `RelativeTarget`.
  - `Ally`-targeting moves are deferred (current `MoveTarget` enum has no `Ally` class;
    add when those moves are implemented).
- **Blast radius is contained:** each gen has its own `MoveChoice`; only
  `src/genx/state.rs` (~17 sites) and `src/genx/generate_instructions.rs` (~12 sites) match
  `MoveChoice::Move`. `mcts.rs`/`search.rs`/`io.rs`/`lib.rs` treat `MoveChoice` opaquely
  (only `to_string`/`from_string`/clone/compare), so they need no per-site changes beyond
  the serialization of the new target in `to_string`/`from_string`.
- **`MoveTarget` (`src/choices.rs:19350`)** is gaining `All`/`Opponents` variants (used
  at `generate_instructions.rs:538, 572, 645`) but the matches are incomplete
  (`Opponents` unbound; `MoveTarget::All | Opponents => !todo()`). Finish the enum and
  every `match` over it.

### Option generation
- `add_actions_for_slot` is **declared with 4 params** (`src/genx/state.rs:1174`) but
  **called with 3** (`src/genx/state.rs:1147`) — compile error. It must take both
  opponents (and the ally), and emit one `MoveChoice` per legal (move, target) pair.
- Make sure single-target options enumerate both opponent targets; spread/self/ally moves
  emit a single option; status/field moves target appropriately.

### Move execution (currently single-target, diagonal)
- Execution resolves one defender via `attacking_side_reference.get_other_side()` —
  e.g. `generate_instructions.rs:643, 832, 980, 1139`; substitute handling at `1404`;
  and `get_both_sides()` (`src/state.rs:1328`) returns the attacker + its diagonal
  opponent. All of these must use the **chosen target** from `MoveChoice` instead of the
  hard-coded diagonal.

### New doubles mechanics (not yet implemented at all)
- **Spread damage**: multi-target moves (Earthquake, Rock Slide, Dazzling Gleam, …) deal
  **0.75×** when they hit >1 target. New damage path + multi-target resolution.
- **Moves that also hit the ally** (Earthquake, Surf, Discharge, Explosion, …).
- **Redirection**: Follow Me / Rage Powder / Lightning Rod / Storm Drain pull
  single-target moves to another slot. Resolve during targeting.
- **Doubles-only protection**: **Wide Guard**, **Quick Guard**, **Crafty Shield**,
  **Mat Block** — the `PokemonSideCondition` variants exist (`src/state.rs:30`) but no
  logic consumes them.
- **Ally-affecting effects/abilities**: Helping Hand, Beat Up, Instruct, Decorate,
  Coaching, Ally Switch; abilities **Friend Guard**, **Battery**, **Power Spot**.
- **Spread/side-condition application** must respect Resolved decision #2 (per-team
  side conditions): a single Spikes/Reflect use applies **once** to the team and is
  visible when either ally is targeted — don't apply it twice across the ally pair.

---

## 4. Abilities & field effects that change in doubles

- **Intimidate** should drop Attack on **both** opposing actives (currently single target
  via `get_other_side`, `src/genx/abilities.rs`).
- **Weather/Terrain-setting abilities** (Drizzle/Drought/Sand Stream/etc.) interact with
  ally abilities and ordering — verify single application and correct ordering.
- **Audit every `get_other_side()` call in `src/genx/abilities.rs`** (there are many) for
  "should this hit both opponents / the ally?".
- **Once-per-turn counters** (Trick Room, Tailwind, weather, Future Sight, Wish) must
  decrement once per turn in end-of-turn, not once per active slot.

---

## 5. Search / decision layer (MCTS)

`mcts.rs` `selection`/`expand`/`do_mcts`/`MctsResult`/`perform_mcts` are **already
widened to 4 move lists** — the remaining items are concrete bugs, not a full rewrite:

- **Children-map key is a 3-tuple** `(usize, usize, usize)` (`mcts.rs:112, 292, 313`) but
  selection builds a **5-tuple** `(node, s1_1, s1_2, s2_1, s2_2)` (`mcts.rs:123`) — type
  mismatch (`E0308`). Move the whole keying scheme to the four move-indices
  (`(node, s1_1, s1_2, s2_1, s2_2)`).
- **`expand()` references undefined `s1_1_mc_index … s2_2_mc_index`** at `mcts.rs:191`
  (should reuse the `*_move_index` params passed in).
- **Backprop sign bug** (`mcts.rs:202-220`): `s1_1`, `s1_2`, and **`s2_1`** all get
  `+= score`, while `s2_2` correctly gets `+= 1.0 - score`. Both **team-two** slots
  (`s2_1` and `s2_2`) must get `1.0 - score`; `s2_1` at line 214 is wrong. Confirm the
  team-relative convention and fix.
- `MctsResult` in `mcts.rs` already exposes `s1_1/s1_2/s2_1/s2_2` (`mcts.rs:280`) — good;
  the 2-field `s1/s2` problem is **only** in `io.rs` and `mcts_threaded.rs` (below).
- **`src/mcts_threaded.rs`** (new, untracked) — **NOT needed; stub or comment it out** of
  the genx build. It's still entirely 2-side and is only reached via the Python binding's
  `perform_mcts_shared_tree`. Also drop that call from `lib.rs` (have `mcts()` use the
  single-threaded `perform_mcts`) and remove the `use poke_engine::mcts_threaded::…`
  import (`lib.rs:15`).
- **`src/search.rs`** (alpha-beta / iterative deepening) — **in scope; widen to 4 slots.**
  Currently 2-side: undefined `next_turn_side_two_1_options`, `side_two_options`,
  `worst_case_this_row`; returns 2-tuples where 4 are expected; iterates a `MoveChoice` as
  if it were a list (`search.rs:181`). Update option handling, the worst-case/minimax
  bookkeeping, and the return shape to the 4-slot API.

---

## 6. I/O, bindings, and the Python side

- **`src/io.rs`** pervasively references `state.side_one`/`state.side_two`,
  `MctsResult.s1`/`.s2`, and the old 2-arg option/instruction arities (~40 errors). Update
  printing, the result formatters (`print_mcts_result`, `pprint_mcts_result`), state
  round-trips, and CLI parsing to 4 slots.
- **State (de)serialization** already uses 4 sides (`State::serialize`/`deserialize`,
  `src/state.rs:2179, 2379`, `=`-separated). Confirm foul-play and any saved fixtures
  match this format.
- **Rust↔Python binding (`poke-engine-py/src/lib.rs`) is still entirely 2-side** — this
  is a full widening, not a touch-up:
  - `PyState` holds `side_one`/`side_two` (`lib.rs:38`); needs 4 `PySide`s.
  - `PyMctsResult` maps only `s1`/`s2` from `state.side_one`/`side_two` (`lib.rs:853-905`);
    needs 4 slot results matching the Rust `MctsResult`.
  - `mcts()` destructures `root_get_all_options()` into **2** values (`lib.rs:912`) and
    calls `perform_mcts`/`perform_mcts_shared_tree` with 2 option args — but genx returns
    a **4-tuple** and `perform_mcts` takes 4. The `calculate_damage`/`gi` entrypoints
    (`lib.rs:1011+`) are likewise 2-side.
  - Keep the `.pyi` (`python/poke_engine/poke_engine.pyi`) and `__init__.py` in lockstep
    with the new 4-slot API (both are modified in the working tree).
- **foul-play (Python client)**: `fp/battle.py`, `fp/battle_modifier.py`,
  `fp/run_battle.py`, `fp/search/*` are modified for doubles. Needs an end-to-end pass once
  the engine compiles: each turn Showdown requests **2 choices per player with target
  indices**; map Showdown target slots (`+2`/`-1`/`-2` etc.) to engine `MoveChoice`
  targets, and handle mid-turn replacement requests for a single fainted slot.

---

## 7. Evaluation & win condition

Per Resolved decision #1 (disjoint ≤3 benches), the core logic here is **already
correct** — the work is smaller than the rest:

- **`battle_is_over()` (`src/state.rs:1297`)** — correct as written. Just verify the
  mid-turn path: when one slot faints but its reserves remain, force a **single-slot
  replacement**, not a game end or a re-request of the surviving ally's action.
- **`evaluate()` (`src/genx/evaluate.rs:159`)** — summing all four disjoint rosters is
  correct (no double-count). Two things to confirm once side conditions go per-team
  (decision #2): hazards/screens must **not** be counted twice for a team (e.g.
  `evaluate_hazards` is called per slot — make sure team-shared hazards aren't added once
  per ally). Also confirm the sign/scale stays team-relative (Team One positive, Team Two
  negative) and that the MCTS rollout's `sigmoid(eval - root_eval)` (`mcts.rs:226`) still
  behaves.
- **≤3 bench:** ensure empty bench entries don't contribute to the score.

---

## 8. Other generations (out of scope)

Per your direction, `gen1/2/3` are **not** being converted. They share the widened
`state.rs` types (`SideReference`/`State`), so they must still **compile** — either keep
them building against the shared types or feature-gate them out of the default/genx build.
No doubles behavior is expected from them.

---

## 9. Tests

- genx doctests and `#[cfg(test)]` blocks still use `state.side_one`/`state.side_two` and
  the 2-side `SideMovesFirst` (e.g. `generate_instructions.rs:7511`, `9074+`;
  `damage_calc.rs:947`; `state.rs` doc comments at `2362+`). Migrate to the 4-slot API.
- `tests/test_battle_mechanics.rs` needs a doubles harness: a helper to build a 4-slot
  `State` and assert per-target outcomes.
- Add new tests for: turn order across 4 actors (incl. Trick Room & priority brackets),
  speed-tie permutation branching, spread-move 0.75× damage, redirection, Wide/Quick
  Guard, ally-target moves, and shared-vs-separate side conditions (per decision #2).

---

## Suggested order of attack

1. **§0** — get it compiling again (mechanical fixes + restore constants).
2. **Side-condition refactor to per-team** (Resolved decision #2) + **enforce the ≤3
   bench** (Resolved decision #1) in switch/option generation. Roster/win-con/evaluate
   need no structural change — just the ≤3 cleanup.
3. **§2** — `SideReference` helpers (`get_other_sides`/`get_own_sides`/`get_ally`).
4. **§3 data model** — add targets to `MoveChoice`, finish `MoveTarget`, fix
   `add_actions_for_slot` option generation. (Settle this before §1's turn loop.)
5. **§1** — speed/turn-order rewrite + the 4-action turn loop in
   `generate_instructions_from_move_pair` (now executing against real targets). Start
   without redirection.
6. **§3 mechanics** — single-target execution via chosen target, then spread damage,
   redirection, doubles-only protects, ally effects.
7. **§5** — MCTS fixes (children key, `expand` vars, `s2_1` backprop sign); widen
   `search.rs` to 4 slots; stub/comment out `mcts_threaded.rs` and drop its binding call.
8. **§6** — `io.rs`, then the Python binding (`lib.rs` + `.pyi` + `__init__.py`), then
   foul-play end-to-end.
9. **§4, §7, §9** — ability/field correctness, evaluate/win-con audit, and tests
   throughout.

> Remaining item still **marked for your attention**: whether the missing constants in §0
> were intentionally removed during the refactor (verify against git history before
> re-adding).
