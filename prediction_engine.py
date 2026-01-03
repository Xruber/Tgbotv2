import hashlib
from config import BETTING_SEQUENCE, MAX_LEVEL

def get_bet_unit(level):
    if level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level-1]
    return BETTING_SEQUENCE[-1]

def analyze_history_trend(history):
    """
    Returns 'Big', 'Small' or None based on last 5 results.
    """
    if not history or len(history) < 5: return None
    outcomes = [h['o'] for h in history[-5:]]
    
    # 1. ZigZag Check (B S B S)
    if outcomes[-1] != outcomes[-2] and outcomes[-2] != outcomes[-3]:
        # Predict opposite of last
        return "Small" if outcomes[-1] == "Big" else "Big"
    
    # 2. Streak Check (B B B)
    if outcomes[-1] == outcomes[-2] == outcomes[-3]:
        return outcomes[-1]
        
    return None

def get_v5_plus_prediction(period_number, history):
    """
    V5+ Logic: 
    1. SHA256 Hash of Period.
    2. Extract last digit.
    3. Confluence Check:
       - Strong Digits (0,1,2,3, 6,7,8,9): Trust SHA directly.
       - Weak Digits (4, 5): These are volatile. Check History Trend.
         If Trend exists, follow Trend. If no trend, default to SHA.
    """
    # 1. SHA256
    data_str = str(period_number)
    hash_hex = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
    
    # Find last numeric digit
    digit = 0
    for char in reversed(hash_hex):
        if char.isdigit():
            digit = int(char)
            break
            
    # Default SHA Prediction
    # 0-4 Small, 5-9 Big
    sha_pred = "Big" if digit >= 5 else "Small"
    
    # 2. Confluence (3-Level Accuracy)
    logic_note = f"V5 SHA ({digit})"
    
    # Volatility Check (4 and 5 are often switch points in Wingo)
    if digit in [4, 5]: 
        trend_pred = analyze_history_trend(history)
        if trend_pred:
            final_pred = trend_pred
            logic_note = f"V5+ Trend Fix ({digit})"
        else:
            final_pred = sha_pred
    else:
        final_pred = sha_pred
        
    return final_pred, logic_note
