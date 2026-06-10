import json
import asyncio
import concurrent.futures
from copy import deepcopy
import logging

from data.pkmn_sets import RandomBattleTeamDatasets, TeamDatasets
from data.pkmn_sets import SmogonSets
import constants
from constants import BattleType
from config import BotModes, FoulPlayConfig, SaveReplay
from fp.battle import LastUsedMove, Pokemon, Battle
from fp.battle_modifier import async_update_battle, process_battle_updates
from fp.helpers import normalize_name
from fp.search.main import find_best_move

from fp.websocket_client import PSWebsocketClient

logger = logging.getLogger(__name__)


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


def format_decision(battle, decision):
    # Formats a decision for communication with Pokemon-Showdown
    # Handles singles moves (str) for individual bots
    # For doubles battles, the move selection is split in async_pick_move()
    # so each bot only receives and formats its own single move
    
    # Handle singles (and extracted doubles moves)
    if decision.startswith(constants.SWITCH_STRING + " "):
        switch_pokemon = decision.split("switch ")[-1]
        for pkmn in battle.user.reserve:
            if pkmn.name == switch_pokemon:
                message = "/switch {}".format(pkmn.index)
                break
        else:
            raise ValueError("Tried to switch to: {}".format(switch_pokemon))
    else:
        # Safety check: ensure we have an active Pokemon before formatting a move choice
        if battle.user.active is None:
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

        if battle.user.active.can_mega_evo and mega:
            message = "{} {}".format(message, constants.MEGA)
        elif battle.user.active.can_ultra_burst:
            message = "{} {}".format(message, constants.ULTRA_BURST)

        # only dynamax on last pokemon
        if battle.user.active.can_dynamax and all(
            p.hp == 0 for p in battle.user.reserve
        ):
            message = "{} {}".format(message, constants.DYNAMAX)

        if tera:
            message = "{} {}".format(message, constants.TERASTALLIZE)

        # Check if the move exists and has Z-move capability
        move = battle.user.active.get_move(decision)
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


async def async_pick_move(battle, ps_websocket_client: PSWebsocketClient):
    battle_copy = deepcopy(battle)
    if not battle_copy.team_preview:
        battle_copy.user.update_from_request_json(battle_copy.request_json)

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        best_move = await loop.run_in_executor(pool, find_best_move, battle_copy)
    
    # Handle both singles (str) and doubles (tuple) return types
    if isinstance(best_move, tuple):
        # Doubles battles: MCTS returns (left_move_index, right_move_index) tuple
        # Each bot acts independently, so extract the move for THIS bot
        left_move_index, right_move_index = best_move
        
        # Determine which move belongs to this bot based on username
        # Bot1 controls left active, other username controls right active
        is_this_bot1 = ps_websocket_client.username == FoulPlayConfig.bot1username
        
        if is_this_bot1:
            # This bot is Bot1 (left side), use left active Pokemon
            selected_move_index = left_move_index
            active_pokemon = battle_copy.user.active
            bot_position = "left (p1)"
        else:
            # This bot is the other player (right side), use right active Pokemon
            selected_move_index = right_move_index
            active_pokemon = battle_copy.user.active_right
            bot_position = "right (p4)"
        
        # Convert move index string to actual move name
        # MCTS returns strings like "move 0", "move 1", "switch 2", etc.
        logger.info(f"Converting MCTS choice '{selected_move_index}' for {active_pokemon.name if active_pokemon else 'NONE'} on {bot_position}")
        selected_move = convert_mcts_choice_to_move_name(selected_move_index, active_pokemon)
        
        # For logging, also convert the other player's move index
        other_active = battle_copy.user.active_right if is_this_bot1 else battle_copy.user.active
        other_move = convert_mcts_choice_to_move_name(
            right_move_index if is_this_bot1 else left_move_index, 
            other_active
        )
        
        # Log both moves for transparency
        logger.info(f"Doubles move pair from MCTS: {left_move_index}, {right_move_index}")
        logger.info(f"Bot {bot_position} selected: {selected_move} (opponent selecting: {other_move})")
        
        # Track the selected move for this bot
        battle.user.last_selected_move = LastUsedMove(
            active_pokemon.name if active_pokemon else "unknown",
            selected_move.removesuffix("-tera").removesuffix("-mega"),
            battle.turn,
        )
        
        best_move = selected_move
    else:
        # Singles: original behavior - convert move index to move name
        best_move = convert_mcts_choice_to_move_name(best_move, battle_copy.user.active)
        battle.user.last_selected_move = LastUsedMove(
            battle.user.active.name,
            best_move.removesuffix("-tera").removesuffix("-mega"),
            battle.turn,
        )
    
    return format_decision(battle_copy, best_move)


async def handle_team_preview(battle, ps_websocket_client):
    battle_copy = deepcopy(battle)
    battle_copy.user.active = Pokemon.get_dummy()
    battle_copy.opponent.active = Pokemon.get_dummy()
    battle_copy.team_preview = True

    best_move = await async_pick_move(battle_copy, ps_websocket_client)

    # because we copied the battle before sending it in, we need to update the last selected move here
    pkmn_name = battle.user.reserve[int(best_move[0].split()[1]) - 1].name
    battle.user.last_selected_move = LastUsedMove(
        "teampreview", "switch {}".format(pkmn_name), battle.turn
    )

    size_of_team = len(battle.user.reserve) + 1
    team_list_indexes = list(range(1, size_of_team))
    choice_digit = int(best_move[0].split()[-1])

    team_list_indexes.remove(choice_digit)
    message = [
        "/team {}{}|{}".format(
            choice_digit, "".join(str(x) for x in team_list_indexes), battle.rqid
        )
    ]

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
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type
):
    battle_tag, opponent_name = await get_battle_tag_and_opponent(ps_websocket_client)
    if FoulPlayConfig.log_to_file:
        FoulPlayConfig.file_log_handler.do_rollover(
            "{}_{}.log".format(battle_tag, opponent_name)
        )

    battle = Battle(battle_tag)
    battle.opponent.account_name = opponent_name
    battle.pokemon_format = pokemon_battle_type
    battle.generation = pokemon_battle_type[:4]

    # wait until the opponent's identifier is received. This will be `p1` or `p2`.
    #
    # e.g.
    # '>battle-gen9randombattle-44733
    # |player|p1|OpponentName|2|'
    while True:
        msg = await ps_websocket_client.receive_message()
        if "|player|" in msg and "p4" in msg:
            battle.opponent.name = msg.split("|")[2]
            battle.user.name = "p1" if ps_websocket_client.username == FoulPlayConfig.bot1username else "p3"
            break

    return battle, msg


async def get_first_request_json(
    ps_websocket_client: PSWebsocketClient, battle: Battle
):
    while True:
        msg = await ps_websocket_client.receive_message()
        msg_split = msg.split("|")
        if msg_split[1].strip() == "request" and msg_split[2].strip():
            user_json = json.loads(msg_split[2].strip("'"))
            battle.request_json = user_json
            battle.user.initialize_first_turn_user_from_json(user_json)
            battle.rqid = user_json[constants.RQID]
            return


async def start_random_battle(
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type
):
    battle, msg = await start_battle_common(ps_websocket_client, pokemon_battle_type)
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
                if not (m.startswith("|switch|{}".format(battle.user.name)))
            ]
            break
        msg = await ps_websocket_client.receive_message()

    await get_first_request_json(ps_websocket_client, battle)

    # apply the messages that were held onto
    process_battle_updates(battle)

    best_move = await async_pick_move(battle, ps_websocket_client)
    await ps_websocket_client.send_message(battle.battle_tag, best_move)

    return battle


async def start_standard_battle(
    ps_websocket_client: PSWebsocketClient, pokemon_battle_type, team_dict
):
    battle, msg = await start_battle_common(ps_websocket_client, pokemon_battle_type)
    battle.user.team_dict = team_dict
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
                    if not (m.startswith("|switch|{}".format(battle.user.name)))
                ]
                break
            msg = await ps_websocket_client.receive_message()

        await get_first_request_json(ps_websocket_client, battle)

        unique_pkmn_names = set(
            [p.name for p in battle.user.reserve] + [battle.user.active.name]
        )
        SmogonSets.initialize(
            FoulPlayConfig.smogon_stats or pokemon_battle_type, unique_pkmn_names
        )
        TeamDatasets.initialize(pokemon_battle_type, unique_pkmn_names)

        # apply the messages that were held onto
        process_battle_updates(battle)

        best_move = await async_pick_move(battle, ps_websocket_client)
        await ps_websocket_client.send_message(battle.battle_tag, best_move)

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
                and split_line[2].strip() == battle.opponent.name
            ):
                opponent_pokemon.append(split_line[3])

        await get_first_request_json(ps_websocket_client, battle)
        battle.initialize_team_preview(opponent_pokemon, pokemon_battle_type)
        battle.during_team_preview()

        unique_pkmn_names = set(
            p.name for p in battle.opponent.reserve + battle.user.reserve
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


async def start_battle(ps_websocket_client, pokemon_battle_type, team_dict):
    if "random" in pokemon_battle_type:
        battle = await start_random_battle(ps_websocket_client, pokemon_battle_type)
    else:
        battle = await start_standard_battle(
            ps_websocket_client, pokemon_battle_type, team_dict
        )

    await ps_websocket_client.send_message(battle.battle_tag, ["hf"])
    await ps_websocket_client.send_message(battle.battle_tag, ["/timer on"])

    return battle


async def pokemon_battle(ps_websocket_client, pokemon_battle_type, team_dict):
    battle = await start_battle(ps_websocket_client, pokemon_battle_type, team_dict)
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
                await ps_websocket_client.send_message(battle.battle_tag, best_move)
