import hashlib
import random
from config import BETTING_SEQUENCE, MAX_LEVEL

def get_bet_unit(level):
    """Returns the betting multiplier for the current level."""
    # Safety check for index out of bounds
    if level < 1: level = 1
    if level > MAX_LEVEL: level = MAX_LEVEL
    return BETTING_SEQUENCE[level-1]

def analyze_history_trend(history):
    """
    Analyzes the last 5 results to find a trend pattern.
    Returns: 'Big', 'Small', or None
    """
    if not history or len(history) < 5: return None
    outcomes = [h['o'] for h in history[-5:]] # Get last 5 outcomes
    
    # 1. ZigZag Pattern (B S B S -> Predict B)
    # Checks if the last 3 are alternating
    if outcomes[-1] != outcomes[-2] and outcomes[-2] != outcomes[-3]:
        # Predict the opposite of the last result
        return "Small" if outcomes[-1] == "Big" else "Big"
    
    # 2. Streak Pattern (B B B -> Predict B)
    # Checks if the last 3 are the same
    if outcomes[-1] == outcomes[-2] == outcomes[-3]:
        return outcomes[-1]
        
    return None

def get_v5_logic(period_number, game_type="30s", history=None):
    """
    V5+ Engine Logic:
    1. SHA256 Hash of the Period Number.
    2. Extract the last numeric digit from the hash.
    3. Confluence Check:
       - If digit is 0,1,2,3 -> Trust Small
       - If digit is 6,7,8,9 -> Trust Big
       - If digit is 4 or 5 (Volatile) -> Check History Trend.
    
    Returns: (Prediction, Pattern_Name, Digit)
    """
    # 1. SHA256 Hash
    data_str = str(period_number)
    hash_hex = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
    
    # 2. Find Last Numeric Digit
    digit = 0
    for char in reversed(hash_hex):
        if char.isdigit():
            digit = int(char)
            break
    
    # 3. Base Prediction (Standard SHA)
    # 0-4 is Small, 5-9 is Big
    sha_prediction = "Big" if digit >= 5 else "Small"
    
    # 4. Confluence Check (The V5+ Upgrade)
    pattern_name = f"V5 Argon ({digit})"
    
    # If we have history, we can do advanced checks for volatile digits 4 & 5
    if history and digit in [4, 5]:
        trend_pred = analyze_history_trend(history)
        if trend_pred:
            final_pred = trend_pred
            pattern_name = f"V5+ Trend Fix ({digit})"
        else:
            final_pred = sha_prediction
    else:
        final_pred = sha_prediction
        
    return final_pred, pattern_name, digit
