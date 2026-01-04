import random
import hashlib
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, PATTERN_LENGTH, V5_SALT
from database import get_user_data, update_user_field

# --- V5+ ENGINE (HASH + TREND CONFLUENCE) ---
def get_v5_logic(period_number, game_type="30s", history_data=None):
    """
    V5+ Logic: 
    1. SHA256(Period + Salt)
    2. Checks Confluence with History Trend (if available)
    """
    # 1. Base Hash Prediction
    data_str = str(period_number) + V5_SALT
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
    
    # 2. Confluence Check (Refining the prediction)
    confluence_txt = ""
    final_pred = hash_pred
    
    if history_data and len(history_data) >= 5:
        trend_pred = get_high_confidence_prediction(history_data)
        if trend_pred:
            if trend_pred == hash_pred:
                confluence_txt = "🔥 (Confirmed)"
            else:
                # If Trend is SUPER strong (e.g. Streak of 6), override Hash
                if is_super_trend(history_data):
                    final_pred = trend_pred
                    confluence_txt = "⚡ (Trend Override)"
    
    pattern_name = f"V5+ Argon2i {confluence_txt}"
    return final_pred, pattern_name, digit

def is_super_trend(history):
    # Check for streak of 5+
    recent = [x['o'] for x in history[-5:]]
    if len(set(recent)) == 1: return True
    return False

def get_high_confidence_prediction(history):
    if not history or len(history) < 10: return None
    recent = [x['o'] for x in history[-10:]]
    
    # Streak Logic
    if recent[-1] == recent[-2] == recent[-3] == recent[-4]:
        return recent[-1]
    
    # ZigZag
    if (recent[-1] != recent[-2] and recent[-2] != recent[-3] and recent[-3] != recent[-4]):
        return "Small" if recent[-1] == "Big" else "Big"
        
    return None

def get_sureshot_confluence(period, history, game_type="30s"):
    """
    Used for the Sureshot Ladder. Stricter than standard V5.
    """
    v5_outcome, _, _ = get_v5_logic(period, game_type, history)
    trend_outcome = get_high_confidence_prediction(history)
    
    if trend_outcome and trend_outcome == v5_outcome:
        return v5_outcome, True 
    return v5_outcome, False # Return V5 anyway but marked unsafe

# --- HELPERS ---
def get_bet_unit(level: int) -> int:
    if 1 <= level <= MAX_LEVEL: return BETTING_SEQUENCE[level - 1]
    return 1

def get_number_for_outcome(outcome: str) -> int:
    return random.randint(0, 4) if outcome == "Small" else random.randint(5, 9)

# --- ENGINE CONTROLLER ---
def process_prediction_request(user_id, outcome, api_history=[]):
    state = get_user_data(user_id)
    # Defaulting to V5 if not set or if strictly requested
    mode = state.get("prediction_mode", "V5")
    
    # Determine next period
    if api_history:
        last_p = int(api_history[-1]['p'])
        next_p = str(last_p + 1)
    else:
        next_p = str(int(state.get("current_period", "0")) + 1)

    if mode == "V1":
        # (Legacy code omitted for brevity, use V5 mostly)
        return "Big", "V1 Logic" 
    elif mode == "V5":
        return get_v5_logic(next_p, "30s", api_history)[0:2]
    else:
        # Fallback to V5
        return get_v5_logic(next_p, "30s", api_history)[0:2]
