import random
import csv

from teams.team_converter import export_to_dict, export_to_packed
from data import pokedex
from fp.helpers import normalize_name


# Forme-keyword aliases -> the keyword Showdown actually uses in its forme id.
_FORME_KEYWORD_ALIASES = {
    "alolan": "alola",
    "galarian": "galar",
    "hisuian": "hisui",
}


def _to_showdown_species(display_name):
    """Convert a Battle-Tree display name into a valid Showdown species.

    e.g. "Ninetales (Alola Form)"     -> "ninetales-alola"
         "Rotom (Frost Rotom)"        -> "rotom-frost"
         "Wishiwashi (School Form)"   -> "Wishiwashi"  (battle-only forme -> base)
         "Tornadus (Incarnate Forme)" -> "Tornadus"    (default forme -> base)

    Names without a parenthesised forme are returned unchanged. The Showdown export
    format reads "Nickname (Species)" with the species in parens, so leaving these
    display names as-is makes the converter read e.g. "Alola Form" as the species.
    """
    display_name = display_name.strip()
    if "(" not in display_name or ")" not in display_name:
        return display_name

    base = display_name[: display_name.index("(")].strip()
    descriptor = display_name[display_name.index("(") + 1 : display_name.index(")")].strip()
    if not descriptor:
        return base

    # The forme keyword is the first token of the descriptor:
    # "Alola Form" -> Alola, "Sensu Style" -> Sensu, "Frost Rotom" -> Frost.
    keyword = descriptor.split()[0]
    keyword = _FORME_KEYWORD_ALIASES.get(normalize_name(keyword), keyword)

    candidate_id = normalize_name("{}-{}".format(base, keyword))
    entry = pokedex.get(candidate_id)
    # Only keep the forme if it's a real, team-buildable species. Battle-only formes
    # (Wishiwashi-School, Minior-Meteor, ...) and default-forme descriptors
    # (Incarnate, Midday, ...) aren't buildable -> fall back to the base species.
    if entry is not None and not entry.get("battleOnly"):
        return entry["name"]
    return base


class Pokemon:
    def __init__(
        self,
        id, 
        name,
        item,
        ability,
        ev_hp=0,
        ev_atk=0,
        ev_def=0,
        ev_spa=0,
        ev_spd=0,
        ev_speed=0,
        nature="Hardy",
        move1="",
        move2="",
        move3="",
        move4="",
    ):
        self.name = name
        self.id = id
        self.item = item
        self.ability = ability

        self.ev_hp = ev_hp
        self.ev_atk = ev_atk
        self.ev_def = ev_def
        self.ev_spa = ev_spa
        self.ev_spd = ev_spd
        self.ev_speed = ev_speed

        self.nature = nature

        self.moves = [move1, move2, move3, move4]

    def format_evs(self):
        parts = []
        if self.ev_hp:
            parts.append(f"{self.ev_hp} HP")
        if self.ev_atk:
            parts.append(f"{self.ev_atk} Atk")
        if self.ev_def:
            parts.append(f"{self.ev_def} Def")
        if self.ev_spa:
            parts.append(f"{self.ev_spa} SpA")
        if self.ev_spd:
            parts.append(f"{self.ev_spd} SpD")
        if self.ev_speed:
            parts.append(f"{self.ev_speed} Spe")

        return " / ".join(parts) if parts else ""

    def to_text(self):
        lines = []

        # Name + item
        lines.append(f"{self.name} @ {self.item}")

        # Ability
        lines.append(f"Ability: {self.ability}")

        # EVs
        evs = self.format_evs()
        if evs:
            lines.append(f"EVs: {evs}")

        # Nature
        lines.append(f"{self.nature} Nature")

        # Moves
        for move in self.moves:
            if move:
                lines.append(f"- {move}")

        return "\n".join(lines)

class Trainer:
    # #,Class,Trainer,Team,Image,
    def __init__(self, id, prefix, name, team, image) :
        self.id = id
        self.prefix = prefix
        self.name = name
        self.team = team
        self.image = image

    # sets the active team to a new random sample of the whole set of possibilities
    def chooseRandomTeam(self, team_size) :
        i = 0 # odds of a bad team are low, so I'm going with low effort code :)
        while i < 25 : 
            self.active_team = random.sample(self.team, team_size)
            if self.teamCheck() : 
                return
            i += 1
    
    # Returns true if there aren't any issues with the team (mainly just having the same pokemon multiple times)
    def teamCheck(self) :
        for pkmn_1 in self.active_team : 
            for pkmn_2 in self.active_team : 
                if pkmn_1.id == pkmn_2.id :
                    continue
                if pkmn_1.name == pkmn_2.name :
                    return False
                if "-mega" in pkmn_1.name and "-mega" in pkmn_2.name : 
                    return False
        # we're good. Now need to remove "-mega" so it doesn't send an already mega evolved pkmn out
        for p in self.active_team : 
            if "-mega" in p.name : 
                p.name = p.name.split("-")[0]
        return True


    def prettyName(self) :
        return f"{self.prefix} {self.name}"

    # Showdown export text for the currently-chosen active_team (joined Pokemon.to_text() blocks)
    def team_export_string(self) :
        return "\n\n".join(p.to_text() for p in self.active_team)

    # Convert the chosen active_team into foul-play's team formats.
    # Returns (packed_string, team_dict):
    #   packed_string -> the packed string passed to PSWebsocketClient.update_team()
    #   team_dict     -> list of per-pokemon dicts (foul-play's team_dict format)
    def to_foulplay_team(self) :
        export = self.team_export_string()
        return export_to_packed(export), export_to_dict(export)


class TeamMaker : 

    def __init__(self, pkmn_input_file="TreePokemonAll.csv", trainer_input_file="TreeTrainersAl.csv") :
        self.pokemon_dict = self.load_pokemon_from_csv(pkmn_input_file)
        for k in self.pokemon_dict.keys() : 
            if '(' in k : 
                print(k)
        self.load_trainers_from_csv(trainer_input_file)

    # Checks that two trainers aren't running the same pokemon. True -> no issues.
    def duo_check(self, trainer_1, trainer_2) : 
        for pkmn_1 in trainer_1.active_team : 
            for pkmn_2 in trainer_2.active_team : 
                if pkmn_1.name == pkmn_2.name :
                    return False
        return True
        
    # what we'll want to call to get our opponents based on the battle number
    def get_opponents(self, battle_number=1, team_size = 2) : 
        print('a')
        list_to_choose = None
        if battle_number == 50 : 
            list_to_choose = self.trainer_list_50
        elif battle_number % 10 == 0 :
            list_to_choose = self.trainer_list_boss
        elif battle_number < 10 : 
            list_to_choose = self.trainer_list_1_10
        elif battle_number < 20 : 
            list_to_choose = self.trainer_list_11_20
        elif battle_number < 30 : 
            list_to_choose = self.trainer_list_21_30
        elif battle_number < 40 : 
            list_to_choose = self.trainer_list_31_40
        elif battle_number < 50 : 
            list_to_choose = self.trainer_list_41_50
        else : 
            list_to_choose = self.trainer_list_51
        tries = 0
        while tries < 39 : 
            opps = random.sample(list_to_choose, 2)
            for opp in opps : 
                opp.chooseRandomTeam(team_size)
            if self.duo_check(opps[0], opps[1]) :
                return opps
            tries += 1


    def write_team_to_file(pokemon_dict, pokemon_list, filename):
        with open(filename, "w", encoding="utf-8") as f:
            # get Pokemon objects for each name in pokemon_list
            pokemon_objects = []
            for name in pokemon_list:
                if name in pokemon_dict:
                    pokemon_objects.append(pokemon_dict[name])
                else:
                    raise ValueError(f"Pokemon {name} not found in dictionary")
            for i, pokemon in enumerate(pokemon_objects):
                f.write(pokemon.to_text())

                # Add blank line between Pokémon (but not after last)
                if i != len(pokemon_list) - 1:
                    f.write("\n\n")

    def load_trainers_from_csv(self, filename) :
        self.trainer_list_1_10 = []
        self.trainer_list_11_20 = []
        self.trainer_list_21_30 = []
        self.trainer_list_31_40 = []
        self.trainer_list_41_50 = []
        self.trainer_list_51 = []

        self.trainer_list_50 = []
        self.trainer_list_boss = []

        self.all_trainers = []

        with open(filename, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header row
            for row in reader:
                if not row or not row[0].strip():
                    continue  # skip blank / trailing empty lines
                team = [p.strip() for p in row[3].split(",") if p.strip()]
                t_len = len(team)
                for t in range (t_len):
                    team[t] = self.pokemon_dict[team[t]]
                trainer = Trainer(
                    id=int(row[0]),     # "#"
                    prefix=row[1],      # "Class"
                    name=row[2],        # "Trainer"
                    team=team,          # "Team" -> list of "Name-count" strings
                    image=row[-1],      # real sprite id, e.g. "Preschooler-M"
                )
                self.all_trainers.append(trainer)

        # need to assign trainers to the list of trainers per battle # in the tree
        for i in range (50) : # 0,49 -> 1-10
            self.trainer_list_1_10.append(self.all_trainers[i])
        for i in range (30,70) : # 30,79 -> 11-20
            self.trainer_list_11_20.append(self.all_trainers[i])
        for i in range (50,90) : 
            self.trainer_list_21_30.append(self.all_trainers[i])
        for i in range (70,110) : 
            self.trainer_list_31_40.append(self.all_trainers[i])
        for i in range (90,130) : 
            self.trainer_list_41_50.append(self.all_trainers[i])
        for i in range (90,190) : # 
            self.trainer_list_51.append(self.all_trainers[i])
        for i in (190,191) : # RED and BLUE
            self.trainer_list_50.append(self.all_trainers[i])
        for i in range(192, 205) : 
            self.trainer_list_boss.append(self.all_trainers[i])

        # return(
        #     self.trainer_list_1_10,
        #     self.trainer_list_11_20,
        #     self.trainer_list_21_30,
        #     self.trainer_list_31_40,
        #     self.trainer_list_41_50,
        #     self.trainer_list_51,
        #     self.trainer_list_50,
        #     self.trainer_list_boss
        # )

    def load_pokemon_from_csv(self, filename):
        pokemon_dict = {}

        with open(filename, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                # Basic fields
                name = _to_showdown_species(row["Species"])  # forme display name -> Showdown species
                id = row["Pokemon"]
                nature = row["Nature"]
                item = row["Item"]

                # Moves
                move1 = row["Move1"]
                move2 = row["Move2"]
                move3 = row["Move3"]
                move4 = row["Move4"]

                # Ability (pick Ability1 by default)
                ability = row["Ability1"]

                # EVs (these are the FIRST EV block)
                ev_hp = int(row["evHP"])
                ev_atk = int(row["evAtk"])
                ev_def = int(row["evDef"])
                ev_spa = int(row["evSpA"])
                ev_spd = int(row["evSpD"])
                ev_spe = int(row["evSpe"])

                # Create Pokemon object
                pokemon = Pokemon(
                    name=name,
                    id=id,
                    item=item,
                    ability=ability,
                    ev_hp=ev_hp,
                    ev_atk=ev_atk,
                    ev_def=ev_def,
                    ev_spa=ev_spa,
                    ev_spd=ev_spd,
                    ev_speed=ev_spe,
                    nature=nature,
                    move1=move1,
                    move2=move2,
                    move3=move3,
                    move4=move4,
                )

                pokemon_dict[id] = pokemon

        return pokemon_dict

    # if __name__ == "__main__":
    #     pokemon_dict = load_pokemon_from_csv("TreePokemonAll.csv")
    #     pokemon_list = pokemon_dict.keys()
    #     write_team_to_file(pokemon_dict, pokemon_list, "TreePkmnAll.txt")