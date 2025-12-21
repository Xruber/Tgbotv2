import random
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, MAX_HISTORY_LENGTH, PATTERN_PROBABILITY
from database import get_user_data, update_user_field

def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1

# --- New: Number Shot Generator ---
def get_number_for_outcome(outcome: str) -> int:
    """Returns 0-4 for Small, 5-9 for Big."""
    if outcome == "Small":
        return random.randint(0, 4)
    else: # Big
        return random.randint(5, 9)

# --- V3 LOGIC (New) ---
def generate_v3_prediction():
    """V3: Pure Random 0-9 Logic."""
    num = random.randint(0, 9)
    prediction = "Small" if num <= 4 else "Big"
    pattern_name = f"V3 Analysed Result"
    return prediction, pattern_name

def get_next_pattern_prediction(history: list) -> tuple[Optional[str], str]:
    if not history: return random.choice(['Small', 'Big']), "Random (No History)"
    recent_history = history[-MAX_HISTORY_LENGTH:]
    recent_len = len(recent_history)
    for pattern_list, pattern_name in ALL_PATTERNS:
        pattern_len = len(pattern_list)
        if recent_len < pattern_len:
            if recent_history == pattern_list[:recent_len]:
                return pattern_list[recent_len], pattern_name
        elif recent_len == pattern_len:
            if recent_history == pattern_list:
                return pattern_list[0], pattern_name
    return None, "Random (No Pattern Match)"

def generate_v1_prediction(history, current_prediction, outcome):
    pattern_prediction, pattern_name = get_next_pattern_prediction(history)
    new_prediction = current_prediction
    if outcome == 'win':
        new_prediction = pattern_prediction if pattern_prediction else ('Big' if current_prediction == 'Small' else 'Small')
    elif outcome == 'loss':
        if random.random() < PATTERN_PROBABILITY: new_prediction = current_prediction
        else: new_prediction = pattern_prediction if pattern_prediction else ('Big' if current_prediction == 'Small' else 'Small')
    return new_prediction, pattern_name

def generate_v2_prediction(history, current_prediction, outcome, current_level):
    if outcome == 'win': return current_prediction, "V2 Winning Streak"
    if current_level == 2: return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch (Level 2)"
    if current_level >= 3:
        pat_pred, pat_name = get_next_pattern_prediction(history)
        return (pat_pred, f"V2 Pattern ({pat_name})") if pat_pred else ('Small' if current_prediction == 'Big' else 'Big', "V2 Random Switch")
    return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch"

def process_prediction_request(user_id, outcome):
    state = get_user_data(user_id)
    mode = state.get("prediction_mode", "V2")
    current_prediction = state.get('current_prediction', "Small")
    current_level = state.get('current_level', 1)

    # Update History
    actual_outcome = current_prediction if outcome == 'win' else ('Big' if current_prediction == 'Small' else 'Small')
    history = state.get('history', [])
    history.append(actual_outcome)
    if len(history) > MAX_HISTORY_LENGTH: history.pop(0)
    update_user_field(user_id, "history", history)

    # Select Logic
    if mode == "V1":
        new_pred, p_name = generate_v1_prediction(history, current_prediction, outcome)
    elif mode == "V3":
        new_pred, p_name = generate_v3_prediction()
    else: # V2 Default
        new_pred, p_name = generate_v2_prediction(history, current_prediction, outcome, current_level)

    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    return new_pred, p_name