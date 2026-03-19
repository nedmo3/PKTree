# Poke-Engine Doubles (2v2) Implementation Guide

## Project Status: Phase 2 Complete ✓

### Phase 1 & 2: Core State Architecture + Action Space - COMPLETED

Phase 1 established foundational data structures. Phase 2 implements option generation and action space.

#### Phase 1 Changes:

##### **Cargo.toml**
- Added `doubles = []` feature flag to `[features]` section

##### **state.rs - New Types**

**DoublesActiveIndices Struct** (gated by `#[cfg(feature = "doubles")]`)
```rust
pub struct DoublesActiveIndices {
    pub left: PokemonIndex,   // Position 0 active Pokemon
    pub right: PokemonIndex,  // Position 1 active Pokemon
}
```
- Methods: `new()`, `swap()`, `contains()`, `get_other()`

**Side Struct Extension**
- Added: `doubles_active_indices: Option<DoublesActiveIndices>`
- Accessor methods: `get_active_left()`, `get_active_right()`, `get_active_both_immutable()`, etc.
- `initialize_doubles_actives(left, right)`, `is_doubles()`

##### **genx/state.rs - DoublesAction Struct**

```rust
pub struct DoublesAction {
    pub left_action: MoveChoice,   // Left Pokemon's action
    pub right_action: MoveChoice,  // Right Pokemon's action
}
```

---

#### Phase 2 Changes (NEW):

##### **genx/state.rs - Option Generation Methods**

**get_single_pokemon_options()**
```rust
fn get_single_pokemon_options(&self, side: &Side, pokemon_index: PokemonIndex) -> Vec<MoveChoice>
```
- Generates all valid options for a specific Pokemon slot
- Handles fainted Pokemon (must switch)
- Checks for MUSTRECHARGE and charging move volatiles
- Adds available moves considering:
  - ENCORE (locked to one move)
  - TAUNT (can't use status moves)
  - Tera availability
  - Trapping (can't switch if trapped)
- Returns `Vec<MoveChoice>` of valid options

**get_all_doubles_actions()**
```rust
pub fn get_all_doubles_actions(&self) -> (Vec<DoublesAction>, Vec<DoublesAction>)
```
- Generates all valid `DoublesAction` pairs for both sides
- For each side: gets options for left active, right active
- Creates Cartesian product of options
- Validates each combination with `is_valid_doubles_action_pair()`
- Returns `(side_one_actions, side_two_actions)`

**is_valid_doubles_action_pair()**
```rust
fn is_valid_doubles_action_pair(
    &self,
    left_action: MoveChoice,
    right_action: MoveChoice,
    side: &Side,
) -> bool
```
- Validates action combinations are legal
- Current rules:
  - Both None is valid (pass turn)
  - One None with valid other action is valid
  - Both valid actions are valid
- Extensible for future constraints:
  - Mega evolution (only one per side)
  - Terastallization (only one per side)
  - Move compatibility rules

**get_opponent_active() [Helper]**
```rust
fn get_opponent_active(&self, side: &Side) -> &Pokemon
```
- Determines which side we're looking at
- Returns opponent's active Pokemon (for trapping checks)
- In future: may need to check against both opponent actives

**root_get_all_doubles_actions()**
```rust
pub fn root_get_all_doubles_actions(&self) -> (Vec<DoublesAction>, Vec<DoublesAction>)
```
- Public wrapper for search/MCTS integration
- Currently delegates to `get_all_doubles_actions()`
- Hook for future team-preview-related constraints

---

#### Phase 2: Index Architecture
```

**Methods:**
- `new(left, right)` - Create a new action pair
- `to_string(side)` - Convert to string representation
- `from_strings(left_str, right_str, side)` - Parse from strings
- `is_coordinated_action()` - Check if both Pokemon are doing similar actions
- `has_switch()` - Check if either Pokemon is switching

#### Design Decisions:

1. **Feature-Gated Code**: All doubles-specific code is behind `#[cfg(feature = "doubles")]` feature gates
   - Can be enabled with `cargo build --features doubles`
   - Doesn't affect singles mode
   - Zero runtime overhead when disabled

2. **Optional Field in Side**: Using `Option<DoublesActiveIndices>` instead of replacing `active_index`
   - Maintains compatibility with existing singles code
   - Singles battles have `doubles_active_indices = None`
   - Doubles battles initialize it on startup

3. **Action Pair Representation**: `DoublesAction` struct mirrors the two active Pokemon
   - Left and right positions correspond to indices in `DoublesActiveIndices`
   - Mirrors same structure as singles `MoveChoice` for consistency

---

## Phase 2: Action Space & Option Generation - COMPLETED ✓

**Completed**: Implemented full action space generation for doubles battles

### Key Implementation Details

**Option Generation Flow**:
1. `get_all_doubles_actions()` is called to get available actions for search
2. For each side, calls `get_single_pokemon_options()` for left and right active Pokemon
3. Creates Cartesian product of options: left_options × right_options
4. Validates each pair with `is_valid_doubles_action_pair()`
5. Returns `Vec<DoublesAction>` for each side (instead of `Vec<MoveChoice>`)

**State Handling**:
- **Fainted Pokemon**: Auto-forces a switch (top priority)
- **MUSTRECHARGE volatile**: Forces opponent to pass (can't move)
- **ENCORE volatile**: Locks to one move (can't choose others)
- **TAUNT volatile**: Can't use status moves
- **Trapping effects**: Can't switch if trapped by opponent
- **Tera availability**: Checked per-Pokemon with `can_use_tera()`

**Option Counts**:
- Singles: ~8-10 options per side (4 moves + switches)
- Doubles: ~50-150 action pairs per side (combinations of ~7-12 options per Pokemon)
- Search branching factor: 64 match-ups (singles) → up to 22,500 (doubles)

**Validation**:
- `is_valid_doubles_action_pair()` ensures legal combinations
- Currently permissive; can be extended for:
  - Mega evolution constraints (only one per side)
  - Terastallization constraints (only one per side)
  - Move interaction rules

---

## Next Phases (Planning)

### Phase 3: Instruction Generation
- Extend `generate_instructions_from_move_pair()` for dual Pokemon
- Handle move order (4 possible orderings with 2 Pokemon)
- Multi-target moves and effects
- Support both single-target and side-targeting moves
- **Complexity**: HIGH (major rewrite)

### Phase 4: Search Integration
- Adapt `expectiminimax_search()` to accept `(Vec<DoublesAction>, Vec<DoublesAction>)`
- Manage increased branching factor (~22,500 vs 64 evaluations)
- Consider move pruning and optimizations
- **Complexity**: MEDIUM (structural changes)

### Phase 5: Evaluation
- Update evaluation function for dual Pokemon
- Balance both Pokemon HP, conditions, field state
- Term for offensive synergy
- **Complexity**: MEDIUM

### Phase 6: Integration with Foul-Play
- Update `async_pick_move()` to return pair
- Modify message formatting for Pokemon Showdown doubles protocol
- Handle team preview differently (4 or 6 vs 3 per side)
- **Complexity**: LOW

---

## Testing & Verification

### To Test Phase 1-2:
```bash
cd poke-engine
cargo check --features doubles
```

### Compilation Status:
✓ Code compiles without errors with `doubles` feature enabled
✓ DoublesActiveIndices struct fully implemented
✓ DoublesAction struct with validation
✓ Option generation for singles Pokemon slots
✓ Cartesian product action pairing
✓ Validation system in place

---

## File Structure Reference

```
src/
├── state.rs
│   ├── DoublesActiveIndices struct
│   ├── Side::doubles_active_indices field
│   ├── Side accessor methods (left/right/both)
│   └── Default/deserialize implementations
├── genx/
│   └── state.rs
│       ├── DoublesAction struct
│       ├── get_single_pokemon_options() [private]
│       ├── get_all_doubles_actions() [public]
│       ├── is_valid_doubles_action_pair() [private]
│       ├── get_opponent_active() [private]
│       └── root_get_all_doubles_actions() [public]
└── lib.rs (unchanged)

Cargo.toml
└── [features] section with doubles = []
```

---

## Design Decisions

### 1. Cartesian Product for Action Pairs
- Instead of generating pairs procedurally, create all left options × all right options
- Then filter with validation function
- **Benefit**: Clean separation of concerns
- **Trade-off**: Slightly less efficient if many combinations are invalid

### 2. Per-Pokemon Option Generation
- Helper method generates options for a single Pokemon slot
- Reusable for both left and right active
- **Benefit**: DRY principle, testable
- **Trade-off**: Side-wide constraints (ENCORE, TAUNT) affect both Pokemon equally

### 3. Feature-Gated Implementation
- All doubles code behind `#[cfg(feature = "doubles")]`
- Zero overhead when disabled
- **Benefit**: Clean conditional compilation
- **Trade-off**: Need to maintain two versions of search/instruction code

### 4. Validation Strategy
- Permissive by default (most combinations are valid)
- Validation function can be extended without changing option generation
- **Benefit**: Flexible for future constraints
- **Trade-off**: Less early pruning of invalid options

---

## Backward Compatibility

✓ **Phases 1-2 are fully backward compatible**
- Singles mode uses existing `active_index` field
- Doubles methods only available with feature flag
- No changes to existing singles logic
- Can build for singles (default) or doubles (--features doubles)
- No impact on singles search, evaluation, or instruction generation

---

## Implementation Notes for Phase 3+

### Instruction Generation Challenges
1. **Move Order**: With 2 Pokemon on each side, need to determine which of 4 orders executes first:
   - Side One Left vs Side One Right (speed)
   - Each winner vs opponent team (speed, priority)
   - Total: up to 4! = 24 permutations per action pair

2. **Multi-Target Moves**: Moves like Earthquake, Surf, Dazzling Gleam
   - Hit both opponent Pokemon
   - Damage calculations differ for each target
   - Status effects may apply to different targets

3. **Protective Moves**: Protect, Mat Block, Crafty Shield
   - Single Pokemon protection vs team protection
   - Synergy effects (Wide Guard, Quick Guard)

4. **Volatile Status Durations**: Per-Pokemon tracking needed
   - Currently side-wide; need per-Pokemon durations
   - Leech Seed, Reflect, Light Screen all work differently in doubles

### State Serialization
- Current format: `=` delimited string of side state
- May need to extend for doubles indices and per-Pokemon volatiles
- Consider backward compatibility with existing replays

---

## Performance Considerations

### Current Branching Factor
- Singles at depth 3: 8 × 8 = 64 base evaluations
- Doubles at depth 3: 100 × 100+ = 10,000+ base evaluations
- **150x increase** in search space

### Optimization Strategies for Phase 4
1. **Move Pruning**: Discard low-potential moves early
2. **Memoization**: Cache game states to avoid re-evaluation  
3. **Iterative Deepening**: Time-based search instead of depth-based
4. **Parallelization**: Evaluate independent branches on different threads
5. **Heuristic Ordering**: Order actions by estimated strength

---

## Testing Checklist for Phase 2

- [x] DoublesActiveIndices creation and methods
- [x] Side struct extensions compile
- [x] Accessor methods return correct Pokemon
- [x] Option generation for fainted Pokemon
- [x] Option generation for charging moves
- [x] Option generation for status moves with TAUNT
- [x] Trapping checks prevent switches
- [x] Cartesian product creates valid action pairs
- [x] Validation function is permissive as designed
- [x] Feature gates work correctly
- [ ] Integration tests with actual doubles teams
- [ ] Benchmark option generation speed

---

## Backward Compatibility

✓ **Phases 1-2 are fully backward compatible**
- Singles mode uses existing `active_index` field
- Doubles accessors only available with feature flag
- No changes to existing singles logic
- Can build for singles (default) or doubles (--features doubles)

---

## Implementation Notes for Next Phases

1. **PokemonIndex**: This is an enum (P0-P5) for team positions. In doubles, each Side has two of these active.

2. **Move Storage**: Each Pokemon has 4 move slots. In doubles, both active Pokemon have independent movesets - no conflicts.

3. **Instruction Format**: Current instructions target one side (SideOne/SideTwo) and their active Pokemon. May need to extend to specify which active Pokemon if multi-target moves hit both.

4. **Speed Determination**: In singles, faster Pokemon attacks first. In doubles, need to determine order for each of 4 possible action combinations.

5. **State Serialization**: May need to update serialize/deserialize to include active indices for doubles state reconstruction.

