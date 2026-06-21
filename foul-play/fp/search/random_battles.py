import logging
import random
from copy import deepcopy

from constants import BattleType
from fp.battle import Battle, Pokemon
from data.pkmn_sets import RandomBattleTeamDatasets, TeamDatasets
from fp.search.helpers import populate_pkmn_from_set
from fp.helpers import (
    POKEMON_TYPE_INDICES,
    is_super_effective,
    type_effectiveness_modifier,
)

logger = logging.getLogger(__name__)


def get_all_remaining_sets_for_revealed_pkmn(battle: Battle) -> dict:
    if battle.battle_type == BattleType.RANDOM_BATTLE:
        datasets = RandomBattleTeamDatasets
    elif battle.battle_type == BattleType.BATTLE_FACTORY:
        datasets = TeamDatasets
    else:
        raise ValueError("Only random battles are supported")

    revealed_pkmn = []
    for pkmn in battle.opponent_1.reserve:
        revealed_pkmn.append(pkmn)
    if battle.opponent_1.active is not None:
        revealed_pkmn.append(battle.opponent_1.active)
    for pkmn in battle.opponent_2.reserve:
        revealed_pkmn.append(pkmn)
    if battle.opponent_2.active is not None:
        revealed_pkmn.append(battle.opponent_2.active)

    ret = {}
    for pkmn in revealed_pkmn:
        sets = datasets.get_all_remaining_sets(pkmn)
        random.shuffle(sets)
        ret[pkmn.name] = sets

    return ret


def prepare_random_battles(battle: Battle, num_battles: int) -> list[(Battle, float)]:
    revealed_pkmn_sets = get_all_remaining_sets_for_revealed_pkmn(deepcopy(battle))

    sampled_battles = []
    for index in range(num_battles):
        battle_copy = deepcopy(battle)

        # OPPONENT_1 LOGIC
        active = battle_copy.opponent_1.active
        if active and revealed_pkmn_sets.get(active.name):
            pkmn_full_set = random.choices(
                revealed_pkmn_sets[active.name],
                weights=[s.pkmn_set.count for s in revealed_pkmn_sets[active.name]],
            )[0]
            populate_pkmn_from_set(active, pkmn_full_set)

        for pkmn in filter(lambda x: x.is_alive(), battle_copy.opponent_1.reserve):
            if not revealed_pkmn_sets.get(pkmn.name):
                continue
            pkmn_full_set = random.choices(
                revealed_pkmn_sets[pkmn.name],
                weights=[s.pkmn_set.count for s in revealed_pkmn_sets[pkmn.name]],
            )[0]
            populate_pkmn_from_set(pkmn, pkmn_full_set)

        # OPPONENT_2 LOGIC (NEW)
        active = battle_copy.opponent_2.active
        if active and revealed_pkmn_sets.get(active.name):
            pkmn_full_set = random.choices(
                revealed_pkmn_sets[active.name],
                weights=[s.pkmn_set.count for s in revealed_pkmn_sets[active.name]],
            )[0]
            populate_pkmn_from_set(active, pkmn_full_set)

        for pkmn in filter(lambda x: x.is_alive(), battle_copy.opponent_2.reserve):
            if not revealed_pkmn_sets.get(pkmn.name):
                continue
            pkmn_full_set = random.choices(
                revealed_pkmn_sets[pkmn.name],
                weights=[s.pkmn_set.count for s in revealed_pkmn_sets[pkmn.name]],
            )[0]
            populate_pkmn_from_set(pkmn, pkmn_full_set)

        # BOTH NEED UNREVEALED PKMN AND LOCKED MOVES
        populate_randombattle_unrevealed_pkmn(battle_copy)
        battle_copy.opponent_1.lock_moves()
        battle_copy.opponent_2.lock_moves()  # NEW
        
        sampled_battles.append((battle_copy, 1 / num_battles))

    return sampled_battles


def sample_randombattle_pokemon(existing_pokemon: list[Pokemon]) -> Pokemon:
    ok = False
    existing_pokemon_names = {pkmn.name for pkmn in existing_pokemon}

    sample_count = 0
    while not ok:
        sample_count += 1
        ok = True
        pkmn_name, pkmn_sets = random.choice(
            list(RandomBattleTeamDatasets.pkmn_sets.items())
        )
        pkmn_full_set = random.choice(pkmn_sets)
        pkmn = Pokemon(pkmn_name, pkmn_full_set.pkmn_set.level)
        if pkmn_name in existing_pokemon_names:
            ok = False
        if sample_count < 10 and _more_than_3_pokemon_weak_to_a_given_typing(
            existing_pokemon + [pkmn]
        ):
            ok = False
        if sample_count < 10 and _more_than_1_species(existing_pokemon + [pkmn]):
            ok = False
        if sample_count < 10 and _more_than_2_pokemon_of_any_type(
            existing_pokemon + [pkmn]
        ):
            ok = False
        if sample_count < 10 and _more_than_1_pokemon_with_4x_weakness(
            existing_pokemon + [pkmn]
        ):
            ok = False

    populate_pkmn_from_set(pkmn, pkmn_full_set)
    return pkmn


#
# From P.S. documentation:
#
# Team generation currently uses this feature to prevent teams from having:
#   more than 1 species
#   more than 3 Pokemon weak to any given typing,
#   more than 2 Pokemon of any given type,
#   or more than 1 Pokemon that shares a 4x weakness
def _more_than_1_species(team: list[Pokemon]) -> bool:
    pkmn_species = set([pkmn.get_species() for pkmn in team])
    return len(pkmn_species) < len(team)


def _more_than_3_pokemon_weak_to_a_given_typing(team: list[Pokemon]) -> bool:
    num_pkmn_weak_to_typing = {}
    for pkmn in team:
        for t in POKEMON_TYPE_INDICES.keys():
            if is_super_effective(t, pkmn.types):
                num_pkmn_weak_to_typing[t] = num_pkmn_weak_to_typing.get(t, 0) + 1

    if any(x > 3 for x in num_pkmn_weak_to_typing.values()):
        return True

    return False


def _more_than_2_pokemon_of_any_type(team: list[Pokemon]) -> bool:
    num_of_each_type = {}
    for pkmn in team:
        num_of_each_type[pkmn.types[0]] = num_of_each_type.get(pkmn.types[0], 0) + 1
        if len(pkmn.types) > 1:
            num_of_each_type[pkmn.types[1]] = num_of_each_type.get(pkmn.types[1], 0) + 1

    if any(x > 2 for x in num_of_each_type.values()):
        return True

    return False


def _more_than_1_pokemon_with_4x_weakness(team: list[Pokemon]) -> bool:
    num_of_each_4x_weakness = {}
    for pkmn in team:
        for t in POKEMON_TYPE_INDICES.keys():
            if type_effectiveness_modifier(t, pkmn.types) == 4:
                num_of_each_4x_weakness[t] = num_of_each_4x_weakness.get(t, 0) + 1

    if any(x > 1 for x in num_of_each_4x_weakness.values()):
        return True

    return False


def _battler_known_team_size(battler) -> int:
    """Number of pokemon we already know on a battler's team (active + reserve)."""
    size = len(battler.reserve)
    if battler.active is not None:
        size += 1
    return size


# take a Battle and fill in the unrevealed pkmn for the opposing side
def populate_randombattle_unrevealed_pkmn(battle: Battle):
    # In a multi battle the opposing side is two SEPARATE players (opponent_1 / p2a and
    # opponent_2 / p4b), each with their own team -- not one shared team of 6. Fill each
    # opponent's hidden slots independently.
    #
    # Every player in a random multi battle has the same team size, and our own side is
    # fully known from our request, so infer the per-player team size from our team rather
    # than assuming 6.
    team_size = max(
        _battler_known_team_size(battle.user_1),
        _battler_known_team_size(battle.user_2),
    )
    if team_size <= 0:
        team_size = 6  # defensive fallback; shouldn't happen once our request is known

    for opponent in (battle.opponent_1, battle.opponent_2):
        # Seed with this opponent's already-revealed team so sampled pokemon respect the
        # per-team species/composition constraints in sample_randombattle_pokemon.
        existing_pkmn = list(opponent.reserve)
        if opponent.active is not None:
            existing_pkmn.append(opponent.active)

        if len(existing_pkmn) >= team_size:
            continue

        logger.info(
            "Sampling {} unrevealed pokemon for {}".format(
                team_size - len(existing_pkmn), opponent.name
            )
        )
        while len(existing_pkmn) < team_size:
            pkmn = sample_randombattle_pokemon(existing_pkmn)
            existing_pkmn.append(pkmn)
            opponent.reserve.append(pkmn)
