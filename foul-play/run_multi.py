import asyncio
import json
import logging
import traceback
from copy import deepcopy

from config import FoulPlayConfig, init_logging, BotModes

from teams import load_team, TeamListIterator
from fp.run_battle import pokemon_battle
from fp.websocket_client import PSWebsocketClient

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


async def bot_challenger(original_pokedex, original_move_json):
    """Bot 1 that challenges Bot 2 and plays the battle"""
    logger.info("Bot 1 (Challenger) starting...")
    
    ps_websocket_client = await PSWebsocketClient.create(
        FoulPlayConfig.bot1username, FoulPlayConfig.bot1password, FoulPlayConfig.websocket_uri
    )
    
    FoulPlayConfig.user_id = await ps_websocket_client.login()
    
    if FoulPlayConfig.avatar is not None:
        await ps_websocket_client.avatar(FoulPlayConfig.avatar)
    
    team_packed, team_dict, team_file_name = None, None, "None"
    if FoulPlayConfig.requires_team():
        team_name = FoulPlayConfig.team_name
        team_packed, team_dict, team_file_name = load_team(team_name)
        await ps_websocket_client.update_team(team_packed)
    else:
        await ps_websocket_client.update_team("None")
    
    # Challenge user and get the battle tag
    await ps_websocket_client.challenge_user(
        FoulPlayConfig.user_to_challenge,
        FoulPlayConfig.pokemon_format,
    )
    
    # Play the battle
    winner = await pokemon_battle(
        ps_websocket_client, FoulPlayConfig.pokemon_format, team_dict
    )
    
    if winner == FoulPlayConfig.bot1username:
        logger.info("Bot 1: Won with team: {}".format(team_file_name))
    else:
        logger.info("Bot 1: Lost with team: {}".format(team_file_name))
    
    check_dictionaries_are_unmodified(original_pokedex, original_move_json)
    await ps_websocket_client.close()


async def bot_accepter(original_pokedex, original_move_json):
    """Bot 2 that accepts Bot 1's challenge and plays the battle"""
    logger.info("Bot 2 (Accepter) starting...")
    
    ps_websocket_client = await PSWebsocketClient.create(
        FoulPlayConfig.bot2username, FoulPlayConfig.bot2password, FoulPlayConfig.websocket_uri
    )
    
    FoulPlayConfig.user_id = await ps_websocket_client.login()
    
    if FoulPlayConfig.avatar is not None:
        await ps_websocket_client.avatar(FoulPlayConfig.avatar)
    
    team_packed, team_dict, team_file_name = None, None, "None"
    if FoulPlayConfig.requires_team():
        team_name = FoulPlayConfig.team_name
        team_packed, team_dict, team_file_name = load_team(team_name)
        await ps_websocket_client.update_team(team_packed)
    else:
        await ps_websocket_client.update_team("None")
    
    # Accept the challenge from Bot 1 and get the battle tag
    await ps_websocket_client.accept_challenge(
        FoulPlayConfig.pokemon_format,
        FoulPlayConfig.room_name
    )
    
    # Play the battle
    winner = await pokemon_battle(
        ps_websocket_client, FoulPlayConfig.pokemon_format, team_dict
    )
    
    if winner == FoulPlayConfig.bot2username:
        logger.info("Bot 2: Won with team: {}".format(team_file_name))
    else:
        logger.info("Bot 2: Lost with team: {}".format(team_file_name))
    
    check_dictionaries_are_unmodified(original_pokedex, original_move_json)
    await ps_websocket_client.close()


async def run_foul_play_multi():
    FoulPlayConfig.configure()
    init_logging(FoulPlayConfig.log_level, FoulPlayConfig.log_to_file)
    apply_mods(FoulPlayConfig.pokemon_format)

    original_pokedex = deepcopy(pokedex)
    original_move_json = deepcopy(all_move_json)
    
    # Run both bots concurrently
    await asyncio.gather(
        bot_challenger(original_pokedex, original_move_json),
        bot_accepter(original_pokedex, original_move_json),
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_foul_play_multi())
    except Exception:
        logger.error(traceback.format_exc())
        raise
