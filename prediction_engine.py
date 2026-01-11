import random
import hashlib
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, PATTERN_LENGTH, V5_SALT, TRUSTWIN_SALT
from database import get_user_data, update_user_field

# --- V5+ ENGINE (HASH + TREND CONFLUENCE + PLATFORM SALT) ---
def get_v5_logic(period_number, game_type="30s", history_data=None, platform="Tiranga"):
    """
    V5+ Logic: 
    1. Selects Salt based on Platform (TrustWin vs Others).
    2. SHA256(Period + Salt).
    3. Checks Confluence with History Trend.
    """
    # 1. SELECT SALT
    salt = TRUSTWIN_SALT if platform == "TrustWin" else V5_SALT
    
    # 2. Base Hash Prediction
    data_str = str(period_number) + salt
    try:
        hash_obj = hashlib.sha256(data_str.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()
    except:
        hash_hex = "0000"

    digit = None
    for char in reversed(hash_hex):
        if char.isdigit():
            digit = int(char)
            break
    if digit is None: digit = 0
    
    hash_pred = "Big" if digit > 4 else "Small"
    
    # 3. Confluence Check (Refining the prediction)
    confluence_txt = ""
    final_pred = hash_pred
    
    if history_data and len(history_data) >= 5:
        trend_pred = get_high_confidence_prediction(history_data)
        if trend_pred:
            if trend_pred == hash_pred:
                confluence_txt = "🔥"
            else:
                # If Trend is SUPER strong (streak of 5+), override Hash
                if is_super_trend(history_data):
                    final_pred = trend_pred
                    confluence_txt = "⚡"
    
    pattern_name = f"V5+ {platform} {confluence_txt}"
    return final_pred, pattern_name, digit

# --- SURESHOT / TREND HELPERS ---

def is_super_trend(history):
    if not history: return False
    recent = [x['o'] for x in history[-5:]]
    if len(set(recent)) == 1: return True
    return False

def get_high_confidence_prediction(history):
    if not history or len(history) < 10: return None
    recent = [x['o'] for x in history[-10:]]
    
    # Streak Logic (4 in a row)
    if recent[-1] == recent[-2] == recent[-3] == recent[-4]:
        return recent[-1]
    
    # ZigZag (ABAB)
    if (recent[-1] != recent[-2] and recent[-2] != recent[-3] and recent[-3] != recent[-4]):
        return "Small" if recent[-1] == "Big" else "Big"
        
    return None

def get_sureshot_confluence(period, history, game_type="30s"):
    """
    Used for the Sureshot Ladder. 
    Note: Always uses default Tiranga salt for safety unless passed otherwise.
    """
    v5_outcome, _, _ = get_v5_logic(period, game_type, history, platform="Tiranga")
    trend_outcome = get_high_confidence_prediction(history)
    
    if trend_outcome and trend_outcome == v5_outcome:
        return v5_outcome, True 
    return v5_outcome, False

# --- UTILS ---

def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL: return BETTING_SEQUENCE[level - 1]
    return 1

def get_number_for_outcome(outcome: str) -> int:
    return random.randint(0, 4) if outcome == "Small" else random.randint(5, 9)

# --- V1 to V4 ENGINES (RESTORED) ---

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

def generate_v1_prediction(api_history, current_prediction, outcome):
    # Pattern Matcher
    pattern_prediction, pattern_name = get_next_pattern_prediction(api_history)
    if pattern_prediction: return pattern_prediction, pattern_name
    if api_history: return api_history[-1]['o'], "V1 Streak"
    return random.choice(['Small', 'Big']), "V1 Random"

def generate_v2_prediction(history, current_prediction, outcome, current_level):
    # Martingale Switcher
    if outcome == 'win': return current_prediction, "V2 Winning Streak"
    if current_level == 2: return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch (Level 2)"
    return ('Small' if current_prediction == 'Big' else 'Big'), "V2 Switch"

def generate_v3_prediction():
    # Pure Random (Unpredictable)
    return ("Small" if random.randint(0, 9) <= 4 else "Big"), "V3 Random AI"

def generate_v4_prediction(history_outcomes, current_prediction, outcome, current_level):
    # Trend Follower
    if current_level == 4: return ('Small' if current_prediction == 'Big' else 'Big'), "V4 Safety Switch"
    if len(history_outcomes) >= 3:
        if history_outcomes[-1] == history_outcomes[-2] == history_outcomes[-3]:
            return history_outcomes[-1], "V4 Strong Trend"
    return ('Small' if current_prediction == 'Big' else 'Big'), "V4 Smart Switch"

# --- MAIN CONTROLLER (ROUTER) ---

def process_prediction_request(user_id, outcome, api_history=[]):
    """
    Decides which engine to use based on user settings.
    Legacy V1-V4 logic is preserved here.
    """
    state = get_user_data(user_id)
    mode = state.get("prediction_mode", "V5")
    current_prediction = state.get('current_prediction', "Small")
    current_level = state.get('current_level', 1)

    if mode == "V1":
        new_pred, p_name = generate_v1_prediction(api_history, current_prediction, outcome)
    elif mode == "V2":
        new_pred, p_name = generate_v2_prediction(api_history, current_prediction, outcome, current_level)
    elif mode == "V3":
        new_pred, p_name = generate_v3_prediction()
    elif mode == "V4":
        hist_strings = [x['o'] for x in api_history] if api_history else []
        new_pred, p_name = generate_v4_prediction(hist_strings, current_prediction, outcome, current_level)
    else: 
        # Default to V5 logic (Standard Tiranga salt if called this way)
        new_pred, p_name, _ = get_v5_logic("000", "30s", api_history, platform="Tiranga")

    update_user_field(user_id, "current_prediction", new_pred)
    update_user_field(user_id, "current_pattern_name", p_name)
    return new_pred, p_name
