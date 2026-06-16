from dataclasses import dataclass
from enum import StrEnum

from .poke_engine import *


class Weather(StrEnum):
    NONE = "none"
    SUN = "sun"
    RAIN = "rain"
    SAND = "sand"
    HAIL = "hail"
    SNOW = "snow"
    HARSH_SUN = "harshsun"
    HEAVY_RAIN = "heavyrain"


class Terrain(StrEnum):
    NONE = "none"
    GRASSY = "grassyterrain"
    ELECTRIC = "electricterrain"
    MISTY = "mistyterrain"
    PSYCHIC = "psychicterrain"


class PokemonIndex(StrEnum):
    P0 = "0"
    P1 = "1"
    P2 = "2"
    P3 = "3"
    P4 = "4"
    P5 = "5"


@dataclass
class IterativeDeepeningResult:
    """
    Result of an Iterative Deepening Expectiminimax Search (doubles: four slots).

    :param side_one_1: The moves for side one's first slot
    :param side_one_2: The moves for side one's second slot
    :param side_two_1: The moves for side two's first slot
    :param side_two_2: The moves for side two's second slot
    :param matrix: A flat vector representing the 4-D payoff matrix of the search,
        indexed as (((s1_1 * len(s1_2) + s1_2) * len(s2_1) + s2_1) * len(s2_2) + s2_2)
    :param depth_searched: The depth that was searched to
    """

    side_one_1: list[str]
    side_one_2: list[str]
    side_two_1: list[str]
    side_two_2: list[str]
    matrix: list[float]
    depth_searched: int

    @classmethod
    def _from_rust(cls, rust_result):
        return cls(
            side_one_1=rust_result.s1_1,
            side_one_2=rust_result.s1_2,
            side_two_1=rust_result.s2_1,
            side_two_2=rust_result.s2_2,
            matrix=rust_result.matrix,
            depth_searched=rust_result.depth_searched,
        )

    def get_safest_move(self) -> tuple[str, str]:
        """
        Get the safest (side_one_1, side_one_2) move pair: the pair that maximizes the
        worst case over all opposing (side_two_1, side_two_2) combinations.

        :return: the safest move for each of side one's two slots
        :rtype: tuple[str, str]
        """
        n_s1_1 = len(self.side_one_1)
        n_s1_2 = len(self.side_one_2)
        n_s2_1 = len(self.side_two_1)
        n_s2_2 = len(self.side_two_2)

        safest_value = float("-inf")
        best = (
            self.side_one_1[0] if n_s1_1 else "",
            self.side_one_2[0] if n_s1_2 else "",
        )
        vec_index = 0
        for i in range(n_s1_1):
            for j in range(n_s1_2):
                worst_case_this_row = float("inf")
                for _ in range(n_s2_1):
                    for _ in range(n_s2_2):
                        score = self.matrix[vec_index]
                        vec_index += 1
                        if score < worst_case_this_row:
                            worst_case_this_row = score
                if worst_case_this_row > safest_value:
                    safest_value = worst_case_this_row
                    best = (self.side_one_1[i], self.side_one_2[j])

        return best


@dataclass
class MctsSideResult:
    """
    Result of a Monte Carlo Tree Search for a single side

    :param move_choice: The move that was chosen
    :type move_choice: str
    :param total_score: The total score of the chosen move
    :type total_score: float
    :param visits: The number of times the move was chosen
    :type visits: int
    """

    move_choice: str
    total_score: float
    visits: int


@dataclass
class MctsResult:
    """
    Result of a Monte Carlo Tree Search (doubles: four slots).

    :param side_one_1: Result for side one's first slot
    :param side_one_2: Result for side one's second slot
    :param side_two_1: Result for side two's first slot
    :param side_two_2: Result for side two's second slot
    :param total_visits: Total number of monte carlo iterations
    """

    side_one_1: list[MctsSideResult]
    side_one_2: list[MctsSideResult]
    side_two_1: list[MctsSideResult]
    side_two_2: list[MctsSideResult]
    total_visits: int

    @classmethod
    def _from_rust(cls, rust_result):
        def convert(side):
            return [
                MctsSideResult(
                    move_choice=i.move_choice,
                    total_score=i.total_score,
                    visits=i.visits,
                )
                for i in side
            ]

        return cls(
            side_one_1=convert(rust_result.s1_1),
            side_one_2=convert(rust_result.s1_2),
            side_two_1=convert(rust_result.s2_1),
            side_two_2=convert(rust_result.s2_2),
            total_visits=rust_result.iteration_count,
        )


def monte_carlo_tree_search(
    state: State, duration_ms: int = 1000, threads: int = 1
) -> MctsResult:
    """
    Perform monte-carlo-tree-search on the given state and for the given duration

    :param state: the state to search through
    :type state: State
    :param duration_ms: time in milliseconds to run the search
    :type duration_ms: int
    :param threads: number of threads to use for the search
    :type threads: int
    :return: the result of the search
    :rtype: MctsResult
    """
    return MctsResult._from_rust(mcts(state, duration_ms, threads))


def iterative_deepening_expectiminimax(
    state: State, duration_ms: int = 1000
) -> IterativeDeepeningResult:
    """
    Perform an iterative-deepening expectiminimax search on the given state and for the given duration

    :param state: the state to search through
    :type state: State
    :param duration_ms: time in milliseconds to run the search
    :type duration_ms: int
    :return: the result of the search
    :rtype: IterativeDeepeningResult
    """
    return IterativeDeepeningResult._from_rust(id(state, duration_ms))
