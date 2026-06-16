//! Step 3b validation: a single-target move's damage lands on the *chosen* opposing slot,
//! not just the diagonal opponent.
//!
//! Run with a generation feature, e.g. `cargo test --features gen9 --test doubles_targeting`.
//! (Using `--test` builds only this file against the normal lib, so it is unaffected by the
//! not-yet-migrated in-crate `#[cfg(test)]` modules.)

use poke_engine::choices::{Choices, MOVES};
use poke_engine::engine::generate_instructions::generate_instructions_from_move_pair;
use poke_engine::engine::state::{MoveChoice, RelativeTarget};
use poke_engine::instruction::{Instruction, StateInstructions};
use poke_engine::state::{Move, PokemonMoveIndex, SideReference, State};

fn tackle() -> Move {
    Move {
        id: Choices::TACKLE,
        disabled: false,
        pp: 32,
        choice: MOVES.get(&Choices::TACKLE).unwrap().clone(),
    }
}

/// Build a default doubles state where side_one_1 knows Tackle and both opponents have
/// plenty of HP (so they don't faint and the Damage instruction is unambiguous).
fn setup() -> State {
    let mut state = State::default();
    state.side_one_1.get_active().moves.m0 = tackle();
    for side in [&mut state.side_two_1, &mut state.side_two_2] {
        let active = side.get_active();
        active.hp = 300;
        active.maxhp = 300;
    }
    state
}

fn damaged_sides(results: &[StateInstructions]) -> Vec<SideReference> {
    results
        .iter()
        .flat_map(|r| r.instruction_list.iter())
        .filter_map(|i| match i {
            Instruction::Damage(d) => Some(d.side_ref),
            _ => None,
        })
        .collect()
}

#[test]
fn diagonal_target_damages_side_two_1() {
    let mut state = setup();
    let s1_1 = MoveChoice::Move(PokemonMoveIndex::M0, RelativeTarget::DiagonalOpponent);
    let results = generate_instructions_from_move_pair(
        &mut state,
        &s1_1,
        &MoveChoice::None,
        &MoveChoice::None,
        &MoveChoice::None,
        false,
    );
    let dmg = damaged_sides(&results);
    assert!(
        dmg.contains(&SideReference::SideTwo_1),
        "diagonal target should damage SideTwo_1, got {:?}",
        dmg
    );
    assert!(
        !dmg.contains(&SideReference::SideTwo_2),
        "diagonal target should NOT damage SideTwo_2, got {:?}",
        dmg
    );
}

#[test]
fn other_target_damages_side_two_2() {
    let mut state = setup();
    let s1_1 = MoveChoice::Move(PokemonMoveIndex::M0, RelativeTarget::OtherOpponent);
    let results = generate_instructions_from_move_pair(
        &mut state,
        &s1_1,
        &MoveChoice::None,
        &MoveChoice::None,
        &MoveChoice::None,
        false,
    );
    let dmg = damaged_sides(&results);
    assert!(
        dmg.contains(&SideReference::SideTwo_2),
        "other-opponent target should damage SideTwo_2, got {:?}",
        dmg
    );
    assert!(
        !dmg.contains(&SideReference::SideTwo_1),
        "other-opponent target should NOT damage SideTwo_1, got {:?}",
        dmg
    );
}

/// side_one_2's diagonal is SideTwo_2, and its "other" opponent is SideTwo_1 — verify the
/// mapping is correct from the second slot's perspective too.
#[test]
fn second_slot_targeting_mapping() {
    let mut state = State::default();
    state.side_one_2.get_active().moves.m0 = tackle();
    for side in [&mut state.side_two_1, &mut state.side_two_2] {
        let active = side.get_active();
        active.hp = 300;
        active.maxhp = 300;
    }

    let diagonal = generate_instructions_from_move_pair(
        &mut state,
        &MoveChoice::None,
        &MoveChoice::Move(PokemonMoveIndex::M0, RelativeTarget::DiagonalOpponent),
        &MoveChoice::None,
        &MoveChoice::None,
        false,
    );
    assert!(
        damaged_sides(&diagonal).contains(&SideReference::SideTwo_2),
        "side_one_2 diagonal should be SideTwo_2, got {:?}",
        damaged_sides(&diagonal)
    );

    let other = generate_instructions_from_move_pair(
        &mut state,
        &MoveChoice::None,
        &MoveChoice::Move(PokemonMoveIndex::M0, RelativeTarget::OtherOpponent),
        &MoveChoice::None,
        &MoveChoice::None,
        false,
    );
    assert!(
        damaged_sides(&other).contains(&SideReference::SideTwo_1),
        "side_one_2 other-opponent should be SideTwo_1, got {:?}",
        damaged_sides(&other)
    );
}
