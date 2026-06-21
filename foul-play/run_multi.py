import asyncio
import json
import logging
import traceback
from copy import deepcopy

from config import FoulPlayConfig, init_logging, BotModes

from teams import load_team, TeamListIterator
from fp.run_battle import pokemon_battle, pokemon_battle_reader, start_random_battle_reader
from fp.websocket_client import PSWebsocketClient
from team_maker import Pokemon, Trainer, TeamMaker

from data import all_move_json
from data import pokedex
from data.mods.apply_mods import apply_mods

logger = logging.getLogger(__name__)


def check_dictionaries_are_unmodified(original_pokedex, original_move_json):
    # The bot should not modify the data dictionaries
    # This is a "just-in-case" check to make sure and will stop the bot if it mutates either of them
    if original_move_json != all_move_json:
        logger.critical(
            "Move JSON changed!\nDumping modified version to `modified_moves.json`"
        )
        with open("modified_moves.json", "w") as f:
            json.dump(all_move_json, f, indent=4)
        exit(1)
    else:
        logger.debug("Move JSON unmodified!")

    if original_pokedex != pokedex:
        logger.critical(
            "Pokedex JSON changed!\nDumping modified version to `modified_pokedex.json`"
        )
        with open("modified_pokedex.json", "w") as f:
            json.dump(pokedex, f, indent=4)
        exit(1)
    else:
        logger.debug("Pokedex JSON unmodified!")


async def bot_challenger(original_pokedex, original_move_json, command_queue, request_queue, team_dicts, bot_index):
    """Bot 1 (Master) that challenges Bot 2 and makes all battle decisions"""
    logger.info("Bot 1 (Challenger/Master) starting...")
    
    ps_websocket_client = await PSWebsocketClient.create(
        FoulPlayConfig.bot1username, FoulPlayConfig.bot1password, FoulPlayConfig.websocket_uri
    )
    
    FoulPlayConfig.user_id = await ps_websocket_client.login()
    
    if FoulPlayConfig.avatar is not None:
        await ps_websocket_client.avatar(FoulPlayConfig.avatar)
    
    if FoulPlayConfig.requires_team():
        # Use team_dicts[bot_index] which is team_dicts[0] for Bot 1
        team_dict = team_dicts[bot_index]
        # Need to reconstruct team_packed for update_team
        # For now, we'll load it again (could optimize by returning team_packed from run_foul_play_multi)
        team_packed, _, _ = load_team(FoulPlayConfig.team_name)
        await ps_websocket_client.update_team(team_packed)
    else:
        team_dict = None
        await ps_websocket_client.update_team("None")
    
    # Challenge user and get the battle tag
    await ps_websocket_client.challenge_user(
        FoulPlayConfig.user_to_challenge,
        FoulPlayConfig.pokemon_format,
    )
    
    # Play the battle, passing the list of team dicts
    winner = await pokemon_battle(
        ps_websocket_client, FoulPlayConfig.pokemon_format, team_dicts, command_queue, request_queue
    )
    
    if winner == FoulPlayConfig.bot1username:
        logger.info("Bot 1: Won")
    else:
        logger.info("Bot 1: Lost")
    
    # Signal Bot 2 to stop
    await command_queue.put(None)
    
    check_dictionaries_are_unmodified(original_pokedex, original_move_json)
    await ps_websocket_client.close()


async def bot_accepter(original_pokedex, original_move_json, command_queue, request_queue, team_dicts, bot_index):
    """Bot 2 (Worker) that accepts the challenge and waits for commands from Bot 1"""
    logger.info("Bot 2 (Accepter/Worker) starting...")
    
    ps_websocket_client = await PSWebsocketClient.create(
        FoulPlayConfig.bot2username, FoulPlayConfig.bot2password, FoulPlayConfig.websocket_uri
    )
    
    FoulPlayConfig.user_id = await ps_websocket_client.login()
    
    if FoulPlayConfig.avatar is not None:
        await ps_websocket_client.avatar(FoulPlayConfig.avatar)
    
    if FoulPlayConfig.requires_team():
        # Use team_dicts[bot_index] which is team_dicts[1] for Bot 2
        team_dict = team_dicts[bot_index]
        # Need to reconstruct team_packed for update_team
        team_packed, _, _ = load_team(FoulPlayConfig.team_name)
        await ps_websocket_client.update_team(team_packed)
    else:
        team_dict = None
        await ps_websocket_client.update_team("None")
    
    # Accept the challenge from Bot 1
    await ps_websocket_client.accept_challenge(
        FoulPlayConfig.pokemon_format,
        FoulPlayConfig.room_name
    )
    
    logger.info("Bot 2: Challenge accepted, waiting for commands from Bot 1...")

    await pokemon_battle_reader(ps_websocket_client, FoulPlayConfig.pokemon_format, command_queue, request_queue)
    
    
    check_dictionaries_are_unmodified(original_pokedex, original_move_json)
    await ps_websocket_client.close()


async def run_foul_play_multi():
    FoulPlayConfig.configure()
    init_logging(FoulPlayConfig.log_level, FoulPlayConfig.log_to_file)
    apply_mods(FoulPlayConfig.pokemon_format)

    original_pokedex = deepcopy(pokedex)
    original_move_json = deepcopy(all_move_json)
    
    # Load teams for both bots
    team_dicts = [None, None]  # [bot1_team_dict, bot2_team_dict]
    team_names = ["", ""]

    """
    TODO get the team creation / initialization from files into foul-play. Create trainers, and they have a list
    of pokemon for their team. When we need, we can get a random team from 2 of their pokemon :)
    """
    team_maker = TeamMaker()
    opps = team_maker.get_opponents(battle_number=FoulPlayConfig.round, team_size=2)

    
    if FoulPlayConfig.requires_team():
        # Load Bot 1's team
        team_packed_1, team_dicts[0], team_names[0] = load_team(FoulPlayConfig.team_name)
        # Load Bot 2's team (same config for now, but could be different)
        team_packed_2, team_dicts[1], team_names[1] = load_team(FoulPlayConfig.team_name)
    
    # Create command queue
    command_queue = asyncio.Queue() # master writes to this to tell worker what to send
    request_queue = asyncio.Queue() # worker writes to this to tell master what message received from server
    
    # Run both bots concurrently, passing the list of team dicts
    await asyncio.gather(
        bot_challenger(original_pokedex, original_move_json, command_queue, request_queue, team_dicts, 0),
        bot_accepter(original_pokedex, original_move_json, command_queue, request_queue, team_dicts, 1),
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_foul_play_multi())
    except Exception:
        logger.error(traceback.format_exc())
        raise
