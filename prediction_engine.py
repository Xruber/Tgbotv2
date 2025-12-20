import random
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, MAX_HISTORY_LENGTH, PATTERN_PROBABILITY
from database import get_user_data, update_user_field

def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1

def get_next_pattern_prediction(history: list) -> tuple[Optional[str], str]:
    """Helper: Analyzes history to find a matching pattern."""
    if not history:
        return random.choice(['Small', 'Big']), "Random (No History)"
    
    recent_history = history[-MAX_HISTORY_LENGTH:]
    recent_len = len(recent_history)
    
    for pattern_list, pattern_name in ALL_PATTERNS:
        pattern_len = len(pattern_list)
        # Check partial match
        if recent_len < pattern_len:
            if recent_history == pattern_list[:recent_len]:
                return pattern_list[recent_len], pattern_name
        # Check full match (restart loop)
        elif recent_len == pattern_len:
            if recent_history == pattern_list:
                return pattern_list[0], pattern_name
                
    return None, "Random (No Pattern Match)"

# --- V1 LOGIC (Original) ---
def generate_v1_prediction(user_id, current_prediction, outcome, history):
    """Original Logic: Random chance to follow Martingale trend on loss."""
    pattern_prediction, pattern_name = get_next_pattern_prediction(history)
    new_prediction = current_prediction
    
    if outcome == 'win':
        if pattern_prediction:
            new_prediction = pattern_prediction
        else:
            new_prediction = 'Big' if current_prediction == 'Small' else 'Small'
    elif outcome == 'loss':
        # 60% chance to stick with the prediction (Martingale trend)
        if random.random() < PATTERN_PROBABILITY:
            new_prediction = current_prediction
        else:
            if pattern_prediction:
                new_prediction = pattern_prediction
            else:
                new_prediction = 'Big' if current_prediction == 'Small' else 'Small'
                
    return new_prediction, pattern_name

# --- V2 LOGIC (New) ---
def generate_v2_prediction(user_id, current_prediction, outcome, history, current_level):
    """New Logic: Win=Repeat, L2=Swap, L3=Pattern."""
    new_prediction = current_prediction
    pattern_name = "Analyzing..."

    if outcome == 'win':
        # Rule: Win -> Streak (Repeat)
        new_prediction = current_prediction
        pattern_name = "V2 Winning Streak"
        
    elif outcome == 'loss':
        if current_level == 2:
            # Rule: 1st Loss -> Opposite
            new_prediction = 'Small' if current_prediction == 'Big' else 'Big'
            pattern_name = "V2 Switch (Level 2)"
        elif current_level >= 3:
            # Rule: 2nd+ Loss -> Pattern
            pat_pred, pat_name = get_next_pattern_prediction(history)
            if pat_pred:
                new_prediction = pat_pred
                pattern_name = f"V2 Pattern ({pat_name})"
            else:
                new_prediction = 'Small' if current_prediction == 'Big' else 'Big'
                pattern_name = "V2 Random Switch"
        else:
             new_prediction = 'Small' if current_prediction == 'Big' else 'Big'
             pattern_name = "V2 Switch"

    return new_prediction, pattern_name

def process_prediction_request(user_id, outcome):
    """Main wrapper to decide which logic to use."""
    state = get_user_data(user_id)
    mode = state.get("prediction_mode", "V2")
    current_prediction = state.get('current_prediction', random.choice(['Small', 'Big']))
    current_level = state.get('current_level', 1)

    # 1. Update History
    actual_outcome = current_prediction if outcome == 'win' else ('Big' if current_prediction == 'Small' else 'Small')
    history = state.get('history', [])
    history.append(actual_outcome)
    if len(history) > MAX_HISTORY_LENGTH: history.pop(0)
    update_user_field(user_id, "history", history)

    # 2. Select Logic
    if mode == "V1":
        new_pred, p_name = generate_v1_prediction(user_id, current_prediction, outcome, history)
    else:
        new_pred, p_name = generate_v2_prediction(user_id, current_prediction, outcome, history, current_level)

    # 3. Save
    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    
    return new_pred, p_name