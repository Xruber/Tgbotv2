from database import get_user_data, update_user_field
from config import TARGET_PACKS
from prediction_engine import get_v5_logic
from api_helper import get_game_data

def calculate_sequence(current_balance, goal_amount):
    """
    Splits the available capital (Current - Safety) into 6 Aggressive Steps
    to try and reach the goal faster.
    """
    # Logic: We have 6 bullets. 
    # We use a custom compounding ratio to recover + profit.
    # Level 1: 1%
    # Level 2: 2%
    # Level 3: 5%
    # Level 4: 12%
    # Level 5: 30%
    # Level 6: 50% (All in effort)
    
    # Safe Balance to use (leave 100rs buffer if possible)
    use_bal = max(current_balance - 50, 0) 
    
    seq = [
        int(use_bal * 0.01),
        int(use_bal * 0.02),
        int(use_bal * 0.05),
        int(use_bal * 0.12),
        int(use_bal * 0.30),
        int(use_bal * 0.49)
    ]
    # Filter out 0 bets
    seq = [s if s > 10 else 10 for s in seq]
    return seq

def start_target_session(user_id, target_key, game_type="30s"):
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    period, history = get_game_data(game_type)
    if not period: return None

    # Initial Prediction
    pred, _, _ = get_v5_logic(period, game_type, history)

    start = pack['start']
    target = pack['target']
    
    session = {
        "start_balance": start,
        "current_balance": start,
        "target_amount": target,
        "current_period": period,
        "current_prediction": pred,
        "sequence": calculate_sequence(start, target),
        "current_level_index": 0,
        "game_type": game_type,
        "is_active": True,
        "pack_key": target_key
    }
    
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    user_data = get_user_data(user_id)
    sess = user_data.get("target_session")
    if not sess: return None, "Ended"

    # Get Bet Amount
    try:
        bet_amt = sess["sequence"][sess["current_level_index"]]
    except:
        bet_amt = sess["sequence"][-1]

    # Process Win/Loss
    if outcome == "win":
        sess["current_balance"] += bet_amt
        # Reset to Level 1 on Win
        sess["current_level_index"] = 0
        # RECALCULATE Sequence based on NEW Balance to optimize growth
        sess["sequence"] = calculate_sequence(sess["current_balance"], sess["target_amount"])
    else:
        sess["current_balance"] -= bet_amt
        # Move to Next Level
        if sess["current_level_index"] < 5:
            sess["current_level_index"] += 1
        else:
            # Level 6 Lost -> Reset to 0 (Martingale Reset)
            sess["current_level_index"] = 0
            sess["sequence"] = calculate_sequence(sess["current_balance"], sess["target_amount"])

    # Check End Conditions
    if sess["current_balance"] >= sess["target_amount"]:
        update_user_field(user_id, "target_session", None)
        return sess, "TargetReached"
        
    if sess["current_balance"] < 50:
        update_user_field(user_id, "target_session", None)
        return sess, "Bankrupt"

    # Next Prediction
    next_p, hist = get_game_data(sess["game_type"])
    if next_p == sess["current_period"]:
        try: next_p = str(int(next_p) + 1)
        except: pass
        
    pred, _, _ = get_v5_logic(next_p, sess["game_type"], hist)
    sess["current_prediction"] = pred
    sess["current_period"] = next_p
    
    update_user_field(user_id, "target_session", sess)
    return sess, "Continue"
