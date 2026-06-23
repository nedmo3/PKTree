This project uses 3 open source repositories to simulate Battle Tree Super Multi Battles from Pokemon Sun/Moon
 - [foul-play](https://github.com/pmariglia/foul-play)
    - Controls the bots who actually play the match and communicate with the server. It also reads from the list of Battle Tree trainers/pokemon to initialize random teams to play against. Written in Python. 
 - [poke-engine](https://github.com/pmariglia/poke-engine)
    - The engine for searching through pokemon battles, written in Rust. The original poke-engine is singles only. I've modified that (imperfectly) to work for doubles battles. 
      It is far from perfect, but currently functional.
 - [pokemon-showdown](https://github.com/smogon/pokemon-showdown/tree/master)
    - You can run a custom showdown server very easily. This one basically just adds the Gen 7 Multi Battle format

## Quick start
1. Follow [these instructions](https://github.com/smogon/pokemon-showdown/blob/master/server/README.md) to get your Showdown server running. Once set up, you can start your server with `node pokemon-showdown`. It listens on `http://localhost:8000` by default.

2. **Build & install the doubles `poke-engine`.** The engine is a Rust crate exposed to Python through [maturin](https://github.com/PyO3/maturin). It must be compiled for a single generation — this project runs on the `gen9` feature.

   ```bash
   cd poke-engine/poke-engine-py
   pip install -r requirements.txt          # installs maturin
   maturin build --release --no-default-features --features "poke-engine/gen9"
   pip install --force-reinstall --no-deps target/wheels/poke_engine-*.whl
   ```

   `--no-default-features` is required because the default feature is `gen4`; leaving it on would compile two generations at once and fail. Re-run this step any time you change Rust code (see [Rebuilding the engine](#rebuilding-the-engine-after-changes)).

3. **Install `foul-play`'s Python dependencies.** Requires Python 3.11+.

   ```bash
   cd foul-play
   pip install -r requirements.txt
   ```

4. **Create the two bot accounts.** The multi-battle setup runs *two* bots on your team (a master and a worker — see [How it works](#how-it-works)), so you need two usernames. On a server started with `node pokemon-showdown` (no auth), accounts are created on first login — just pick two names/passwords and use them below.

5. **Run the bots and accept the challenge.** From `foul-play/`:

   ```bash
   python run_multi.py \
     --websocket-uri ws://localhost:8000/showdown/websocket \
     --bot-mode challenge_user \
     --user-to-challenge YOUR_SHOWDOWN_NAME \
     --pokemon-format gen9multirandombattle \
     --bot1-username treebot1 --bot1-password pw1 \
     --bot2-username treebot2 --bot2-password pw2
   ```

   Then open `http://localhost:8000` in a browser, log in as `YOUR_SHOWDOWN_NAME`, and accept the incoming challenge. The two bots will take it from there.

## Prerequisites
- **Python 3.11+** (foul-play and the engine bindings)
- **Rust** via [rustup](https://rustup.rs/) (to build poke-engine)
- **Node.js 18+** (to run the Showdown server)
- **maturin** (`pip install maturin`, also pulled in by step 2's requirements)

## Repo layout
```
PKTree/
├── foul-play/         # the bots: connect to the server, run the search, pick moves
│   ├── run_multi.py   # entry point for the 2-bot multi battle
│   ├── team_maker.py  # builds teams from the Battle Tree CSVs
│   └── fp/            # battle state, message handling, search glue
├── poke-engine/       # Rust battle simulator + MCTS search (doubles-modified)
│   └── poke-engine-py # the Python bindings you build in step 2
└── pokemon-showdown/  # the local server the bots and you connect to
```

## Choosing a format
- **`gen9multirandombattle`** — quick way to test: the server hands both sides random teams, so no team setup is needed. This is the format in the run command above.
- **The Battle Tree format** — uses fixed trainer teams read from `foul-play/TreeTrainersAl.csv` / `TreePokemonAll.csv`. Pass the custom format with `--pokemon-format <gen7-multi-format>` and pick which round of the Tree the opponents come from with `--round N`. `team_maker.py` samples two trainers for that round and gives each bot a team.

## Configuration & tuning
All options are command-line flags (`python run_multi.py --help` for the full list). The ones that matter most for play quality:

| Flag | Default | What it does |
|---|---|---|
| `--search-time-ms` | `2000` | MCTS time budget per sampled battle (per "determinization"). Higher = stronger, slower. |
| `--search-parallelism` | `1` | Number of opponent-team guesses searched (in parallel). Against a human with an unknown team, raise this toward your core count for more robust decisions. |
| `--smogon-stats-format` | `gen7doublesou` | Which Smogon usage stats are used to predict the opponent's unknown sets/items/moves. |
| `--round` | `None` | Battle Tree round number, selects which trainers the opponents are drawn from (Tree format only). |

## How it works
A multi battle has two players per side, so foul-play runs **two bot processes** that cooperate:
- **Master** (`bot1`) reads the full battle, runs the MCTS search over the 4-slot doubles state, and decides moves for *both* allied slots.
- **Worker** (`bot2`) relays its private request to the master and submits whatever move the master computes for it.

They coordinate over in-process queues, synchronizing only when a decision is actually needed. The master serializes the battle into the Rust engine (`poke-engine`), which searches move/target pairs and returns the best pair; foul-play translates those back into Showdown `/choose` commands (including doubles target numbers).

## Rebuilding the engine after changes
The installed `poke_engine` is a compiled wheel, so **Python changes to foul-play take effect immediately, but any change to Rust code under `poke-engine/` requires a rebuild**:

```bash
cd poke-engine/poke-engine-py
maturin build --release --no-default-features --features "poke-engine/gen9"
pip install --force-reinstall --no-deps target/wheels/poke_engine-*.whl
```

To run the in-crate Rust tests, always pass a generation feature, e.g. `cargo test --no-default-features --features gen9`.

## Troubleshooting
- **Engine constants "missing" / build errors about undefined items** — you didn't pass a gen feature, or you left `gen4` on. Build with `--no-default-features --features "poke-engine/gen9"`.
- **Bot connects but never challenges / can't log in** — check the websocket URI (`ws://localhost:8000/showdown/websocket`) and that both bot accounts can log in.
- **A single-target move hits the wrong opponent** — this was a target-numbering bug that has been fixed; if you see it again, the mapping lives in `fp/run_battle.py::_showdown_target_loc`.
- **`Could not retrieve Smogon stats` warning** — harmless; your format has no usage stats and it falls back to `gen7doublesou`.

## Known limitations
The doubles conversion of poke-engine is functional but incomplete — notably spread moves, redirection (Follow Me/Rage Powder), and Wide/Quick Guard are only partially modeled, so the AI mis-evaluates some positions. Remaining engine work is tracked in `poke-engine/DOUBLES_REMAINING.md`, and broader project to-dos in `NEXT_STEPS.md`.

