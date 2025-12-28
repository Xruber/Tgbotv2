import random
import hashlib
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, MAX_HISTORY_LENGTH, PATTERN_LENGTH, V5_SALTS
from database import get_user_data, update_user_field

def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1

# --- Number Shot Generator ---
def get_number_for_outcome(outcome: str) -> int:
    if outcome == "Small":
        return random.randint(0, 4)
    else: 
        return random.randint(5, 9)

# --- V5 ENGINE LOGIC (SHA256 + "+" Separator) ---
def get_v5_logic(period_number, game_type="30s"):
    """
    Logic: SHA256(Period + "+" + Salt) -> Last Numeric Digit
    """
    # 1. Get Salt
    salt = V5_SALTS.get(game_type, "admin")
    
    # 2. Hash (NOW WITH PLUS SIGN)
    # User Request: "20251227100051428+admin"
    data_str = str(period_number) + "+" + str(salt)
    
    hash_obj = hashlib.sha256(data_str.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    
    # 3. Find Last Numeric Digit (Search Backwards)
    digit = None
    for char in reversed(hash_hex):
        if char.isdigit():
            digit = int(char)
            break
            
    if digit is None: digit = 0
    
    # 🔍 DEBUG PRINT (Verifying the + is there)
    print(f"\n[V5 DEBUG] Period: {period_number} | Type: {game_type}")
    print(f"[V5 DEBUG] Input String: '{data_str}'") 
    print(f"[V5 DEBUG] Hash: {hash_hex}")
    print(f"[V5 DEBUG] Digit Found: {digit}\n")
    
    # 4. Determine Outcome
    if digit < 5:
        prediction = "Small"
    else:
        prediction = "Big"
        
    pattern_name = f"V5 SHA256 ({digit})"
    return prediction, pattern_name, digit

# --- HELPER: Pattern Matcher ---
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

# --- V2/V3/V4 ---
def generate_v2_prediction(history, current_prediction, outcome, current_level):
    if outcome == 'win': return current_prediction, "V2 Winning Streak"
    if current_level == 2: return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch (Level 2)"
    return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch"

def generate_v3_prediction():
    return ("Small" if random.randint(0, 9) <= 4 else "Big"), "V3 Random"

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
        new_pred, p_name = "Wait...", "V5 (Live)"
    else: 
        new_pred, p_name = generate_v2_prediction([], current_prediction, outcome, current_level)

    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    return new_pred, p_name