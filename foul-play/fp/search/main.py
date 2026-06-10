import logging
import random
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy

from constants import BattleType
from fp.battle import Battle
from config import FoulPlayConfig
from .standard_battles import prepare_battles
from .random_battles import prepare_random_battles

from poke_engine import State as PokeEngineState, monte_carlo_tree_search, MctsResult

from fp.search.poke_engine_helpers import battle_to_poke_engine_state

logger = logging.getLogger(__name__)


def parse_move_pair_from_string(move_pair_str: str) -> tuple:
    """
    Parse a move pair string from poke-engine MCTS format.
    
    Expected formats:
    - Singles: "move_id" -> return as-is (handled before this)
    - Doubles: "move1, move2" or "move1|move2" -> parse to tuple
    
    Args:
        move_pair_str: String representation of move pair from MCTS
        
    Returns:
        Tuple of (left_move_id, right_move_id)
    """
    # Try comma-separated format first (standard format)
    if "," in move_pair_str:
        parts = move_pair_str.split(",")
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
    
    # Try pipe-separated format as fallback
    if "|" in move_pair_str:
        parts = move_pair_str.split("|")
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
    
    # Fallback: assume it's two moves and parse what we can
    # This handles edge cases from poke-engine formatting
    parts = move_pair_str.replace("(", "").replace(")", "").split()
    if len(parts) >= 2:
        return (parts[0], parts[1])
    
    # Last resort: return struggle for both
    logger.warning(f"Could not parse move pair from: {move_pair_str}")
    return ("struggle", "struggle")


def select_move_from_mcts_results(mcts_results: list[(MctsResult, float, int)]) -> str:
    final_policy = {}
    for mcts_result, sample_chance, index in mcts_results:
        this_policy = max(mcts_result.side_one, key=lambda x: x.visits)
        logger.info(
            "Policy {}: {} visited {}% avg_score={} sample_chance_multiplier={}".format(
                index,
                this_policy.move_choice,
                round(100 * this_policy.visits / mcts_result.total_visits, 2),
                round(this_policy.total_score / this_policy.visits, 3),
                round(sample_chance, 3),
            )
        )
        for s1_option in mcts_result.side_one:
            final_policy[s1_option.move_choice] = final_policy.get(
                s1_option.move_choice, 0
            ) + (sample_chance * (s1_option.visits / mcts_result.total_visits))

    final_policy = sorted(final_policy.items(), key=lambda x: x[1], reverse=True)

    # Consider all moves that are close to the best move
    highest_percentage = final_policy[0][1]
    final_policy = [i for i in final_policy if i[1] >= highest_percentage * 0.75]
    logger.info("Considered Choices:")
    for i, policy in enumerate(final_policy):
        logger.info(f"\t{round(policy[1] * 100, 3)}%: {policy[0]}")

    choice = random.choices(final_policy, weights=[p[1] for p in final_policy])[0]
    return choice[0]


def get_result_from_mcts(state: str, search_time_ms: int, index: int) -> MctsResult:
    logger.debug("Calling with {} state: {}".format(index, state))
    poke_engine_state = PokeEngineState.from_string(state)

    res = monte_carlo_tree_search(poke_engine_state, search_time_ms)
    logger.info("Iterations {}: {}".format(index, res.total_visits))
    return res


def search_time_num_battles_randombattles(battle):
    revealed_pkmn = len(battle.opponent.reserve)
    if battle.opponent.active is not None:
        revealed_pkmn += 1

    opponent_active_num_moves = len(battle.opponent.active.moves)
    in_time_pressure = battle.time_remaining is not None and battle.time_remaining <= 60

    # it is still quite early in the battle and the pkmn in front of us
    # hasn't revealed any moves: search a lot of battles shallowly
    if (
        revealed_pkmn <= 3
        and battle.opponent.active.hp > 0
        and opponent_active_num_moves == 0
    ):
        num_battles_multiplier = 2 if in_time_pressure else 4
        return FoulPlayConfig.parallelism * num_battles_multiplier, int(
            FoulPlayConfig.search_time_ms // 2
        )

    else:
        num_battles_multiplier = 1 if in_time_pressure else 2
        return FoulPlayConfig.parallelism * num_battles_multiplier, int(
            FoulPlayConfig.search_time_ms
        )


def search_time_num_battles_standard_battle(battle):
    opponent_active_num_moves = len(battle.opponent.active.moves)
    in_time_pressure = battle.time_remaining is not None and battle.time_remaining <= 60

    if (
        battle.team_preview
        or (battle.opponent.active.hp > 0 and opponent_active_num_moves == 0)
        or opponent_active_num_moves < 3
    ):
        num_battles_multiplier = 1 if in_time_pressure else 2
        return FoulPlayConfig.parallelism * num_battles_multiplier, int(
            FoulPlayConfig.search_time_ms
        )
    else:
        return FoulPlayConfig.parallelism, FoulPlayConfig.search_time_ms


def find_best_move(battle: Battle):
    """
    Find the best move(s) for the current battle format using MCTS.
    
    Returns:
        str for singles battles
        tuple for doubles battles  
    """
    battle = deepcopy(battle)
    if battle.team_preview:
        battle.user.active = battle.user.reserve.pop(0)
        battle.opponent.active = battle.opponent.reserve.pop(0)

    # Detect doubles battles by checking the battle format string
    # A battle is doubles if "multi" appears in the format name, regardless of current active count
    # This ensures 2v1 situations remain in doubles format
    is_doubles = battle.pokemon_format and "multi" in battle.pokemon_format.lower()
    
    logger.info(f"Battle format detected: {'Doubles' if is_doubles else 'Singles'} (format={battle.pokemon_format})")
    
    if is_doubles:
        return find_best_move_pair_mcts(battle)
    else:
        return find_best_single_move_mcts(battle)


def find_best_single_move_mcts(battle: Battle) -> str:
    """Original MCTS-based move selection for singles battles."""
    if battle.battle_type == BattleType.RANDOM_BATTLE:
        num_battles, search_time_per_battle = search_time_num_battles_randombattles(
            battle
        )
        battles = prepare_random_battles(battle, num_battles)
    elif battle.battle_type == BattleType.BATTLE_FACTORY:
        num_battles, search_time_per_battle = search_time_num_battles_standard_battle(
            battle
        )
        battles = prepare_random_battles(battle, num_battles)
    elif battle.battle_type == BattleType.STANDARD_BATTLE:
        num_battles, search_time_per_battle = search_time_num_battles_standard_battle(
            battle
        )
        battles = prepare_battles(battle, num_battles)
    else:
        raise ValueError("Unsupported battle type: {}".format(battle.battle_type))

    logger.info("Searching for a move using MCTS...")
    logger.info(
        "Sampling {} battles at {}ms each".format(num_battles, search_time_per_battle)
    )
    with ProcessPoolExecutor(max_workers=FoulPlayConfig.parallelism) as executor:
        futures = []
        for index, (b, chance) in enumerate(battles):
            fut = executor.submit(
                get_result_from_mcts,
                battle_to_poke_engine_state(b).to_string(),
                search_time_per_battle,
                index,
            )
            futures.append((fut, chance, index))

    mcts_results = [(fut.result(), chance, index) for (fut, chance, index) in futures]
    choice = select_move_from_mcts_results(mcts_results)
    logger.info("Choice: {}".format(choice))
    return choice


def find_best_move_pair_mcts(battle: Battle) -> tuple:
    """
    Find the best pair of moves for doubles battles using MCTS.
    
    In doubles, MCTS naturally explores move pair combinations since the poke-engine
    doubles implementation generates all valid paired actions. This function aggregates
    MCTS results to select the best move pair.
    
    Returns:
        Tuple of (left_move_id, right_move_id)
    """
    if battle.battle_type == BattleType.RANDOM_BATTLE:
        num_battles, search_time_per_battle = search_time_num_battles_randombattles(
            battle
        )
        battles = prepare_random_battles(battle, num_battles)
    elif battle.battle_type == BattleType.BATTLE_FACTORY:
        num_battles, search_time_per_battle = search_time_num_battles_standard_battle(
            battle
        )
        battles = prepare_random_battles(battle, num_battles)
    elif battle.battle_type == BattleType.STANDARD_BATTLE:
        num_battles, search_time_per_battle = search_time_num_battles_standard_battle(
            battle
        )
        battles = prepare_battles(battle, num_battles)
    else:
        raise ValueError("Unsupported battle type: {}".format(battle.battle_type))

    logger.info("Searching for best move pair using MCTS...")
    logger.info(
        "Sampling {} battles at {}ms each".format(num_battles, search_time_per_battle)
    )
    with ProcessPoolExecutor(max_workers=FoulPlayConfig.parallelism) as executor:
        futures = []
        for index, (b, chance) in enumerate(battles):
            fut = executor.submit(
                get_result_from_mcts,
                battle_to_poke_engine_state(b).to_string(),
                search_time_per_battle,
                index,
            )
            futures.append((fut, chance, index))

    mcts_results = [(fut.result(), chance, index) for (fut, chance, index) in futures]
    move_pair = select_move_pair_from_mcts_results(mcts_results)
    logger.info("Best move pair: {}".format(move_pair))
    return move_pair


def select_move_pair_from_mcts_results(mcts_results: list[(MctsResult, float, int)]) -> tuple:
    """
    Aggregate MCTS results to select the best move pair for doubles.
    
    In doubles battles, MCTS explores the full game tree with both bots' Pokemon active.
    The result contains side_one options (Bot1's moves) and side_two options (Bot2's moves).
    We aggregate to find the best move for each bot independently, then combine them.
    
    Args:
        mcts_results: List of (MctsResult, sample_chance, index) tuples from MCTS
        
    Returns:
        Tuple of (left_move_id, right_move_id) representing best move pair for (Bot1, Bot2)
    """
    # Aggregate move performance for side_one (Bot1's left Pokemon) independently
    side_one_policy = {}
    # Aggregate move performance for side_two (Bot2's right Pokemon) independently
    side_two_policy = {}
    
    for mcts_result, sample_chance, index in mcts_results:
        # Process side_one (Bot1's moves)
        if mcts_result.side_one:
            best_s1_policy = max(mcts_result.side_one, key=lambda x: x.visits)
            s1_move = best_s1_policy.move_choice
            
            logger.info(
                "Policy {}: side_one {} visited {}% avg_score={} sample_chance_multiplier={}".format(
                    index,
                    s1_move,
                    round(100 * best_s1_policy.visits / mcts_result.total_visits, 2),
                    round(best_s1_policy.total_score / best_s1_policy.visits, 3),
                    round(sample_chance, 3),
                )
            )
            
            side_one_policy[s1_move] = side_one_policy.get(s1_move, 0) + (
                sample_chance * (best_s1_policy.visits / mcts_result.total_visits)
            )
        
        # Process side_two (Bot2's moves)
        if mcts_result.side_two:
            best_s2_policy = max(mcts_result.side_two, key=lambda x: x.visits)
            s2_move = best_s2_policy.move_choice
            
            logger.info(
                "Policy {}: side_two {} visited {}% avg_score={} sample_chance_multiplier={}".format(
                    index,
                    s2_move,
                    round(100 * best_s2_policy.visits / mcts_result.total_visits, 2),
                    round(best_s2_policy.total_score / best_s2_policy.visits, 3),
                    round(sample_chance, 3),
                )
            )
            
            side_two_policy[s2_move] = side_two_policy.get(s2_move, 0) + (
                sample_chance * (best_s2_policy.visits / mcts_result.total_visits)
            )
    
    if not side_one_policy or not side_two_policy:
        logger.warning("No valid moves found in MCTS results, using struggle")
        return ("struggle", "struggle")
    
    # Sort by aggregated policy score
    side_one_sorted = sorted(side_one_policy.items(), key=lambda x: x[1], reverse=True)
    side_two_sorted = sorted(side_two_policy.items(), key=lambda x: x[1], reverse=True)
    
    # Consider moves that are close to the best
    s1_highest = side_one_sorted[0][1]
    s1_candidates = [i for i in side_one_sorted if i[1] >= s1_highest * 0.75]
    
    s2_highest = side_two_sorted[0][1]
    s2_candidates = [i for i in side_two_sorted if i[1] >= s2_highest * 0.75]
    
    logger.info("Considered Side One Moves:")
    for i, policy in enumerate(s1_candidates):
        logger.info(f"\t{round(policy[1] * 100, 3)}%: {policy[0]}")
    
    logger.info("Considered Side Two Moves:")
    for i, policy in enumerate(s2_candidates):
        logger.info(f"\t{round(policy[1] * 100, 3)}%: {policy[0]}")
    
    # Select best move for each side independently
    s1_choice = random.choices(s1_candidates, weights=[p[1] for p in s1_candidates])[0]
    s2_choice = random.choices(s2_candidates, weights=[p[1] for p in s2_candidates])[0]
    
    left_move = s1_choice[0]
    right_move = s2_choice[0]
    
    logger.info(f"Selected move pair: ({left_move}, {right_move})")
    return (left_move, right_move)
