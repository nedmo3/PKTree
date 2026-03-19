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


import csv

def load_pokemon_from_csv(filename):
    pokemon_dict = {}

    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            # Basic fields
            name = row["Species"]  # use Species instead of Pokemon (removes "-1")
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

if __name__ == "__main__":
    pokemon_dict = load_pokemon_from_csv("top3.csv")
    pokemon_list = ["Barbaracle-1", "Hawlucha-1", "Carbink-1"]
    write_team_to_file(pokemon_dict, pokemon_list, "top3.txt")