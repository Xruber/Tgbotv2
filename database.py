import time
import random
import logging
from datetime import datetime
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

users_collection = None 
settings_collection = None

try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db
    users_collection = db.users
    settings_collection = db.settings
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
            "referral_purchases": 0,
            "total_wins": 0,   # Added for Stats
            "total_losses": 0  # Added for Stats
        }
        users_collection.insert_one(user)
    
    # Backfill missing keys for old users
    defaults = {
        "referred_by": None, "referral_purchases": 0, "prediction_mode": "V2",
        "total_wins": 0, "total_losses": 0, "target_access": None
    }
    for key, val in defaults.items():
        if key not in user: user[key] = val

    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
        
    return user

def get_top_referrers(limit=10):
    if users_collection is None: return []
    return list(users_collection.find().sort("referral_purchases", -1).limit(limit))

# --- NEW ADMIN LOGIC ---
def get_total_users():
    if users_collection is None: return 0
    return users_collection.count_documents({})

def get_active_subs_count():
    if users_collection is None: return 0
    # Count where status is ACTIVE and expiry is in the future
    return users_collection.count_documents({
        "prediction_status": "ACTIVE",
        "expiry_timestamp": {"$gt": time.time()}
    })

def get_all_user_ids():
    """Generator to fetch all user IDs efficiently."""
    if users_collection is None: return []
    return users_collection.find({}, {"user_id": 1})
# -----------------------

def check_and_reset_monthly_stats():
    if users_collection is None or settings_collection is None: 
        return False
    
    current_month_str = datetime.now().strftime("%Y-%m")
    config = settings_collection.find_one({"_id": "referral_config"})
    last_reset_str = config.get("last_reset") if config else None
    
    if last_reset_str != current_month_str:
        logger.info(f"🗓️ New Month Detected ({current_month_str}). Resetting referral stats...")
        users_collection.update_many({}, {"$set": {"referral_purchases": 0}})
        settings_collection.update_one(
            {"_id": "referral_config"},
            {"$set": {"last_reset": current_month_str}},
            upsert=True
        )
        return True
    return False

def is_subscription_active(user_data) -> bool:
    return user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time()

def get_remaining_time_str(user_data) -> str:
    expiry_timestamp = user_data.get("expiry_timestamp", 0)
    remaining = int(expiry_timestamp - time.time())
    if remaining > 1000000000: return "Permanent"
    if remaining <= 0: return "Expired"
    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    return f"{days}d {hours}h"