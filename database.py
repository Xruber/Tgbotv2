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
codes_collection = None

try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db
    users_collection = db.users
    settings_collection = db.settings
    codes_collection = db.codes
    logger.info("✅ Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")

# --- HELPER FUNCTIONS ---

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
            "language": "EN",
            "is_banned": False,
            "prediction_status": "NONE", 
            "prediction_plan": None,
            "expiry_timestamp": 0,
            "current_level": 1, 
            "current_prediction": random.choice(['Small', 'Big']),
            "history": [], 
            "current_pattern_name": "Random (New User)", 
            "prediction_mode": "V5", 
            "has_number_shot": False,
            "target_access": None,
            "target_session": None,
            "sureshot_session": None,
            "referred_by": None,
            "referral_purchases": 0,
            "total_wins": 0,
            "total_losses": 0
        }
        users_collection.insert_one(user)
    
    # Backfill defaults
    defaults = {
        "language": "EN", "is_banned": False, "prediction_mode": "V5"
    }
    for key, val in defaults.items():
        if key not in user: user[key] = val

    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
        
    return user

# --- GLOBAL SETTINGS ---
def get_settings():
    if settings_collection is None: return {"maintenance_mode": False}
    s = settings_collection.find_one({"_id": "global_settings"})
    if not s:
        s = {"_id": "global_settings", "maintenance_mode": False}
        settings_collection.insert_one(s)
    return s

def set_maintenance_mode(status: bool):
    if settings_collection is not None:
        settings_collection.update_one({"_id": "global_settings"}, {"$set": {"maintenance_mode": status}}, upsert=True)

# --- GIFT CODES ---
def create_gift_code(plan_type, duration):
    if codes_collection is None: return "ERROR-DB"
    import uuid
    code = f"GIFT-{uuid.uuid4().hex[:8].upper()}"
    codes_collection.insert_one({
        "code": code,
        "plan_type": plan_type,
        "duration": duration,
        "is_redeemed": False
    })
    return code

def redeem_gift_code(code, user_id):
    if codes_collection is None: return False, "DB Error"
    
    c = codes_collection.find_one({"code": code, "is_redeemed": False})
    if not c: return False, "Invalid or Redeemed Code"
    
    # Apply
    expiry = time.time() + c['duration']
    update_user_field(user_id, "prediction_status", "ACTIVE")
    update_user_field(user_id, "expiry_timestamp", int(expiry))
    
    codes_collection.update_one({"_id": c["_id"]}, {"$set": {"is_redeemed": True, "redeemed_by": user_id}})
    return True, c['plan_type']

# --- STATS FUNCTIONS (FIXED) ---

def get_total_users():
    # FIXED: Check explicitly against None
    if users_collection is not None:
        return users_collection.count_documents({})
    return 0

def get_active_subs_count():
    # FIXED: Check explicitly against None
    if users_collection is not None:
        return users_collection.count_documents({
            "prediction_status": "ACTIVE",
            "expiry_timestamp": {"$gt": time.time()}
        })
    return 0

def get_all_user_ids():
    # FIXED: Check explicitly against None
    if users_collection is not None:
        return users_collection.find({}, {"user_id": 1})
    return []

def get_top_referrers(limit=10):
    # FIXED: Check explicitly against None
    if users_collection is not None:
        return list(users_collection.find().sort("referral_purchases", -1).limit(limit))
    return []

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
