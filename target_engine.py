from database import get_user_data, update_user_field
from config import TARGET_PACKS
from prediction_engine import get_v5_logic
from api_helper import get_game_data

def calculate_sequence(balance):
    """Generates a safe compounding sequence based on balance."""
    safe_bal = max(balance, 100)
    # 6-Step Strategy (Conservative Start -> Aggressive Recovery)
    seq = [
        int(safe_bal * 0.01), # 1%
        int(safe_bal * 0.02), # 2%
        int(safe_bal * 0.05), # 5%
        int(safe_bal * 0.12), # 12%
        int(safe_bal * 0.30), # 30%
        int(safe_bal * 0.50)  # 50%
    ]
    return seq

def start_target_session(user_id, target_key, game_type="30s"):
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    period, history = get_game_data(game_type)
    if not period: return None

    # Initial Prediction
    pred, _, _ = get_v5_logic(period, game_type, history)

    session = {
        "start_balance": pack['start'],
        "current_balance": pack['start'],
        "target_amount": pack['target'],
        "current_period": period,
        "current_prediction": pred,
        "sequence": calculate_sequence(pack['start']),
        "current_level_index": 0,
        "game_type": game_type,
        "is_active": True
    }
    
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    user_data = get_user_data(user_id)
    sess = user_data.get("target_session")
    if not sess: return None, "Ended"

    # 1. Update Balance
    try:
        bet_amt = sess["sequence"][sess["current_level_index"]]
    except IndexError:
        bet_amt = sess["sequence"][-1]

    if outcome == "win":
        sess["current_balance"] += bet_amt
        sess["current_level_index"] = 0
        sess["sequence"] = calculate_sequence(sess["current_balance"]) # Recalculate based on new wins
    else:
        sess["current_balance"] -= bet_amt
        # Move to next step in sequence
        if sess["current_level_index"] < len(sess["sequence"]) - 1:
            sess["current_level_index"] += 1
        else:
            sess["current_level_index"] = 0 # Reset if sequence finished
            sess["sequence"] = calculate_sequence(sess["current_balance"])

    # 2. Check Goals
    status = "Continue"
    if sess["current_balance"] >= sess["target_amount"]:
        status = "TargetReached"
        update_user_field(user_id, "target_session", None)
    elif sess["current_balance"] < 50:
        status = "Bankrupt"
        update_user_field(user_id, "target_session", None)
    else:
        # 3. Next Prediction
        next_p, hist = get_game_data(sess["game_type"])
        # Handle API lag (Force next period if same)
        if next_p == sess["current_period"]:
            try: next_p = str(int(next_p) + 1)
            except: pass
            
        pred, _, _ = get_v5_logic(next_p, sess["game_type"], hist)
        sess["current_prediction"] = pred
        sess["current_period"] = next_p
        update_user_field(user_id, "target_session", sess)

    return sess, status
