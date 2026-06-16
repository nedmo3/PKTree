# Doubles — Step 3b Summary: Execution honors the chosen target

Targeting is now **behaviorally active**: a single-target move's damage and effects land on
the slot the player/AI chose (`DiagonalOpponent` vs `OtherOpponent`), not just the diagonal
opponent. Both crates still compile (0 errors), and a new integration test passes.

## ✅ Runtime-validated
`tests/doubles_targeting.rs` (run: `cargo test --features gen9 --test doubles_targeting`):
- side_one_1 + `DiagonalOpponent` → damages **SideTwo_1** (not SideTwo_2).
- side_one_1 + `OtherOpponent` → damages **SideTwo_2** (not SideTwo_1).
- side_one_2 mapping: diagonal = SideTwo_2, other = SideTwo_1.

(The `--test` form builds only this file against the normal lib, so it runs despite the
not-yet-migrated in-crate `#[cfg(test)]` modules.)

## Mechanism
- Added two `State` accessors (`src/state.rs`):
  - `get_both_sides_with_target(attacker, target)` — mutable (attacker, chosen target).
    Panics if `attacker == target` (never valid for a single-target move).
  - `get_both_sides_immutable_with_target(attacker, target)` — shared (safe even if equal).
- `Choice.target_side` (set at move-resolution time from the `RelativeTarget`) is now the
  single source of truth for "the defender".
- **Normalization guard** at the top of `generate_instructions_from_move`: if
  `choice.target_side == attacking_side` (internal generators like sleep talk leave the
  default), it's reset to the diagonal — prevents an attacker-targets-self panic.

## Paths wired to the chosen target
- **Damage calculation** (`damage_calc.rs::calculate_damage`) — defender stats, types,
  screens (Reflect/Light Screen/Aurora Veil).
- **Defender ability/item damage modifiers** — `ability_modify_attack_against`,
  `item_modify_attack_against`, `ability_modify_attack_being_used` (Levitate, Thick Fat,
  Absorb Bulb, etc.).
- **Damage application** (`generate_instructions_from_damage`) — HP loss, substitute,
  Focus Sash/Sturdy/Endure, Destiny Bond.
- **Kill/crit branch** + **PP/Pressure** checks.
- **Direct move effects** — status, boosts, heal, volatile statuses, and secondary effects
  (`get_instructions_from_{status_effects,boosts,heal,volatile_statuses}` gained a
  `target_side` parameter; secondaries pass `attacker_choice.target_side`).
- **After-hit abilities** (`ability_after_damage_hit`) — Moxie/Beast Boost/Magician on the
  attacker; Rough Skin/Iron Barbs/Berserk/Stamina/Color Change/Gulp Missile/Cotton Down on
  the (chosen) defender.
- **After-hit move effects** (`choice_after_damage_hit`) — Knock Off, Thief, Brick
  Break/Raging Bull/Psychic Fangs (screen clear), Clear Smog.
- **1v1 damage helper** (`calculate_damage_rolls`) sets `target_side` to the diagonal so the
  debug/CLI/`calculate_damage` Python path stays correct.

## Still resolves against the diagonal (documented gaps, not regressions)
- **Spread moves** (`MoveTarget::Opponents`/`All`: Earthquake, Boomburst, Dazzling Gleam…)
  still hit only one slot (the stored don't-care `DiagonalOpponent`). Proper spread
  targeting + the 0.75× multiplier + Wide Guard is future work (Step 3 "mechanics" / a new
  task). No behavior change vs. before.
- **Pre-move checks** in `before_move`/`cannot_use_move` and some move-specific tweaks in
  `choice_special_effect`/`choice_before_move` (e.g. Barb Barrage reading the defender's
  status, Protect detection) still read the diagonal opponent. These are niche per-move
  reads; the damage-determining paths above are the important ones and are done.
- **Redirection** (Follow Me / Lightning Rod / Storm Drain) is not implemented.

## Notes for going forward
- The `get_both_sides_with_target` panic-on-equal is a deliberate invariant tripwire. If a
  new internal move generator is added, make sure it either sets a real `target_side` or
  relies on the normalization guard.
- When spread moves are implemented, they should iterate the target set rather than reading
  `choice.target_side`; the option-gen already collapses them to a single option.
