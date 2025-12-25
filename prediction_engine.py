import random
import hashlib # NEW IMPORT
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, MAX_HISTORY_LENGTH, PATTERN_LENGTH, PATTERN_PROBABILITY
from database import get_user_data, update_user_field

def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1

# --- Number Shot Generator ---
def get_number_for_outcome(outcome: str) -> int:
    """Returns 0-4 for Small, 5-9 for Big."""
    if outcome == "Small":
        return random.randint(0, 4)
    else: # Big
        return random.randint(5, 9)

# --- V5 ENGINE LOGIC (SHA256) ---
def get_v5_logic(period_number):
    """
    Logic: SHA256(Period) -> Last Char -> Dec -> % 10 -> Prediction
    Returns: (Prediction, PatternName, Digit)
    """
    # 1. Hash the period number
    period_str = str(period_number)
    hash_obj = hashlib.sha256(period_str.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    
    # 2. Extract last character
    last_char = hash_hex[-1]
    
    # 3. Convert Hex to Decimal
    decimal_val = int(last_char, 16)
    
    # 4. Final Digit
    digit = decimal_val % 10
    
    # 5. Determine Outcome
    if digit < 5:
        prediction = "Small"
    else:
        prediction = "Big"
        
    pattern_name = f"V5 Hash (Ends: {last_char} -> {digit})"
    
    return prediction, pattern_name, digit

# --- HELPER: Pattern Matcher ---
def get_next_pattern_prediction(history: list) -> tuple[Optional[str], str]:
    if not history: return None, "Random"
    
    recent_history = history[-PATTERN_LENGTH:] 
    recent_len = len(recent_history)
    
    for pattern_list, pattern_name in ALL_PATTERNS:
        pattern_len = len(pattern_list)
        
        if recent_len < pattern_len:
            if recent_history == pattern_list[:recent_len]:
                return pattern_list[recent_len], pattern_name
                
        elif recent_len == pattern_len:
            if recent_history == pattern_list:
                return pattern_list[0], pattern_name
                
    return None, None

# --- V1: Rebuilt (Patterns -> Streak) ---
def generate_v1_prediction(history, current_prediction, outcome):
    pattern_prediction, pattern_name = get_next_pattern_prediction(history)
    if pattern_prediction:
        return pattern_prediction, pattern_name
    
    if history:
        last_result = history[-1]
        return last_result, "V1 Streak (Follow Winner)"
    
    return random.choice(['Small', 'Big']), "V1 Random Start"

# --- V2: Streak on Win / Switch on Loss ---
def generate_v2_prediction(history, current_prediction, outcome, current_level):
    if outcome == 'win': 
        return current_prediction, "V2 Winning Streak"
    
    if current_level == 2: 
        return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch (Level 2)"
    if current_level >= 3:
        pat_pred, pat_name = get_next_pattern_prediction(history)
        if pat_pred: return pat_pred, f"V2 Pattern ({pat_name})"
        return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Random Switch"
    
    return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch"

# --- V3: Pure Random ---
def generate_v3_prediction():
    num = random.randint(0, 9)
    prediction = "Small" if num <= 4 else "Big"
    pattern_name = f"V3 Random (Rolled {num})"
    return prediction, pattern_name

# --- V4: Adaptive Trend & Safety ---
def generate_v4_prediction(history, current_prediction, outcome, current_level):
    if current_level == 4:
        next_pred = 'Small' if current_prediction == 'Big' else 'Big'
        return next_pred, "V4 Safety Switch (Lvl 4)"

    pat_pred, pat_name = get_next_pattern_prediction(history)
    if pat_pred:
        return pat_pred, f"V4 Pattern ({pat_name})"

    if len(history) >= 3:
        last_three = history[-3:]
        if last_three[0] == last_three[1] == last_three[2]:
            return last_three[0], "V4 Strong Trend"

    next_pred = 'Small' if current_prediction == 'Big' else 'Big'
    return next_pred, "V4 Smart Switch"

# --- MAIN CONTROLLER ---
def process_prediction_request(user_id, outcome):
    state = get_user_data(user_id)
    mode = state.get("prediction_mode", "V2")
    current_prediction = state.get('current_prediction', "Small")
    current_level = state.get('current_level', 1)

    # Update History
    actual_outcome = current_prediction if outcome == 'win' else ('Big' if current_prediction == 'Small' else 'Small')
    history = state.get('history', [])
    history.append(actual_outcome)
    
    if len(history) > MAX_HISTORY_LENGTH: 
        history.pop(0)
        
    update_user_field(user_id, "history", history)

    # Select Logic
    if mode == "V1":
        new_pred, p_name = generate_v1_prediction(history, current_prediction, outcome)
    elif mode == "V3":
        new_pred, p_name = generate_v3_prediction()
    elif mode == "V4":
        new_pred, p_name = generate_v4_prediction(history, current_prediction, outcome, current_level)
    elif mode == "V5":
        # V5 depends on the NEXT period number, which we don't know yet.
        # We return a placeholder. The real calculation happens in 'receive_period_number' in main.py
        new_pred, p_name = "Wait...", "V5 (Waiting for Period)"
    else: 
        new_pred, p_name = generate_v2_prediction(history, current_prediction, outcome, current_level)

    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    return new_pred, p_name