# Doubles — Step 1 Summary: Foundation

Scope: §0 mechanical compile fixes + §2 `SideReference` helpers + `MoveTarget` targeting
plumbing. Status: **complete and verified** (no new errors at any edited site; total
compile errors dropped 122 → 113 with `--features gen9`).

## ⭐ Key finding: the "missing constants" were never missing
The ~40 `cannot find value WEATHER_ABILITY_TURNS / CRIT_MULTIPLIER / BASE_CRIT_CHANCE …`
errors were an artifact of building **without a generation feature**. Those constants are
`#[cfg(feature = "gen3..gen9")]`-gated, and `default = []` in `Cargo.toml` selects none.
- **Always build/test genx with a gen feature**, e.g. `cargo check --features gen9`
  (the Python crate uses `poke-engine/gen4`).
- **Do NOT add the constants back ungated** — that would cause duplicate-definition
  errors the moment a gen feature is active. Nothing was added.
- Same story for the earlier-reported `destinybond_before_move` and several other
  "missing" symbols: they resolve once a gen feature is set.

## Changes made
- **`src/choices.rs`** — fixed the `BOOMBURST` definition: missing comma after
  `target: MoveTarget::All` (this single syntax error was cascading).
- **`src/state.rs` (`SideReference` impl)** — added doubles helpers:
  - `get_ally()` → partner slot.
  - `get_other_sides() -> Vec<SideReference>` → both opposing slots (full opposing team).
  - `get_own_sides() -> Vec<SideReference>` → self + ally.
  - `is_allied_with(&other)` → same-team check.
  - documented `get_other_side()` as the 1:1 diagonal (singles) mapping.
  - *Return type is `Vec`, not `[_;2]`, on purpose:* the call sites iterate by value and
    the crate is edition 2018, where array-by-value `for` iteration is a footgun.
- **`src/genx/generate_instructions.rs`**:
  - `generate_instructions_from_increment_side_condition` /
    `generate_instructions_from_duration_side_conditions` — qualified `Opponents` →
    `MoveTarget::Opponents`; these now apply across `get_other_sides()`/`get_own_sides()`
    (team-wide mirroring — see "Carry-over" below).
  - `get_instructions_from_volatile_statuses` — replaced the `!todo()` stub with a real
    `Vec<SideReference>` target list so `Opponents` (both opponents) and `All`
    (self+ally+both opponents) work; `Opponent` still maps to the diagonal as a
    placeholder.
  - `get_instructions_from_secondaries` (RemoveItem secondary) — replaced an illegal bare
    `return` (E0069 in a `Vec`-returning fn) with a diagonal-opponent fallback for
    `All|Opponents`.

## Verification
- `cargo check --features gen9`: all Step-1 error sites resolved; no new errors at the
  edited code or the new helpers. Remaining errors belong to later steps.
- Full-crate compilation is still blocked by Steps 3 (`add_actions_for_slot` /
  option-gen), 4 (`moves_first` / turn resolution), 5 (search/mcts), 6 (io/bindings), so
  tests can't run yet — see `DOUBLES_TESTS.md`.

## Carry-over / things to keep in mind
- **Side conditions are mirrored, not yet truly shared.** Application now writes a layer to
  *both* ally slots (team-wide). **Step 2 must mirror the same way on every CLEAR/DECREMENT
  path** (Defog, Rapid Spin, Court Change, Reflect/Tailwind timer expiry, Aurora Veil) or
  the two ally slots will desync. The long-term-cleaner option is a per-team struct.
- **Single-target `MoveTarget::Opponent` still means "diagonal opponent"** across volatile
  statuses, secondaries, etc. Step 3 (MoveChoice gains a target) must replace these with
  the attacker's *chosen* target. Grep for `TODO(doubles/targeting)` to find them.
- Several `match _.target` arms (status/boost/heal secondaries at
  `generate_instructions.rs` ~847/995/1154) still `return` on `All|Opponents`. They
  compile (unit-returning fns) but silently skip spread effects — Step 3 cleanup.
- The U-turn / Baton Pass / Shed Tail block (~`generate_instructions.rs:3685-3870`) is
  hard-coded to `SideOne_1`/`SideTwo_1` and has leftover `state.side_two` (no-slot)
  references. That's move-execution slot-migration — folded into Step 3/4.
