import time
import random
import logging
from datetime import datetime # NEW IMPORT
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

users_collection = None 
settings_collection = None # NEW

try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db
    users_collection = db.users
    settings_collection = db.settings # NEW: Stores global configs
    logger.info("✅ Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")

def update_user_field(user_id, field, value):
    if users_collection is not None:
        users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def increment_user_field(user_id, field, amount=1):
    if users_collection is not None:
        users_collection.update_one({"user_id": user_id}, {"$inc": {field: amount}})

def get_user_data(user_id):
    if users_collection is None: return {}
    
    user = users_collection.find_one({"user_id": user_id})
    if user is None:
        user = {
            "user_id": user_id,
            "username": None,
            "prediction_status": "NONE", 
            "prediction_plan": None,
            "expiry_timestamp": 0,
            "current_level": 1, 
            "current_prediction": random.choice(['Small', 'Big']),
            "history": [], 
            "current_pattern_name": "Random (New User)", 
            "prediction_mode": "V2",
            "has_number_shot": False,
            "target_access": None,
            "target_session": None,
            "referred_by": None,
            "referral_purchases": 0
        }
        users_collection.insert_one(user)
    
    if "referred_by" not in user: user["referred_by"] = None
    if "referral_purchases" not in user: user["referral_purchases"] = 0
    if "prediction_mode" not in user: user["prediction_mode"] = "V2"

    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
        
    return user

def get_top_referrers(limit=10):
    if users_collection is None: return []
    return list(users_collection.find().sort("referral_purchases", -1).limit(limit))

# --- NEW: MONTHLY RESET LOGIC ---
def check_and_reset_monthly_stats():
    """
    Checks if the current month string (YYYY-MM) matches the stored one.
    If different, resets all referral stats to 0.
    Returns: True if reset occurred, False otherwise.
    """
    if users_collection is None or settings_collection is None: 
        return False
    
    # Get current month tag, e.g., "2023-12"
    current_month_str = datetime.now().strftime("%Y-%m")
    
    # Get last stored reset tag
    config = settings_collection.find_one({"_id": "referral_config"})
    last_reset_str = config.get("last_reset") if config else None
    
    # Compare
    if last_reset_str != current_month_str:
        logger.info(f"🗓️ New Month Detected ({current_month_str}). Resetting referral stats...")
        
        # 1. Reset everyone's count to 0
        users_collection.update_many({}, {"$set": {"referral_purchases": 0}})
        
        # 2. Update the config so we don't reset again this month
        settings_collection.update_one(
            {"_id": "referral_config"},
            {"$set": {"last_reset": current_month_str}},
            upsert=True
        )
        return True
        
    return False

def is_subscription_active(user_data) -> bool:
    return user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time()

def get_remaining_time_str(expiry_timestamp: int) -> str:
    remaining = int(expiry_timestamp - time.time())
    if remaining > 1000000000: return "Permanent"
    if remaining <= 0: return "Expired"
    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    return f"{days}d {hours}h"