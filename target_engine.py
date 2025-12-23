import random
from database import get_user_data, update_user_field
from config import TARGET_PACKS
from prediction_engine import generate_v4_prediction

def calculate_sequence(balance):
    """
    Splits the current balance into 5 aggressive Martingale steps.
    Percentages: 2%, 5%, 10%, 25%, 58% (Sum = 100%)
    """
    safe_balance = max(balance, 50)
    
    seq = [
        int(safe_balance * 0.02), # Step 1
        int(safe_balance * 0.05), # Step 2
        int(safe_balance * 0.10), # Step 3
        int(safe_balance * 0.25), # Step 4
        int(safe_balance * 0.58)  # Step 5
    ]
    
    if sum(seq) > balance:
        seq[-1] = balance - sum(seq[:-1])
        
    return seq

def start_target_session(user_id, target_key, last_period_num):
    """
    Starts session. 
    last_period_num: The number user entered (e.g., 800). 
    We start predicting for 801.
    """
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    # v4 Logic for first prediction
    initial_pred, _ = generate_v4_prediction()

    start_bal = pack['start']
    
    session = {
        "target_amount": pack['target'],
        "current_balance": start_bal,
        "current_level_index": 0,
        "current_prediction": initial_pred,
        "is_active": True,
        "pack_name": pack['name'],
        "sequence": calculate_sequence(start_bal),
        # NEW: Store the Period Number (User input + 1)
        "current_period": last_period_num + 1 
    }
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    user_data = get_user_data(user_id)
    session = user_data.get("target_session")
    if not session or not session.get("is_active"): return None, "Ended"

    # Get bet amount
    level_idx = session["current_level_index"]
    sequence = session["sequence"]
    
    if level_idx >= len(sequence):
         level_idx = len(sequence) - 1
         
    bet_amount = sequence[level_idx]

    if outcome == 'win':
        session["current_balance"] += bet_amount
        session["current_level_index"] = 0
        session["sequence"] = calculate_sequence(session["current_balance"])
    else:
        session["current_balance"] -= bet_amount
        if level_idx < len(sequence) - 1:
            session["current_level_index"] += 1
        else:
            session["current_level_index"] = len(sequence) - 1

    # Check End Conditions
    if session["current_balance"] >= session["target_amount"]:
        update_user_field(user_id, "target_session", None)
        update_user_field(user_id, "target_access", None)
        return session, "TargetReached"
    
    if session["current_balance"] <= 0:
        update_user_field(user_id, "target_session", None)
        update_user_field(user_id, "target_access", None) 
        return session, "Bankrupt"

    # Generate Next Prediction
    new_pred, _ = generate_v4_prediction()
    session["current_prediction"] = new_pred
    
    # NEW: Increment Period Number for the next round
    session["current_period"] += 1
    
    update_user_field(user_id, "target_session", session)
    return session, "Continue"