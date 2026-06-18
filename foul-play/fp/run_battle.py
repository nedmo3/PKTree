import json
import asyncio
import concurrent.futures
from copy import deepcopy
import logging

from data.pkmn_sets import RandomBattleTeamDatasets, TeamDatasets
from data.pkmn_sets import SmogonSets
from data import all_move_json
import constants
from constants import BattleType
from config import BotModes, FoulPlayConfig, SaveReplay
from fp.battle import LastUsedMove, Pokemon, Battle
from fp.battle_modifier import async_update_battle, process_battle_updates
from fp.helpers import normalize_name
from fp.search.main import find_best_move

from fp.websocket_client import PSWebsocketClient

logger = logging.getLogger(__name__)


# Relative-target tokens the engine may append to a move string (empty = diagonal opponent).
_ENGINE_TARGET_TOKENS = ("opp", "opp2", "ally", "self")

# Showdown move "target" types that require choosing an explicit single target in doubles.
# Everything else (self, allAdjacent, allAdjacentFoes, all, allySide, foeSide, randomNormal,
# scripted, ...) is auto-resolved by Showdown and takes NO target number.
_SINGLE_TARGET_MOVE_TYPES = {
    "normal",
    "adjacentFoe",
    "any",
    "adjacentAlly",
    "adjacentAllyOrSelf",
}


def _split_engine_target(move_str: str):
    """Split a trailing engine relative-target token off a move string.

    Returns (move_without_token, token); token is "" when absent (diagonal opponent).
    """
    parts = move_str.rsplit(" ", 1)
    if len(parts) == 2 and parts[1] in _ENGINE_TARGET_TOKENS:
        return parts[0], parts[1]
    return move_str, ""


def _showdown_target_loc(token: str, battle, acting_user):
    """
    Translate the engine's relative target (for the acting allied slot) into a Showdown
    multi-battle target location number, or None if it can't be resolved.

    Field layout: own side.active = [user_1 / p1a, user_2 / p3b];
                  foe.active     = [opponent_1 / p2a, opponent_2 / p4b].
    Per Showdown's getAtLoc convention a foe at side-index i is targeted with
    loc = num_foe_active - i (foes are numbered in reverse), and an ally at index i with
    loc = -(i + 1). For a fixed 2v2 that yields:
        opponent_1 (p2a) -> +2,  opponent_2 (p4b) -> +1,
        user_1 (p1a)     -> -1,  user_2 (p3b)     -> -2

    NOTE: verify the foe reversal against a live `|error|` response. If foes turn out to be
    numbered left-to-right (p2a -> +1, p4b -> +2), swap the two foe return values below.
    """
    is_user_1 = acting_user is battle.user_1

    # Engine relative target -> absolute battler, given who is acting.
    if token in ("", "opp"):  # DiagonalOpponent
        target = battle.opponent_1 if is_user_1 else battle.opponent_2
    elif token == "opp2":  # OtherOpponent
        target = battle.opponent_2 if is_user_1 else battle.opponent_1
    elif token == "ally":
        target = battle.user_2 if is_user_1 else battle.user_1
    elif token == "self":
        target = battle.user_1 if is_user_1 else battle.user_2
    else:
        return None

    # Absolute battler -> Showdown target location.
    if target is battle.opponent_1:
        return "+2"
    if target is battle.opponent_2:
        return "+1"
    if target is battle.user_1:
        return "-1"
    if target is battle.user_2:
        return "-2"
    return None


def convert_mcts_choice_to_move_name(mcts_choice: str, active_pokemon) -> str:
    """
    Convert an MCTS choice string to an actual move name.
    
    MCTS can return choices in multiple formats:
    - Move names directly: "sacredsword", "thunderbolt", etc. (most common)
    - Move indices: "move 0", "move 1", "move 2", "move 3" (rare)
    - Move indices with modifiers: "move 0-mega", "move 1-tera"
    - Switches: "switch 1", "switch 2", etc.
    
    Args:
        mcts_choice: String from MCTS results
        active_pokemon: The Pokemon object whose moves to validate against
        
    Returns:
        Valid move name (e.g., "thunderbolt") or switch command
    """
    # Handle switches - pass through as-is
    if mcts_choice.startswith(constants.SWITCH_STRING):
        return mcts_choice
    
    # Extract modifiers (-tera, -mega) early
    modifiers = ""
    choice_for_processing = mcts_choice
    if mcts_choice.endswith("-tera"):
        modifiers = "-tera"
        choice_for_processing = mcts_choice[:-5]
    elif mcts_choice.endswith("-mega"):
        modifiers = "-mega"
        choice_for_processing = mcts_choice[:-5]
    
    # Case 1: Already a move name (most common from MCTS)
    # Move names don't start with "move ", and they're not all digits
    if not choice_for_processing.startswith("move "):
        # Assume it's already a move name - validate it exists on the active Pokemon
        if active_pokemon is None:
            logger.error(f"ERROR: No active Pokemon provided to validate move '{choice_for_processing}' - returning struggle")
            return "struggle"
        
        # Check if this move exists in the active Pokemon's moveset
        move_names = [m.name for m in active_pokemon.moves]
        if choice_for_processing in move_names:
            logger.info(f"MCTS move '{choice_for_processing}' validated for {active_pokemon.name}")
            return choice_for_processing + modifiers
        else:
            # Move not in this Pokemon's moveset - try to find any valid move
            logger.warning(
                f"MCTS returned move '{choice_for_processing}' but {active_pokemon.name} "
                f"doesn't have it. Available: {move_names}"
            )
            if move_names:
                fallback_move = move_names[0]
                logger.warning(f"Using fallback move: {fallback_move}")
                return fallback_move + modifiers
            else:
                logger.error(f"{active_pokemon.name} has NO MOVES! Returning struggle")
                return "struggle"
    
    # Case 2: Index format "move X"
    try:
        move_index = int(choice_for_processing.split()[1])
    except (ValueError, IndexError):
        logger.warning(f"Could not parse move from: {mcts_choice}")
        return "struggle"
    
    # Look up the actual move name from the active Pokemon's moveset
    if active_pokemon is None:
        logger.warning(f"No active Pokemon to look up move index {move_index}")
        return "struggle"
    
    if move_index < 0 or move_index >= len(active_pokemon.moves):
        logger.warning(
            f"Move index {move_index} out of range for {active_pokemon.name} "
            f"(has {len(active_pokemon.moves)} moves)"
        )
        return "struggle"
    
    move_name = active_pokemon.moves[move_index].name
    logger.debug(f"Converted MCTS 'move {move_index}' to '{move_name}' for {active_pokemon.name}")
    
    return move_name + modifiers


def format_decision(battle, decision, battle_user, target_token=""):
    # Formats a decision for communication with Pokemon-Showdown
    # Handles singles moves (str) for individual bots
    # For doubles battles, the move selection is split in async_pick_move()
    # so each bot only receives and formats its own single move.
    # `target_token` is the engine relative-target token for this move (doubles targeting).
    
    # Handle singles (and extracted doubles moves)
    if decision.startswith(constants.SWITCH_STRING + " "):
        switch_pokemon = decision.split("switch ")[-1]
        for pkmn in battle_user.reserve:
            if pkmn.name == switch_pokemon:
                message = "/switch {}".format(pkmn.index)
                break
        else:
            raise ValueError("Tried to switch to: {}".format(switch_pokemon))
    else:
        # Safety check: ensure we have an active Pokemon before formatting a move choice
        if battle_user.active is None :
            logger.warning(f"No active Pokemon available; defaulting to pass")
            return ["/pass", str(battle.rqid)]
            
        tera = False
        mega = False
        if decision.endswith("-tera"):
            decision = decision.replace("-tera", "")
            tera = True
        elif decision.endswith("-mega"):
            decision = decision.replace("-mega", "")
            mega = True

        message = "/choose move {}".format(decision)
        # Doubles: append the Showdown target location for single-target moves. Spread/self
        # moves (allAdjacent, self, ...) take no target and are left as-is.
        move_target_type = all_move_json.get(decision, {}).get("target", "normal")
        if move_target_type in _SINGLE_TARGET_MOVE_TYPES:
            target_loc = _showdown_target_loc(target_token, battle, battle_user)
            if target_loc is not None:
                message = "/choose move {} {}".format(decision, target_loc)

        if battle_user.active.can_mega_evo and mega:
            message = "{} {}".format(message, constants.MEGA)
        elif battle_user.active.can_ultra_burst:
            message = "{} {}".format(message, constants.ULTRA_BURST)

        # only dynamax on last pokemon
        if battle_user.active.can_dynamax and all(
            p.hp == 0 for p in battle_user.reserve
        ):
            message = "{} {}".format(message, constants.DYNAMAX)

        if tera:
            message = "{} {}".format(message, constants.TERASTALLIZE)

        # Check if the move exists and has Z-move capability
        move = battle_user.active.get_move(decision)
        if move and move.can_z:
            message = "{} {}".format(message, constants.ZMOVE)

    return [message, str(battle.rqid)]


def battle_is_finished(battle_tag, msg):
    return (
        msg.startswith(">{}".format(battle_tag))
        and (constants.WIN_STRING in msg or constants.TIE_STRING in msg)
        and constants.CHAT_STRING not in msg
    )


def extract_battle_factory_tier_from_msg(msg):
    start = msg.find("Battle Factory Tier: ") + len("Battle Factory Tier: ")
    end = msg.find("</b>", start)
    tier_name = msg[start:end]

    return normalize_name(tier_name)


async def async_pick_move(battle, ps_websocket_client: PSWebsocketClient, ally = False):
    battle_copy = deepcopy(battle)
    print("user 1 name: ",battle.user_1.name,ally)
    print("user 2 name: ",battle.user_2.name,ally)
    if not battle_copy.team_preview:
        if not ally : 
            battle_copy.user_1.update_from_request_json(battle_copy.request_json)
            battle_copy.user_2.update_from_request_json(battle_copy.request_json, ally=True)
        else :
            battle_copy.user_2.update_from_request_json(battle_copy.request_json)
            battle_copy.user_1.update_from_request_json(battle_copy.request_json, ally=True)

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        best_move = await loop.run_in_executor(pool, find_best_move, battle_copy)
    
    # Handle both singles (str) and doubles (tuple) return types
    left_target = ""
    right_target = ""
    if isinstance(best_move, tuple):
        # Split the engine's relative-target token off each move (e.g. "tackle opp2") so the
        # move name validates cleanly; the token is threaded into format_decision below.
        raw_left, left_target = _split_engine_target(best_move[0])
        raw_right, right_target = _split_engine_target(best_move[1])

        selected_move = [
            convert_mcts_choice_to_move_name(raw_left, battle_copy.user_1.active),
            convert_mcts_choice_to_move_name(raw_right, battle_copy.user_2.active)
        ]

        logger.info(f"Bot selected: {selected_move} ")

        # Track the selected move for this bot
        battle.user_1.last_selected_move = LastUsedMove(
            battle_copy.user_1.active.name if battle_copy.user_1.active else "unknown",
            selected_move[0].removesuffix("-tera").removesuffix("-mega"),
            battle.turn,
        )
        battle.user_2.last_selected_move = LastUsedMove(
            battle_copy.user_2.active.name if battle_copy.user_2.active else "unknown",
            selected_move[1].removesuffix("-tera").removesuffix("-mega"),
            battle.turn,
        )

        best_move = selected_move
    else:
        # Singles: original behavior - convert move index to move name
        pass # ditching singles behavior
        # best_move = convert_mcts_choice_to_move_name(best_move, battle_copy.user.active)
        # battle.user.last_selected_move = LastUsedMove(
        #     battle.user.active.name,
        #     best_move.removesuffix("-tera").removesuffix("-mega"),
        #     battle.turn,
        # )

    return [
        format_decision(battle_copy, best_move[0], battle_copy.user_1, left_target),
        format_decision(battle_copy, best_move[1], battle_copy.user_2, right_target)
    ]


async def handle_team_preview(battle, ps_websocket_client):
    battle_copy = deepcopy(battle)
    battle_copy.user_1.active = Pokemon.get_dummy()
    battle_copy.user_2.active = Pokemon.get_dummy()
    battle_copy.opponent_1.active = Pokemon.get_dummy()
    battle_copy.opponent_2.active = Pokemon.get_dummy()
    battle_copy.team_preview = True

    best_move = await async_pick_move(battle_copy, ps_websocket_client)

    # because we copied the battle before sending it in, we need to update the last selected move here
    pkmn_name_1 = battle.user_1.reserve[int(best_move[0].split()[1]) - 1].name
    pkmn_name_2 = battle.user_2.reserve[int(best_move[1].split()[1]) - 1].name
    battle.user_1.last_selected_move = LastUsedMove(
        "teampreview", "switch {}".format(pkmn_name_1), battle.turn
    )
    battle.user_2.last_selected_move = LastUsedMove(
        "teampreview", "switch {}".format(pkmn_name_2), battle.turn
    )

    size_of_team = 2* (len(battle.user_1.reserve) + 1)
    team_list_indexes = list(range(1, size_of_team))
    choice_digit = int(best_move[0].split()[-1])

    team_list_indexes.remove(choice_digit)
    message = [
        "/team {}{}|{}".format(
            choice_digit, "".join(str(x) for x in team_list_indexes), battle.rqid
        )
    ]
    # HOPING THIS ISN'T APPLICABLE TO MULTI BATTLES
    await ps_websocket_client.send_message(battle.battle_tag, message)


async def get_battle_tag_and_opponent(ps_websocket_client: PSWebsocketClient):
    while True:
        msg = await ps_websocket_client.receive_message()
        split_msg = msg.split("|")
        first_msg = split_msg[0]
        if "battle" in first_msg:
            battle_tag = first_msg.replace(">", "").strip()
            user_name = FoulPlayConfig.bot1username if FoulPlayConfig.bot_mode == BotModes.challenge_user else FoulPlayConfig.bot2username
            opponent_name = (
                # added lstrip to remove trailing ' from bot names
                split_msg[4].replace(user_name, "").replace("vs.", "").lstrip("'").strip()
            )
            logger.info("Initialized {} against: {}".format(battle_tag, opponent_name))
            return battle_tag, opponent_name


async def start_battle_common(
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type, command_queue
):
    battle_tag, opponent_name = await get_battle_tag_and_opponent(ps_websocket_client)
    if FoulPlayConfig.log_to_file:
        FoulPlayConfig.file_log_handler.do_rollover(
            "{}_{}.log".format(battle_tag, opponent_name)
        )

    battle = Battle(battle_tag)
    battle.opponent_1.account_name = opponent_name
    battle.opponent_2.account_name = opponent_name + "'s ally"
    battle.pokemon_format = pokemon_battle_type
    battle.generation = pokemon_battle_type[:4]

    # e.g.
    # '>battle-gen9randombattle-44733
    # |player|p1|OpponentName|2|' TODO CHECK THIS
    while True:
        msg = await ps_websocket_client.receive_message()
        if "|player|" in msg and "p4" in msg:
            battle.opponent_1.name = "p2a"
            battle.opponent_2.name = "p4b"
            battle.user_1.name = "p1a"
            battle.user_2.name = "p3b"
            break

    return battle, msg


async def get_first_request_json(
    ps_websocket_client: PSWebsocketClient, battle: Battle, is_reader=False
):
    while True:
        msg = await ps_websocket_client.receive_message()
        msg_split = msg.split("|")
        if msg_split[1].strip() == "request" and msg_split[2].strip():
            user_json = json.loads(msg_split[2].strip("'"))
            battle.request_json = user_json
            # Keep user_1 == p1 and user_2 == p3 constant for BOTH bots. The request's
            # "side" section is always the *receiving* bot's own player; for the master (p1)
            # that is user_1, but for the reader/accepter (p3) it is user_2. So the reader
            # reads its own side into user_2 and the ally (p1) into user_1.
            if not is_reader:
                battle.user_1.initialize_first_turn_user_from_json(user_json)
                battle.user_2.initialize_first_turn_user_from_json(user_json, ally=True)
            else:
                battle.user_1.initialize_first_turn_user_from_json(user_json, ally=True)
                battle.user_2.initialize_first_turn_user_from_json(user_json)
            battle.rqid = user_json[constants.RQID]
            return


async def start_random_battle(
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type, command_queue
):
    battle, msg = await start_battle_common(ps_websocket_client, pokemon_battle_type, command_queue)
    battle.battle_type = BattleType.RANDOM_BATTLE
    RandomBattleTeamDatasets.initialize(battle.generation)

    while True:
        if constants.START_STRING in msg:
            battle.started = True

            # hold onto some messages to apply after we get the request JSON
            # omit the bot's switch-in message because we won't need that
            # parsing the request JSON will set the bot's active pkmn
            battle.msg_list = [
                m
                for m in msg.split(constants.START_STRING)[1].strip().split("\n")
                if not (m.startswith("|switch|{}".format(battle.user_1.name)))
            ]
            break
        msg = await ps_websocket_client.receive_message()

    await get_first_request_json(ps_websocket_client, battle)

    # apply the messages that were held onto
    process_battle_updates(battle)

    best_move = await async_pick_move(battle, ps_websocket_client)
    await command_queue.put([battle.battle_tag, best_move[1]])
    await ps_websocket_client.send_message(battle.battle_tag, best_move[0])

    return battle

async def start_random_battle_reader(
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type, command_queue
):
    battle, msg = await start_battle_common(ps_websocket_client, pokemon_battle_type, command_queue)
    battle.battle_type = BattleType.RANDOM_BATTLE
    RandomBattleTeamDatasets.initialize(battle.generation)

    while True:
        if constants.START_STRING in msg:
            battle.started = True

            # hold onto some messages to apply after we get the request JSON
            # omit the bot's switch-in message because we won't need that
            # parsing the request JSON will set the bot's active pkmn
            battle.msg_list = [
                m
                for m in msg.split(constants.START_STRING)[1].strip().split("\n")
                if not (m.startswith("|switch|{}".format(battle.user_1.name)))
            ]
            break
        msg = await ps_websocket_client.receive_message()

    await get_first_request_json(ps_websocket_client, battle, is_reader=True)

    # apply the messages that were held onto
    process_battle_updates(battle)

    # best_move = await async_pick_move(battle, ps_websocket_client)
    # await command_queue.put([battle.battle_tag, best_move[1]])

    command = await asyncio.wait_for(command_queue.get(), timeout=30.0)
    logger.debug(f"1 Received command from queue: {command}")
    await ps_websocket_client.send_message(battle.battle_tag, replace_command_with_reader_rqid(command[1], battle))

    return battle


async def start_standard_battle(
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type, team_dict, command_queue
):
    battle, msg = await start_battle_common(ps_websocket_client, pokemon_battle_type, command_queue)
    battle.user_1.team_dict = team_dict
    battle.user_2.team_dict = team_dict # TODO CHECK
    if "battlefactory" in pokemon_battle_type:
        battle.battle_type = BattleType.BATTLE_FACTORY
    else:
        battle.battle_type = BattleType.STANDARD_BATTLE

    if battle.generation in constants.NO_TEAM_PREVIEW_GENS:
        while True:
            if constants.START_STRING in msg:
                battle.started = True

                # hold onto some messages to apply after we get the request JSON
                # omit the bot's switch-in message because we won't need that
                # parsing the request JSON will set the bot's active pkmn
                battle.msg_list = [
                    m
                    for m in msg.split(constants.START_STRING)[1].strip().split("\n")
                    if not (m.startswith("|switch|{}".format(battle.user_1.name))) # TODO CHECK
                ]
                break
            msg = await ps_websocket_client.receive_message()

        await get_first_request_json(ps_websocket_client, battle)

        unique_pkmn_names = set(
            [p.name for p in battle.user_1.reserve] + [battle.user_1.active.name]
        )
        SmogonSets.initialize(
            FoulPlayConfig.smogon_stats or pokemon_battle_type, unique_pkmn_names
        )
        TeamDatasets.initialize(pokemon_battle_type, unique_pkmn_names)

        # apply the messages that were held onto
        process_battle_updates(battle)

        best_move = await async_pick_move(battle, ps_websocket_client)
        await command_queue.put([battle.battle_tag, best_move[1]])
        await ps_websocket_client.send_message(battle.battle_tag, best_move[0])

    else:
        while constants.START_TEAM_PREVIEW not in msg:
            msg = await ps_websocket_client.receive_message()

        preview_string_lines = msg.split(constants.START_TEAM_PREVIEW)[-1].split("\n")

        opponent_pokemon = []
        for line in preview_string_lines:
            if not line:
                continue

            split_line = line.split("|")
            if (
                split_line[1] == constants.TEAM_PREVIEW_POKE
                and (split_line[2].strip() == battle.opponent_1.name
                        or split_line[2].strip() == battle.opponent_2.name)
            ):
                opponent_pokemon.append(split_line[3])

        await get_first_request_json(ps_websocket_client, battle)
        battle.initialize_team_preview(opponent_pokemon, pokemon_battle_type)
        battle.during_team_preview()

        unique_pkmn_names = set(
            p.name for p in battle.opponent_1.reserve + battle.user_1.reserve
        )

        if battle.battle_type == BattleType.BATTLE_FACTORY:
            battle.battle_type = BattleType.BATTLE_FACTORY
            tier_name = extract_battle_factory_tier_from_msg(msg)
            logger.info("Battle Factory Tier: {}".format(tier_name))
            TeamDatasets.initialize(
                pokemon_battle_type,
                unique_pkmn_names,
                battle_factory_tier_name=tier_name,
            )
        else:
            battle.battle_type = BattleType.STANDARD_BATTLE
            SmogonSets.initialize(
                FoulPlayConfig.smogon_stats or pokemon_battle_type, unique_pkmn_names
            )
            TeamDatasets.initialize(pokemon_battle_type, unique_pkmn_names)

        await handle_team_preview(battle, ps_websocket_client)

    return battle


async def start_battle(ps_websocket_client, pokemon_battle_type, team_dict, command_queue):
    if "random" in pokemon_battle_type:
        battle = await start_random_battle(ps_websocket_client, pokemon_battle_type, command_queue)
    else:
        battle = await start_standard_battle(
            ps_websocket_client, pokemon_battle_type, team_dict, command_queue
        )

    await ps_websocket_client.send_message(battle.battle_tag, ["hf"])
    #await command_queue.put([battle.battle_tag, ["hf"]])
    await ps_websocket_client.send_message(battle.battle_tag, ["/timer on"])

    return battle


async def pokemon_battle(ps_websocket_client, pokemon_battle_type, team_dicts, command_queue=None):
    # Extract the correct team_dict based on the bot's username
    if isinstance(team_dicts, list):
        # Multi-battle: team_dicts is [bot1_dict, bot2_dict]
        team_dict = team_dicts[0] if ps_websocket_client.username == FoulPlayConfig.bot1username else team_dicts[1]
    else:
        # Single-battle: team_dicts is just a dict
        team_dict = team_dicts
    
    battle = await start_battle(ps_websocket_client, pokemon_battle_type, team_dict, command_queue)
    while True:
        msg = await ps_websocket_client.receive_message()
        if battle_is_finished(battle.battle_tag, msg):
            winner = (
                msg.split(constants.WIN_STRING)[-1].split("\n")[0].strip()
                if constants.WIN_STRING in msg
                else None
            )
            logger.info("Winner: {}".format(winner))
            await ps_websocket_client.send_message(battle.battle_tag, ["gg"])
            if (
                FoulPlayConfig.save_replay == SaveReplay.always
                or (
                    FoulPlayConfig.save_replay == SaveReplay.on_loss
                    and winner != FoulPlayConfig.username
                )
                or (
                    FoulPlayConfig.save_replay == SaveReplay.on_win
                    and winner == FoulPlayConfig.username
                )
            ):
                await ps_websocket_client.save_replay(battle.battle_tag)
            await ps_websocket_client.leave_battle(battle.battle_tag)
            return winner
        else:
            action_required = await async_update_battle(battle, msg)
            if action_required and not battle.wait:
                best_move = await async_pick_move(battle, ps_websocket_client)
                await command_queue.put([battle.battle_tag, best_move[1]])
                await ps_websocket_client.send_message(battle.battle_tag, best_move[0])


async def pokemon_battle_reader(ps_websocket_client, pokemon_battle_type, command_queue=None):
    
    battle = await start_random_battle_reader(ps_websocket_client, pokemon_battle_type, command_queue)
    while True:
        msg = await ps_websocket_client.receive_message()
        if battle_is_finished(battle.battle_tag, msg):
            winner = (
                msg.split(constants.WIN_STRING)[-1].split("\n")[0].strip()
                if constants.WIN_STRING in msg
                else None
            )
            logger.info("Winner: {}".format(winner))
            await ps_websocket_client.send_message(battle.battle_tag, ["gg"])
            if (
                FoulPlayConfig.save_replay == SaveReplay.always
                or (
                    FoulPlayConfig.save_replay == SaveReplay.on_loss
                    and winner != FoulPlayConfig.username
                )
                or (
                    FoulPlayConfig.save_replay == SaveReplay.on_win
                    and winner == FoulPlayConfig.username
                )
            ):
                await ps_websocket_client.save_replay(battle.battle_tag)
            await ps_websocket_client.leave_battle(battle.battle_tag)
            return winner
        else:
            action_required = await async_update_battle(battle, msg)
            if action_required and not battle.wait:
                best_move = await async_pick_move(battle, ps_websocket_client, ally=True)
                # await command_queue.put([battle.battle_tag, best_move[1]])
                try :
                    command = await asyncio.wait_for(command_queue.get(), timeout=15.0)
                    logger.debug(f"Received command from queue: {command}")
                    await ps_websocket_client.send_message(battle.battle_tag, replace_command_with_reader_rqid(command[1], battle))
                except :
                    # if we get nothing from command_queue after 15 seconds, do our own thang.
                    await ps_websocket_client.send_message(battle.battle_tag, best_move[1])


# "choose" messages are tagged with a rqid, the last thing on the messsage, right after the "|".
# The accepter bot needs to replace that rqid with the rqid from the most recent request message, which is stored in battle.rqid
def replace_command_with_reader_rqid(msg, battle):
    msg[-1] = str(battle.rqid)
    return msg