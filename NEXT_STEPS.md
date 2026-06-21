# Next Steps — Problem List (post first full battle)

Status: a full doubles multi-battle played through end-to-end. Decisions were decent.
This is a **problem inventory only** — no solutions proposed. Roughly grouped; the two
priority items are first.

---

## Priority 1 — Runtime speed (master/worker lockstep)

- The master and worker advance in lockstep: each master loop iteration blocks on
  `request_queue.get()` (10s timeout) before processing, so the master only reads from its
  websocket as fast as the worker hands over a request. This throttles how fast either bot
  drains server messages and makes turns feel slow.
- `process_battle_updates` (which flushes all buffered public messages) only runs when the
  **master** receives its own `request`. Public events pile up in `battle.msg_list` until
  then, so message application is bursty/delayed rather than streaming.
- On a `request_queue.get()` timeout the master logs "Timed out waiting for request" and
  proceeds — i.e. it can act without the worker's latest state. Unclear how often this fires
  and whether it ever causes acting on stale info.
- `command_queue.put(None)` is used as a "nothing to do" signal; the back-and-forth of
  None/real commands between the two coroutines is intricate and a likely source of stalls.

## Priority 2 — Search quality / parameters

- Revisit MCTS search parameters (time/iteration budget, exploration constant, rollout
  depth) — current settings make "decent" but probably improvable decisions.
- `mcts_threaded` is **stubbed**: the threads argument is ignored, so search is effectively
  single-threaded. Real parallel search would raise the iteration budget within the same
  wall-clock time.
- No measurement yet of how many iterations/visits the search actually completes per move
  under the live time budget — can't tune what isn't measured.
- Evaluation/scoring function not yet reviewed for doubles (e.g. does it value both allies,
  spread threats, positioning) — may bias decisions.

---

## Integration / state-tracking (foul-play)

- **Buffered-flush staleness (broader than the active bug just fixed).** Because the master
  only flushes `battle.msg_list` on its own request, the ally's (and opponents') HP, status,
  boosts, volatiles, and switches can all lag the worker's authoritative `request_json` the
  same way the active pokemon did. Only the active-pokemon mismatch was patched (resync);
  the rest may silently desync.
- **Ally-active resync logging.** `update_from_request_json` now logs
  "Active drifted … resyncing" on mismatch. Need to confirm it fires ~once per forced switch,
  not every turn — every-turn firing would indicate a `|switch|`/`|drag|`/`|replace|`
  routing or flush-timing problem still present.
- **Prior "applied" fixes were missing from disk.** The ally-resync and the `ally`-threaded
  `_initialize_user_active_from_request_json` that a previous session believed were applied
  were **not** in `battle.py`. Other fixes from earlier sessions may likewise be absent or
  reverted — the foul-play changes need an audit against what's actually on disk.
- **Target-location mapping unverified live.** `_showdown_target_loc` foe-reversal
  (opponent_1→+2, opponent_2→+1, user_1→-1, user_2→-2 in `run_battle.py`) is a guess; not
  confirmed against real Showdown target numbering. Wrong values would mis-target moves.
- **Logging bug.** `run_battle.py` ~line 652: `logger.warning("nothing for master to do",
  battle.user_1.rqid)` passes rqid as a stray positional arg (no format placeholder) — the
  value is dropped / mis-logged.
- **Worker compute path is dead.** `pokemon_battle_reader`'s `async_pick_move` call is
  commented out; the worker relies entirely on the master computing both moves. Confirm the
  worker never needs to decide independently (e.g. desync recovery, master crash).

## poke-engine (Rust)

- **Encore fix not live yet.** The `move_has_no_effect` target fix is in source but the gen9
  wheel has **not** been rebuilt/reinstalled, so the running engine still has the old
  behavior.
- **Silent Encore fallback.** The `_ =>` arm in the Encore-forcing block was changed from a
  spammy `println!` to silently leaving the move unchanged. If foul-play ever serializes an
  ENCORE volatile onto a pokemon whose tracked `last_used_move` is none/switch, the engine
  now ignores encore without warning — the foul-play side tracking of `last_used_move` +
  encore in doubles is unaudited.
- **Leftover debug prints.** `genx/state.rs` still has `println!` debug lines (~474 "Adding
  available moves…", ~1137/1144 "No options available…") that flood stdout and slow MCTS.
- **Empty-option-set path exists.** The "No options available for side …" guard fires in
  some states; it's defended against (non-empty option vec guaranteed) but the underlying
  reason a slot produces zero options isn't understood.
- **Gen-feature coupling.** The crate must be built with `--features gen9`; building without
  it makes constants look "missing" and the engine look broken. Easy footgun.
- **encore duration not reset on switch.** When ENCORE is removed in
  `remove_volatile_statuses_on_switch`, `volatile_status_durations.encore` is not zeroed
  (minor state inconsistency).
- **Engine doubles behavioral gaps** (full detail in `poke-engine/DOUBLES_REMAINING.md`):
  - Spread moves hit only one slot; no 0.75× multiplier; no ally-hitting variants.
  - No redirection (Follow Me / Rage Powder / Lightning Rod / Storm Drain).
  - Wide Guard / Quick Guard / Crafty Shield / Mat Block defined but no logic consumes them.
  - No ally-targeting moves/abilities (Helping Hand, Decorate, Friend Guard, Battery, …);
    `MoveTarget` has no `Ally` class.
  - Intimidate hits one opposing active, should hit both.
  - Per-team side conditions: clear/decrement paths (Defog, Rapid Spin, Court Change, screen
    breaks, end-of-turn screen/Tailwind ticks) not mirrored to both ally slots → desync.
  - ≤3-bench enforcement relies on unused slots being inert rather than being explicit.
  - Remaining diagonal-target reads in `before_move`/`cannot_use_move`/`choice_special_effect`.
  - U-turn / Baton Pass / Shed Tail block is hard-coded per slot (one arm marked incorrect).
  - `add_end_of_turn_instructions` has a duplicated `side_one_1.force_switch` check that
    should be `side_one_2`.

## Tests

- `cargo test --features gen9` does **not** compile: in-crate `#[cfg(test)]` modules and
  `tests/test_battle_mechanics.rs` still use the old 2-side API. Only standalone integration
  tests run (via `--test <name>`, as `tests/doubles_targeting.rs` does).
- No doubles regression coverage yet for: spread 0.75×, redirection, Wide/Quick Guard,
  per-team side conditions, turn order (priority / Trick Room), Encore targeting.
- No foul-play-side tests for the multi-battle message routing / resync logic.
