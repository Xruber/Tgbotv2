import random
from database import get_user_data, update_user_field
from config import TARGET_PACKS
from prediction_engine import get_v5_logic
from api_helper import get_game_data

def calculate_sequence(balance):
    safe_balance = max(balance, 50)
    seq = [
        int(safe_balance * 0.01),
        int(safe_balance * 0.02),
        int(safe_balance * 0.05),
        int(safe_balance * 0.10),
        int(safe_balance * 0.25),
        int(safe_balance * 0.57)
    ]
    if sum(seq) > balance: seq[-1] = balance - sum(seq[:-1])
    return seq

def start_target_session(user_id, target_key, game_type):
    """
    Starts session using API for period number.
    game_type: '30s' or '1m'
    """
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    # 1. Fetch Live Period
    current_period, _ = get_game_data(game_type)
    if not current_period: return None # API Error

    # 2. Generate First Prediction using V5
    initial_pred, _, _ = get_v5_logic(current_period)

    start_bal = pack['start']
    
    session = {
        "target_amount": pack['target'],
        "current_balance": start_bal,
        "current_level_index": 0,
        "current_prediction": initial_pred,
        "is_active": True,
        "pack_name": pack['name'],
        "sequence": calculate_sequence(start_bal),
        "current_period": current_period,
        "game_type": game_type # Remember choice
    }
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    user_data = get_user_data(user_id)
    session = user_data.get("target_session")
    if not session or not session.get("is_active"): return None, "Ended"

    # 1. Update Balance
    level_idx = session["current_level_index"]
    bet_amount = session["sequence"][level_idx]

    if outcome == 'win':
        session["current_balance"] += bet_amount
        session["current_level_index"] = 0
        session["sequence"] = calculate_sequence(session["current_balance"])
    else:
        session["current_balance"] -= bet_amount
        if level_idx < len(session["sequence"]) - 1:
            session["current_level_index"] += 1
        else:
            session["current_level_index"] = len(session["sequence"]) - 1

    # 2. Check End Conditions
    if session["current_balance"] >= session["target_amount"]:
        update_user_field(user_id, "target_session", None)
        return session, "TargetReached"
    if session["current_balance"] <= 0:
        update_user_field(user_id, "target_session", None)
        return session, "Bankrupt"

    # 3. Fetch NEW Period from API
    game_type = session.get("game_type", "30s")
    next_period, _ = get_game_data(game_type)
    
    # If API fails or returns same period, increment manually (Fallback)
    if not next_period or next_period == session["current_period"]:
        next_period = str(int(session["current_period"]) + 1)

    # 4. Generate Next V5 Prediction
    new_pred, _, _ = get_v5_logic(next_period)
    
    session["current_prediction"] = new_pred
    session["current_period"] = next_period
    
    update_user_field(user_id, "target_session", session)
    return session, "Continue"