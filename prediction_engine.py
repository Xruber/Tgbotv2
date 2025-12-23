import random
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

# --- HELPER: Pattern Matcher ---
def get_next_pattern_prediction(history: list) -> tuple[Optional[str], str]:
    """
    Checks if the recent history matches any of the 6 config patterns.
    Uses PATTERN_LENGTH (4) to look at the immediate past.
    """
    if not history: return None, "Random"
    
    # ⭐ FIX: Slice exactly the last 4 items for pattern matching
    recent_history = history[-PATTERN_LENGTH:] 
    recent_len = len(recent_history)
    
    for pattern_list, pattern_name in ALL_PATTERNS:
        pattern_len = len(pattern_list)
        
        # 1. Partial Match (Building the pattern)
        if recent_len < pattern_len:
            if recent_history == pattern_list[:recent_len]:
                return pattern_list[recent_len], pattern_name
                
        # 2. Full Match (Pattern complete)
        # If we have a full pattern (e.g., BBBB), we predict it continues/loops
        elif recent_len == pattern_len:
            if recent_history == pattern_list:
                return pattern_list[0], pattern_name
                
    return None, None

# --- V1: Rebuilt (Patterns -> Streak) ---
def generate_v1_prediction(history, current_prediction, outcome):
    """
    V1 LOGIC:
    1. Check 6 Patterns.
    2. If no pattern, Follow the Winner (Streak).
    """
    # 1. Check Patterns
    pattern_prediction, pattern_name = get_next_pattern_prediction(history)
    
    if pattern_prediction:
        return pattern_prediction, pattern_name
    
    # 2. No Pattern? Continue with the winning prediction (Streak)
    # This replaces the old Martingale randomizer.
    if history:
        last_result = history[-1]
        return last_result, "V1 Streak (Follow Winner)"
    
    # Fallback for very first bet
    return random.choice(['Small', 'Big']), "V1 Random Start"

# --- V2: Streak on Win / Switch on Loss ---
def generate_v2_prediction(history, current_prediction, outcome, current_level):
    if outcome == 'win': 
        return current_prediction, "V2 Winning Streak"
    
    # On Loss
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

# --- V4: Adaptive Trend & Safety (NEW) ---
def generate_v4_prediction(history, current_prediction, outcome, current_level):
    """
    V4 Strategy:
    1. Safety: If Level 4, Force Switch (Anticipate chop).
    2. Pattern: Check if a known pattern is forming.
    3. Trend: If last 3 results are same, follow them.
    4. Default: Switch (Zig-Zag).
    """
    
    # 1. Level 4 Safety Protocol (Avoid Level 5)
    if current_level == 4:
        # Switch to opposite of last bet to catch a chop/break
        next_pred = 'Small' if current_prediction == 'Big' else 'Big'
        return next_pred, "V4 Safety Switch (Lvl 4)"

    # 2. Pattern Matching
    pat_pred, pat_name = get_next_pattern_prediction(history)
    if pat_pred:
        return pat_pred, f"V4 Pattern ({pat_name})"

    # 3. Trend Analysis (Look at last 3)
    # Since MAX_HISTORY_LENGTH is now 12, we can safely look back 3 steps
    if len(history) >= 3:
        last_three = history[-3:]
        # If last 3 are identical (e.g. Big, Big, Big), Follow Trend
        if last_three[0] == last_three[1] == last_three[2]:
            return last_three[0], "V4 Strong Trend"

    # 4. Default Behavior: Zig-Zag (Switch)
    next_pred = 'Small' if current_prediction == 'Big' else 'Big'
    return next_pred, "V4 Smart Switch"

# --- MAIN CONTROLLER ---
def process_prediction_request(user_id, outcome):
    state = get_user_data(user_id)
    mode = state.get("prediction_mode", "V2")
    current_prediction = state.get('current_prediction', "Small")
    current_level = state.get('current_level', 1)

    # Update History (Storage)
    actual_outcome = current_prediction if outcome == 'win' else ('Big' if current_prediction == 'Small' else 'Small')
    history = state.get('history', [])
    history.append(actual_outcome)
    
    # Keep last 12 items in DB
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
    else: # V2 Default
        new_pred, p_name = generate_v2_prediction(history, current_prediction, outcome, current_level)

    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    return new_pred, p_name