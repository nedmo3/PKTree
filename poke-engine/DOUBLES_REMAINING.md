# poke-engine — Doubles: Remaining Work (checkpoint)

Scope: **only the Rust `poke-engine` crate** (genx). Build/test with a gen feature, e.g.
`cargo check --features gen9`. foul-play integration is tracked separately.

**State at this checkpoint:** engine + Python binding compile (0 errors). Done: Steps 1–6
(foundation, targeting data model, option-gen, speed/turn-order, search/MCTS fixes, io +
bindings) and Step 3b (execution honors the chosen target — damage, defender ability/item
modifiers, direct effects, after-hit abilities/effects; validated by
`tests/doubles_targeting.rs`). See `DOUBLES_STEP_*.md` for details.

The remaining items, roughly highest-value first:

---

## 1. Per-team side conditions + ≤3 bench  (was "Step 2")
- **Side conditions are still per-`Side`.** Decision was **per-team (shared)**. Application
  currently mirrors a layer to both ally slots via `get_own_sides()`/`get_other_sides()`
  (`generate_instructions_from_increment_side_condition` /
  `_duration_side_conditions`), but **clear/decrement paths are not mirrored**: Defog,
  Rapid Spin, Court Change, Brick Break/Raging Bull/Psychic Fangs screen-clears, and the
  end-of-turn timer ticks (Reflect/Light Screen/Tailwind/Safeguard/Aurora Veil) only touch
  one slot → the two ally slots desync. Either mirror every clear/decrement to both ally
  slots, or (cleaner) refactor `side_conditions` to a per-team struct both `Side`s share.
- **≤3 bench enforcement.** Each ally slot owns a disjoint bench of up to 3 (the
  `[Pokemon; 6]` array is oversized). Ensure unused entries stay inert so they're never
  offered as switches or counted by `add_switches` / team preview / `battle_is_over` /
  `evaluate`. (Today this relies on unused slots being fainted/`NONE` — make it explicit.)

## 2. Spread moves  (the biggest behavioral gap)
- Moves with `MoveTarget::Opponents` / `All` (Earthquake, Rock Slide, Dazzling Gleam,
  Boomburst, Discharge, Surf, Explosion, …) currently hit **only one slot** (the stored
  don't-care `DiagonalOpponent`). Need:
  - multi-target damage application (iterate the target set, not `choice.target_side`),
  - the **0.75× spread multiplier** when >1 target is hit,
  - ally-hitting variants (Earthquake/Surf/Discharge hit the user's ally too),
  - option-gen already collapses these to a single option, so the work is execution-side.

## 3. Redirection & doubles-only protection
- **Redirection:** Follow Me / Rage Powder / Lightning Rod / Storm Drain reroute
  single-target moves. Resolve during target resolution (before damage).
- **Doubles protects:** Wide Guard, Quick Guard, Crafty Shield, Mat Block — the
  `PokemonSideCondition` variants exist but no logic consumes them.

## 4. Ally-targeting moves & abilities
- Helping Hand, Beat Up, Instruct, Decorate, Coaching, Ally Switch; abilities Friend Guard,
  Battery, Power Spot. The `MoveTarget` enum has no `Ally` class yet — add it (and the
  `RelativeTarget::Ally` path is already defined in option-gen/resolution, just unused).

## 5. Ability / field correctness in doubles
- **Intimidate** should drop Attack on **both** opposing actives (currently single target).
- **Weather/terrain setters** (Drizzle/Drought/etc.) — verify single application + ordering
  with an ally that also sets weather.
- Audit remaining `get_other_side()` calls in `abilities.rs` (switch-in / end-of-turn /
  before-move paths) for "should this be both opponents / the ally?".
- Once-per-turn field counters (Trick Room, Tailwind, weather, Wish, Future Sight) must tick
  once per turn, not once per active slot — re-verify in `add_end_of_turn_instructions`.

## 6. Remaining diagonal-target reads (Step 3b leftovers)
These still resolve against the **diagonal** opponent rather than the chosen target. Niche,
but listed for completeness:
- `before_move` / `cannot_use_move` defender reads (Protect detection, type-immunity
  pre-checks).
- Move-specific reads in `choice_special_effect` / `choice_before_move` (e.g. Barb Barrage
  reading the defender's status).
- `get_instructions_from_secondaries` `All`/`Opponents` secondaries fall back to the chosen
  target (single), not the full set — folds into §2 (spread).

## 7. Known-incorrect / hard-coded spots to revisit
- **U-turn / Baton Pass / Shed Tail block** (`generate_instructions.rs` ~3600-3840) is
  hard-coded per slot; one arm carries a `// TODO this is incorrect`. Needs a slot-agnostic
  rewrite using `attacking_side` + the partner, plus correct
  `switch_out_move_second_saved_move` plumbing for all four slots.
- **`add_end_of_turn_instructions`** has a duplicated `side_one_1.force_switch` check that
  should be `side_one_2` (harmless today, fix when touching that function).
- **Charging moves / forced second moves** push `Move(idx, DiagonalOpponent)` because the
  target chosen on launch turn isn't persisted — revisit if 2-turn-move targeting matters.

## 8. Speed / turn-order polish (optional)
- Pre-move speed items not modeled: **Custap Berry, Quick Claw, Quick Draw, Lagging Tail /
  Full Incense**. Fold into the `move_order` key when desired.
- **Trick Room** uses speed-term negation (preserves priority/switch-first), not a literal
  full-list reversal — intended, but note it if exact behavior is ever questioned.

## 9. Tests (Step 9 — unblocks the suite)
- The in-crate `#[cfg(test)]` modules (`generate_instructions.rs`, `damage_calc.rs`) and
  `tests/test_battle_mechanics.rs` still use the **old 2-side API** (`state.side_one`,
  `SideReference::SideOne`, 2-arg `generate_instructions_from_move_pair`, etc.), so a full
  `cargo test --features gen9` does not compile. Migrate them to a 4-slot state builder.
  Until then, write new doubles tests as separate integration files and run with
  `--test <name>` (as `tests/doubles_targeting.rs` does) so they bypass the broken modules.
- Add coverage from `DOUBLES_TESTS.md`: option-gen per-living-opponent, spread 0.75×,
  redirection, Wide/Quick Guard, per-team side conditions, turn order (priority/Trick Room).

## Out of scope
- `gen1/2/3` remain singles. They share the widened `state.rs` types and currently compile;
  no doubles behavior is expected from them.
