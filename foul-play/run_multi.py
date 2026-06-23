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


async def bot_challenger(original_pokedex, original_move_json, command_queue, request_queue):
    """Bot 1 (Master) that challenges Bot 2 and makes all battle decisions"""
    logger.info("Bot 1 (Challenger/Master) starting...")
    
    ps_websocket_client = await PSWebsocketClient.create(
        FoulPlayConfig.bot1username, FoulPlayConfig.bot1password, FoulPlayConfig.websocket_uri
    )
    
    FoulPlayConfig.user_id = await ps_websocket_client.login()
    if FoulPlayConfig.avatar is not None:
            await ps_websocket_client.avatar(FoulPlayConfig.avatar)

    team_maker = TeamMaker()
    battle_number = FoulPlayConfig.round
    while battle_number != -1 : 

        team_packs = ["None", "None"]
        team_dicts = [None, None]
        
        if FoulPlayConfig.requires_team():
            opps = team_maker.get_opponents(battle_number=battle_number, team_size=2)
            msg = f"Round {battle_number} : You are challenged by {opps[0].prettyName()} and {opps[1].prettyName()}"

            # Each bot's team comes from one of the TeamMaker trainers, converted to foul-play's
            # formats: team_packs feed update_team(), team_dicts feed the search.
            
            team_packs[0], team_dicts[0] = opps[0].to_foulplay_team()
            team_packs[1], team_dicts[1] = opps[1].to_foulplay_team()
            # Team for this bot was built by TeamMaker (see run_foul_play_multi)
            await ps_websocket_client.update_team(team_packs[0])
            await command_queue.put(team_packs[1])
        else:
            await ps_websocket_client.update_team("None")

        # Challenge user and get the battle tag
        await ps_websocket_client.challenge_user(
            FoulPlayConfig.user_to_challenge,
            FoulPlayConfig.pokemon_format,
        )
        
        # Play the battle, passing the list of team dicts
        winner = await pokemon_battle(
            ps_websocket_client, FoulPlayConfig.pokemon_format, team_dicts, command_queue, request_queue, greeting = msg
        )
        
        if FoulPlayConfig.bot1username in winner :
            logger.info("Bots: Won")
            battle_number = -1
            await command_queue.put("stop")
        else:
            logger.info("Bot 1: Lost")
            battle_number += 1
            await command_queue.put("go")

    
    check_dictionaries_are_unmodified(original_pokedex, original_move_json)
    await ps_websocket_client.close()


async def bot_accepter(original_pokedex, original_move_json, command_queue, request_queue):
    """Bot 2 (Worker) that accepts the challenge and waits for commands from Bot 1"""
    logger.info("Bot 2 (Accepter/Worker) starting...")
    
    ps_websocket_client = await PSWebsocketClient.create(
        FoulPlayConfig.bot2username, FoulPlayConfig.bot2password, FoulPlayConfig.websocket_uri
    )
    
    FoulPlayConfig.user_id = await ps_websocket_client.login()
    if FoulPlayConfig.avatar is not None:
        await ps_websocket_client.avatar(FoulPlayConfig.avatar)

    command_received = "go"
    while command_received != "stop" : 
    
        if FoulPlayConfig.requires_team():
            # Team for this bot was built by TeamMaker (see run_foul_play_multi)
            team_pack = await command_queue.get()
            await ps_websocket_client.update_team(team_pack)
        else:
            await ps_websocket_client.update_team("None")
        
        # Accept the challenge from Bot 1
        await ps_websocket_client.accept_challenge(
            FoulPlayConfig.pokemon_format,
            FoulPlayConfig.room_name
        )
        
        logger.info("Bot 2: Challenge accepted, waiting for commands from Bot 1...")

        await pokemon_battle_reader(ps_websocket_client, FoulPlayConfig.pokemon_format, command_queue, request_queue)

        try : 
            command_received = await asyncio.wait_for(command_queue.get(), timeout=20.0)
        except : 
            command_received = "stop"
    
    
    check_dictionaries_are_unmodified(original_pokedex, original_move_json)
    await ps_websocket_client.close()


async def run_foul_play_multi():
    FoulPlayConfig.configure()
    init_logging(FoulPlayConfig.log_level, FoulPlayConfig.log_to_file)
    apply_mods(FoulPlayConfig.pokemon_format)

    original_pokedex = deepcopy(pokedex)
    original_move_json = deepcopy(all_move_json)
    
    # Create command queue
    command_queue = asyncio.Queue() # master writes to this to tell worker what to send
    request_queue = asyncio.Queue() # worker writes to this to tell master what message received from server
    
    # Run both bots concurrently, passing the list of team dicts
    await asyncio.gather(
        bot_challenger(original_pokedex, original_move_json, command_queue, request_queue),
        bot_accepter(original_pokedex, original_move_json, command_queue, request_queue),
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_foul_play_multi())
    except Exception:
        logger.error(traceback.format_exc())
        raise
