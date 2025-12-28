import random
from database import get_user_data, update_user_field
from config import TARGET_PACKS
from prediction_engine import get_v5_logic
from api_helper import get_game_data

def calculate_sequence(balance):
    # Safety: Ensure we don't bet 0 or negative
    safe_balance = max(balance, 50)
    
    # Aggressive compounding sequence (can be adjusted)
    seq = [
        int(safe_balance * 0.01), # Step 1: 1%
        int(safe_balance * 0.02), # Step 2: 2%
        int(safe_balance * 0.05), # Step 3: 5%
        int(safe_balance * 0.12), # Step 4: 12%
        int(safe_balance * 0.30), # Step 5: 30%
        int(safe_balance * 0.50)  # Step 6: All-in/Recovery
    ]
    # Cap the last bet to not exceed balance
    if sum(seq) > balance: 
        seq[-1] = balance - sum(seq[:-1])
    return seq

def start_target_session(user_id, target_key, game_type):
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    # Fetch Live Period
    current_period, _ = get_game_data(game_type)
    if not current_period: return None 

    # Generate First Prediction
    initial_pred, _, _ = get_v5_logic(current_period, game_type)

    start_bal = pack['start']
    
    session = {
        "target_amount": pack['target'],
        "start_balance": start_bal,  # <--- LOGIC ADDED: For Profit Calculation
        "current_balance": start_bal,
        "current_level_index": 0,
        "current_prediction": initial_pred,
        "is_active": True,
        "pack_name": pack['name'],
        "sequence": calculate_sequence(start_bal),
        "current_period": current_period,
        "game_type": game_type
    }
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    user_data = get_user_data(user_id)
    session = user_data.get("target_session")
    if not session or not session.get("is_active"): return None, "Ended"

    # Update Balance
    level_idx = session["current_level_index"]
    # Safety check for index out of range
    if level_idx >= len(session["sequence"]):
        level_idx = len(session["sequence"]) - 1
        
    bet_amount = session["sequence"][level_idx]

    if outcome == 'win':
        session["current_balance"] += bet_amount
        session["current_level_index"] = 0
        # Recalculate sequence based on NEW balance (Compounding Logic)
        session["sequence"] = calculate_sequence(session["current_balance"])
    else:
        session["current_balance"] -= bet_amount
        if level_idx < len(session["sequence"]) - 1:
            session["current_level_index"] += 1
        else:
            # Reached end of sequence (Stop Loss or Reset)
            session["current_level_index"] = 0
            session["sequence"] = calculate_sequence(session["current_balance"])

    # End Conditions
    if session["current_balance"] >= session["target_amount"]:
        update_user_field(user_id, "target_session", None)
        return session, "TargetReached"
    if session["current_balance"] <= 50: # Effectively Bankrupt
        update_user_field(user_id, "target_session", None)
        return session, "Bankrupt"

    # Fetch NEW Period Logic
    game_type = session.get("game_type", "30s")
    next_period, _ = get_game_data(game_type)
    
    # If API doesn't update fast enough, force increment
    if not next_period or next_period == session["current_period"]:
        try:
            next_period = str(int(session["current_period"]) + 1)
        except:
            return session, "Ended"

    # Generate Next Prediction
    new_pred, _, _ = get_v5_logic(next_period, game_type)
    
    session["current_prediction"] = new_pred
    session["current_period"] = next_period
    
    update_user_field(user_id, "target_session", session)
    return session, "Continue"