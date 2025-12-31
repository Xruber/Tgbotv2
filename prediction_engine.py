import random
import hashlib
from typing import Optional
from config import BETTING_SEQUENCE, MAX_LEVEL, ALL_PATTERNS, PATTERN_LENGTH, V5_SALT
from database import get_user_data, update_user_field
import argon2.low_level

# --- V5 ENGINE LOGIC (Argon2i Custom) ---
def get_v5_logic(period_number, game_type="30s"):
    """
    Logic: Argon2i(Period, Salt="ar-lottery", Mem=16, Iter=2, Len=16) -> HEX -> Last Numeric Digit
    """
    
    # 1. Configuration (Updated Salt)
    salt_str = V5_SALT
    period_str = str(period_number)
    
    # 2. Generate Hash using Argon2i
    try:
        raw_hash = argon2.low_level.hash_secret_raw(
            secret=period_str.encode('utf-8'),
            salt=salt_str.encode('utf-8'),
            time_cost=2,        # Iterations
            memory_cost=16,     # Memory in KiB
            parallelism=1,      # Standard parallelism
            hash_len=16,        # Hash Length
            type=argon2.low_level.Type.I
        )
        # Convert raw bytes to HEX string
        hash_hex = raw_hash.hex()
        
    except Exception as e:
        print(f"[V5 ERROR] Argon2 failed: {e}")
        # Fallback to a dummy safe hash if library fails
        hash_hex = hashlib.sha256(period_str.encode()).hexdigest()

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
        
    pattern_name = f"V5 Argon2i ({digit})"
    return prediction, pattern_name, digit

# --- SURESHOT LOGIC (Exact Number Match) ---
def get_history_number_prediction(history):
    """
    Analyzes last 10 PERIOD NUMBERS' winning numbers to predict the next one.
    Method: Sum of last 10 winning numbers -> Last Digit.
    """
    if not history or len(history) < 10: 
        return random.randint(0, 9) # Not enough data
    
    # Get last 10 items (Tail of the list)
    recent = history[-10:] 
    
    # Extract the winning numbers 'r'
    numbers = [x['r'] for x in recent]
    
    # Algorithm: Sum of last 10 numbers % 10
    total_sum = sum(numbers)
    predicted_number = total_sum % 10
    
    return predicted_number

def get_sureshot_confluence(period, history, game_type="30s"):
    """
    Returns a prediction ONLY if V5 Argon Digit == History Prediction Digit.
    STRICT EXACT NUMBER MATCH.
    """
    # 1. Get V5 Argon2i Data (Outcome, Pattern, Digit)
    v5_outcome, _, v5_digit = get_v5_logic(period, game_type)
    
    # 2. Get History Number Prediction (Digit)
    hist_digit = get_history_number_prediction(history)
    
    # 3. STRICT COMPARISON
    # Example: Argon=6, Hist=6 -> Match.
    # Example: Argon=6, Hist=8 -> Mismatch (Even though both are Big).
    if v5_digit == hist_digit:
        return v5_outcome, True 
    else:
        # Mismatch -> Wait
        return None, False

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
