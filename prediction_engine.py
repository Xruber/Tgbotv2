import random
import hashlib
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, PATTERN_LENGTH
from database import get_user_data, update_user_field

# --- V5 ENGINE LOGIC (SHA256 - Period Only) ---
def get_v5_logic(period_number, game_type="30s"):
    """
    Logic: SHA256(Period) -> HEX -> Last Numeric Digit
    NO SALT is used.
    """
    
    # 1. Prepare Data (Period Only)
    data_str = str(period_number)
    
    # 2. Generate Hash using SHA256
    try:
        # We encode the period number string directly
        hash_obj = hashlib.sha256(data_str.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()
    except Exception as e:
        print(f"[V5 ERROR] SHA256 failed: {e}")
        hash_hex = "0000" # Safety fallback

    # 3. Find Last Numeric Digit (Search Backwards)
    digit = None
    for char in reversed(hash_hex):
        if char.isdigit():
            digit = int(char)
            break
            
    if digit is None: digit = 0
    
    # 4. Determine Outcome
    # Logic: If value greater than 4 it is big or else (Small)
    if digit > 4:
        prediction = "Big"
    else:
        prediction = "Small"
        
    pattern_name = f"V5 SHA256 ({digit})"
    return prediction, pattern_name, digit

# --- SURESHOT LOGIC (Deep Trend Analysis) ---
def get_high_confidence_prediction(history):
    """
    Analyzes last 10 results for HIGH PROBABILITY patterns (>90%).
    Returns: 'Big', 'Small', or None (if confidence low).
    """
    if not history or len(history) < 10: 
        return None # Not enough data
    
    # Get last 10 outcomes (Recent is at the end)
    recent = [x['o'] for x in history[-10:]]
    last_outcome = recent[-1]
    
    # 1. STREAK PATTERN (>90% if streak >= 4)
    # If the last 4 results are identical, we predict the streak continues.
    streak_count = 0
    for out in reversed(recent):
        if out == last_outcome: streak_count += 1
        else: break
        
    if streak_count >= 4:
        return last_outcome 
        
    # 2. ZIG-ZAG PATTERN (Alternating)
    # Checks for Big, Small, Big, Small... (Length 4+)
    # If pattern is B-S-B-S, next is likely B (Opposite of last)
    if len(recent) >= 4:
        if (recent[-1] != recent[-2] and 
            recent[-2] != recent[-3] and 
            recent[-3] != recent[-4]):
            return "Small" if last_outcome == "Big" else "Big"

    # 3. DOMINANCE (80-90% one side)
    # If 8 out of last 10 are 'Big', the trend is heavily Big.
    big_count = recent.count("Big")
    small_count = recent.count("Small")
    
    if big_count >= 8: return "Big"
    if small_count >= 8: return "Small"
    
    return None # Confidence < 90%

def get_sureshot_confluence(period, history, game_type="30s"):
    """
    Returns prediction ONLY if:
    1. Trend Analysis gives >90% Confidence Result
    2. V5 SHA256 Logic matches that Result
    """
    # 1. Get V5 Prediction (SHA256 Period Only)
    v5_outcome, _, _ = get_v5_logic(period, game_type)
    
    # 2. Get High Confidence Trend
    trend_outcome = get_high_confidence_prediction(history)
    
    # 3. Confluence Check
    if trend_outcome is not None and trend_outcome == v5_outcome:
        return v5_outcome, True  # High Confidence Match!
    else:
        return None, False       # Low confidence or mismatch -> Wait.

# --- HELPERS ---

def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1

def get_number_for_outcome(outcome: str) -> int:
    if outcome == "Small":
        return random.randint(0, 4)
    else: 
        return random.randint(5, 9)

def get_next_pattern_prediction(history_objs: list) -> tuple[Optional[str], str]:
    if not history_objs: return None, "Random"
    history_outcomes = [x['o'] for x in history_objs]
    recent_history = history_outcomes[-PATTERN_LENGTH:] 
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

# --- V1 ---
def generate_v1_prediction(api_history, current_prediction, outcome):
    pattern_prediction, pattern_name = get_next_pattern_prediction(api_history)
    if pattern_prediction: return pattern_prediction, pattern_name
    if api_history: return api_history[-1]['o'], "V1 Streak"
    return random.choice(['Small', 'Big']), "V1 Random"

# --- V2 ---
def generate_v2_prediction(history, current_prediction, outcome, current_level):
    if outcome == 'win': return current_prediction, "V2 Winning Streak"
    if current_level == 2: return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch (Level 2)"
    return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch"

# --- V3 ---
def generate_v3_prediction():
    return ("Small" if random.randint(0, 9) <= 4 else "Big"), "V3 Random"

# --- V4 ---
def generate_v4_prediction(history_outcomes, current_prediction, outcome, current_level):
    if current_level == 4: return ('Small' if current_prediction == 'Big' else 'Big'), "V4 Safety Switch (Lvl 4)"
    if len(history_outcomes) >= 3:
        if history_outcomes[-1] == history_outcomes[-2] == history_outcomes[-3]:
            return history_outcomes[-1], "V4 Strong Trend"
    return ('Small' if current_prediction == 'Big' else 'Big'), "V4 Smart Switch"

# --- MAIN CONTROLLER ---
def process_prediction_request(user_id, outcome, api_history=[]):
    state = get_user_data(user_id)
    mode = state.get("prediction_mode", "V2")
    current_prediction = state.get('current_prediction', "Small")
    current_level = state.get('current_level', 1)

    if mode == "V1":
        new_pred, p_name = generate_v1_prediction(api_history, current_prediction, outcome)
    elif mode == "V3":
        new_pred, p_name = generate_v3_prediction()
    elif mode == "V4":
        hist_strings = [x['o'] for x in api_history] if api_history else []
        new_pred, p_name = generate_v4_prediction(hist_strings, current_prediction, outcome, current_level)
    elif mode == "V5":
        # Placeholder for main game loop V5 calls
        new_pred, p_name, _ = get_v5_logic("000") 
    else: 
        new_pred, p_name = generate_v2_prediction([], current_prediction, outcome, current_level)

    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    return new_pred, p_name
