import random
from database import get_user_data, update_user_field
from config import TARGET_PACKS
from prediction_engine import generate_v1_prediction

def calculate_sequence(balance):
    """
    Splits the current balance into 5 aggressive Martingale steps.
    Percentages: 2%, 5%, 10%, 25%, 58% (Sum = 100%)
    """
    # Ensure balance is at least 50 to avoid 0 bets
    safe_balance = max(balance, 50)
    
    seq = [
        int(safe_balance * 0.02), # Step 1
        int(safe_balance * 0.05), # Step 2
        int(safe_balance * 0.10), # Step 3
        int(safe_balance * 0.25), # Step 4
        int(safe_balance * 0.58)  # Step 5
    ]
    
    # Correction: If rounding made the sum > balance, adjust last step
    if sum(seq) > balance:
        seq[-1] = balance - sum(seq[:-1])
        
    return seq

def start_target_session(user_id, target_key):
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    # V1 Logic for first prediction
    user_data = get_user_data(user_id)
    history = user_data.get("history", [])
    initial_pred = random.choice(['Small', 'Big'])
    if history:
         pred, _ = generate_v1_prediction(history, initial_pred, 'win')
         initial_pred = pred

    start_bal = pack['start']
    
    session = {
        "target_amount": pack['target'],
        "current_balance": start_bal,
        "current_level_index": 0,
        "current_prediction": initial_pred,
        "is_active": True,
        "pack_name": pack['name'],
        # NEW: Store the calculated sequence in the session
        "sequence": calculate_sequence(start_bal)
    }
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    user_data = get_user_data(user_id)
    session = user_data.get("target_session")
    if not session or not session.get("is_active"): return None, "Ended"

    # Get bet amount from dynamic sequence
    level_idx = session["current_level_index"]
    sequence = session["sequence"]
    
    # Safety check if index out of bounds
    if level_idx >= len(sequence):
         level_idx = len(sequence) - 1
         
    bet_amount = sequence[level_idx]
    current_pred = session["current_prediction"]

    if outcome == 'win':
        session["current_balance"] += bet_amount
        session["current_level_index"] = 0
        
        # KEY CHANGE: Recalculate sequence on WIN based on NEW Balance (Compound Interest)
        session["sequence"] = calculate_sequence(session["current_balance"])
        
    else:
        session["current_balance"] -= bet_amount
        # On loss, we DO NOT recalculate. We stick to the plan to recover losses.
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

    # Next Prediction
    history = user_data.get("history", [])
    actual_outcome = current_pred if outcome == 'win' else ('Big' if current_pred == 'Small' else 'Small')
    history.append(actual_outcome)
    if len(history) > 5: history.pop(0)
    update_user_field(user_id, "history", history)

    new_pred, _ = generate_v1_prediction(history, current_pred, outcome)
    session["current_prediction"] = new_pred
    
    update_user_field(user_id, "target_session", session)
    return session, "Continue"