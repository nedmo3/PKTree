# Doubles — Step 5 + 6 Summary: Search/MCTS, io, and Python bindings

## ⭐ MILESTONE: the whole codebase compiles
- **Engine crate** (`poke-engine`, lib + bin): `cargo check --features gen9` → **0 errors**.
- **Python binding crate** (`poke-engine-py`): `cargo check` (gen4 default) → **0 errors**.

From the original 122 doubles errors (under a gen feature) down to **0**. Remaining
warnings are benign (a few unused vars). The crate could not be tested before because it
didn't build; it now does (test-module migration is still pending — see below).

## Step 5 — Search / MCTS
- **`mcts.rs`**:
  - Children-map key widened from a 3-tuple to a **5-tuple**
    `(node_ptr, s1_1, s1_2, s2_1, s2_2)` (4 declarations + the `expand` key).
  - `expand()` now uses its `*_move_index` params (the undefined `*_mc_index` names are
    gone).
  - **Backprop sign bug fixed**: `s2_1` now receives `1.0 - score` like `s2_2` (both
    team-two slots are scored from team two's perspective).
- **`search.rs`** (alpha-beta / iterative deepening) widened to 4 slots:
  - Fixed the `next_turn_side_twp_1_options` typo.
  - Rewrote `re_order_moves_for_iterative_deepening` to return **4** reordered option vecs
    (was 2) and fixed the mis-scoped `worst_case_this_row`; it now sorts (s1_1, s1_2) move
    pairs by worst-case score and derives a per-slot order (opposing slots pass through).
    This is a pruning heuristic only — it never affects search correctness.
  - `IterativeDeependingThreadMessage::Stop` now carries the 6-tuple the function returns.
- **`mcts_threaded.rs`**: **commented out** of the build (`pub mod mcts_threaded;` in
  `src/lib.rs`). It's the singles-only shared-tree MCTS; the engine uses the
  single-threaded `mcts::perform_mcts`. Its uses in `io.rs` and the binding were removed.

## Step 6 — io.rs + Python bindings
- **`src/io.rs`** ported to 4 slots: all `root_get_all_options()` call sites use the
  4-tuple; `expectiminimax`/`id`/`mcts` use the 4-option APIs; result printers iterate the
  four MCTS slot lists; `pick_safest` uses the 4-count signature. The
  `perform_mcts_shared_tree` import and the `mctsp` parallel command were removed.
  - **CLI simplification (documented in-file):** the debug CLI drives only the two `_1`
    slots from move inputs; the `_2` ally slots default to `MoveChoice::None`. The 4-D
    score matrix is printed flat rather than as a 2-D table.
- **`poke-engine-py/src/lib.rs`**:
  - `PyState` now has `side_one_1/side_one_2/side_two_1/side_two_2` (struct, `From`,
    `Into`, `new`). `PySide` is unchanged (it already maps 1:1 to a slot).
  - `PyMctsResult` exposes `s1_1/s1_2/s2_1/s2_2`; `PyIterativeDeepeningResult` exposes the
    four option lists + matrix + depth.
  - `mcts()` drops the threaded path (`threads` accepted but ignored); `generate_instructions()`
    now takes **four** move strings (one per slot); `id()` uses the 4-option API.
- **`poke-engine-py/python/poke_engine/__init__.py`**:
  - `MctsResult` and `IterativeDeepeningResult` dataclasses now carry four slot lists and
    read the new Rust fields. `IterativeDeepeningResult.get_safest_move()` returns the
    safest **(side_one_1, side_one_2) move pair** (worst-case over all opposing
    combinations), matching the Rust `pick_safest`.
- **`poke-engine-py/python/poke_engine/poke_engine.pyi`**: `State`, `MctsResult`,
  `mcts`, and `generate_instructions` signatures updated to the 4-slot API.

## What's NOT done (carry-over)
- **`Step 3b` — execution targeting is still cosmetic.** Damage/effects still resolve to
  the diagonal opponent; `DiagonalOpponent` vs `OtherOpponent` behave identically. This is
  the most important remaining correctness item.
- **`Step 6b` — foul-play client.** The binding now exposes the correct 4-slot API, but
  the Python client (`fp/*.py`) must be aligned and tested live against Showdown doubles
  (request parsing, target-slot mapping). Runtime work; not a compile issue.
- **`Step 2` — per-team side-condition clear/decrement mirroring + ≤3 bench enforcement.**
- **Tests (`Step 9`)** — in-crate `#[cfg(test)]` modules and `tests/*.rs` still use the
  old 2-side API, so `cargo test` won't compile yet. They need migration to the 4-slot
  builders before the test plan in `DOUBLES_TESTS.md` can run.
- **Trick Room** uses the speed-negation simplification (priorities/switches preserved);
  the hard-coded U-turn block is still partly wrong for doubles (flagged in `DOUBLES_STEP_3-4.md`).

## Verify
```
cd poke-engine && cargo check --features gen9      # engine: 0 errors
cd poke-engine/poke-engine-py && cargo check       # bindings: 0 errors
```
