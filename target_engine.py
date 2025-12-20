import random
from database import get_user_data, update_user_field
from config import TARGET_SEQUENCE, TARGET_PACKS
from prediction_engine import generate_v1_prediction

def start_target_session(user_id, target_key):
    """Initializes the session for the target game."""
    pack = TARGET_PACKS.get(target_key)
    if not pack: return None

    # Calculate first prediction using V1 Logic
    user_data = get_user_data(user_id)
    history = user_data.get("history", [])
    initial_pred = random.choice(['Small', 'Big'])
    
    # If there is history, try to use V1 logic for the first prediction
    if history:
         pred, pattern = generate_v1_prediction(history, initial_pred, 'win') # Mock 'win' to trigger pattern check
         initial_pred = pred

    session = {
        "target_amount": pack['target'],
        "current_balance": pack['start'],
        "current_level_index": 0, # Index in TARGET_SEQUENCE [0 to 4]
        "current_prediction": initial_pred,
        "is_active": True,
        "pack_name": pack['name']
    }
    update_user_field(user_id, "target_session", session)
    return session

def process_target_outcome(user_id, outcome):
    """
    Handles Win/Loss for Target Mode.
    Logic:
    - Win: Balance += Bet. Reset to Level 0.
    - Loss: Balance -= Bet. Increase Level.
    - V1 Engine provides next prediction.
    """
    user_data = get_user_data(user_id)
    session = user_data.get("target_session")
    if not session or not session.get("is_active"): return None, "Ended"

    # Get current bet amount
    level_idx = session["current_level_index"]
    bet_amount = TARGET_SEQUENCE[level_idx]
    current_pred = session["current_prediction"]

    # 1. Update Balance
    if outcome == 'win':
        session["current_balance"] += bet_amount
        session["current_level_index"] = 0 # Reset on win
    else:
        session["current_balance"] -= bet_amount
        # Increase level, cap at max level (index 4)
        if level_idx < len(TARGET_SEQUENCE) - 1:
            session["current_level_index"] += 1
        else:
            # If max level lost, user essentially failed this run, but we keep them at max or reset?
            # Standard logic usually keeps at max or resets. Let's keep at max for recovery.
            session["current_level_index"] = len(TARGET_SEQUENCE) - 1

    # 2. Check Target Reached
    if session["current_balance"] >= session["target_amount"]:
        update_user_field(user_id, "target_session", None)
        update_user_field(user_id, "target_access", None) # One-time use consumed
        return session, "TargetReached"
    
    # 3. Check Bankruptcy (Optional safety)
    if session["current_balance"] <= 0:
        update_user_field(user_id, "target_session", None)
        update_user_field(user_id, "target_access", None) 
        return session, "Bankrupt"

    # 4. Generate Next Prediction (V1 Logic)
    # We need to simulate the history update for V1 to work accurately
    history = user_data.get("history", [])
    actual_outcome = current_pred if outcome == 'win' else ('Big' if current_pred == 'Small' else 'Small')
    history.append(actual_outcome)
    if len(history) > 5: history.pop(0)
    update_user_field(user_id, "history", history)

    new_pred, _ = generate_v1_prediction(history, current_pred, outcome)
    session["current_prediction"] = new_pred
    
    update_user_field(user_id, "target_session", session)
    return session, "Continue"