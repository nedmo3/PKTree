# Doubles — Test Plan

A focused (deliberately small) set of tests that cover the doubles conversion work.
Organized by implementation step. Keep this lean — add a test only when it pins down
behavior that could plausibly regress.

> **Build note:** always test genx with a generation feature, e.g.
> `cargo test --features gen9`. A bare `cargo test`/`cargo check` compiles **no**
> generation (the gated constants disappear) and produces ~40 spurious "missing constant"
> errors. This is *not* a real problem — it's just a missing `--features` flag.

**Status:** the engine + Python binding now **compile** (`cargo check --features gen9` →
0 errors). The remaining blocker for *running* tests is that the in-crate `#[cfg(test)]`
modules and `tests/*.rs` still use the old 2-side API, so `cargo test` won't build until
those are migrated to a 4-slot state builder (Step 9). New doubles tests below should be
written against the 4-slot API.

Legend: ⛔ blocked until the **test modules** are migrated (Step 9). Tests are marked
"trivial" where the logic is pure and only needs the build to go green.

---

## Step 1 — Foundation (`SideReference` helpers, `MoveTarget` targeting)

### `SideReference` helpers — `src/state.rs` (⛔ trivial; pure functions)
1. **`get_other_side`** diagonal mapping: `SideOne_1↔SideTwo_1`, `SideOne_2↔SideTwo_2`.
2. **`get_ally`**: `SideOne_1↔SideOne_2`, `SideTwo_1↔SideTwo_2`.
3. **`get_other_sides`** returns the *two* opposing slots for each of the 4 references
   (e.g. `SideOne_1 → [SideTwo_1, SideTwo_2]`).
4. **`get_own_sides`** returns self + ally for each reference.
5. **`is_allied_with`**: true within a team (incl. self), false across teams.

### Per-team side conditions via targeting (⛔ needs engine compiling)
6. A **hazard** move (e.g. Spikes / Stealth Rock, `target: Opponents`) used by
   `side_one_1` adds the layer to **both** `side_two_1` and `side_two_2`'s
   `side_conditions` (mirrored = team-wide). Re-check with Step 2.
7. A **screen** move (Reflect / Light Screen, `target: User`) used by `side_one_1`
   applies to **both** `side_one_1` and `side_one_2`.

### Volatile-status targeting (⛔)
8. A single-target volatile move (`target: Opponent`) applies to the diagonal opponent
   only (placeholder until Step 3 wires the chosen target).
9. A spread volatile move (`target: Opponents`) applies to both opposing actives.

---

## Step 2 — Per-team side conditions + ≤3 bench  *(planned)*
10. Setting then **clearing** a team side condition (Defog / Rapid Spin / timer expiry)
    removes it from **both** ally slots (no desync).
11. Switch-option generation never offers bench indices ≥ the team's ≤3 limit; empty
    bench entries are treated as fainted/absent.

## Step 3 / 3b — MoveChoice targeting + spread
> **Done & tested:** execution honors the chosen target (Step 3b). See
> **`tests/doubles_targeting.rs`** — run `cargo test --features gen9 --test doubles_targeting`
> (3 tests passing). These bypass the not-yet-migrated in-crate test modules via `--test`.
12. ✅ **PASSING** (`doubles_targeting.rs`) — single-target damage lands on the chosen
    opponent slot (`DiagonalOpponent` → SideTwo_1, `OtherOpponent` → SideTwo_2), validated
    from both side_one_1 and side_one_2 perspectives.
12b. (todo) `get_all_options` yields a distinct option per **living** opponent for a
    single-target move; one option when only one opponent is alive.
13. A **spread** move hitting 2 targets applies the **0.75×** multiplier; hitting 1
    target (ally fainted) does not.
14. A self/ally-target move collapses to a single option (no per-opponent duplication).

## Step 4 — Speed / turn order  *(planned)*
15. With 4 distinct speeds and equal priority, action order is strictly speed-descending.
16. **Priority** beats speed: a +1 priority move from the slowest slot acts before faster
    neutral-priority moves.
17. **Trick Room** reverses the order (slowest acts first).
18. A switch resolves before any move regardless of speed.

## Step 5 — MCTS / search  *(planned)*
19. `perform_mcts` runs N iterations on a 4-slot root without panicking and returns four
    non-empty option lists.
20. Backprop sign: both team-two slots (`s2_1`, `s2_2`) receive `1.0 - score`
    (regression guard for the `s2_1` bug).

## Step 6 — io / bindings  *(planned)*
21. `State::serialize` → `deserialize` round-trips a 4-slot state unchanged.
22. Python `mcts()` on a 4-slot state returns results for all four slots.

---

### Existing test suites to re-green (run with `--features gen9`)
- `tests/test_battle_mechanics.rs` — needs a doubles state builder; expect to migrate
  `state.side_one/side_two` usages.
- genx in-module `#[cfg(test)]` blocks in `generate_instructions.rs` / `damage_calc.rs`.
