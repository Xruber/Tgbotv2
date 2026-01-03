import time
import random
import logging
import string
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_v5_rebuild
    users_collection = db.users
    codes_collection = db.codes
    settings_collection = db.settings
    logger.info("✅ MongoDB Connected.")
except Exception as e:
    logger.error(f"❌ MongoDB Error: {e}")

# --- User Management ---
def get_user_data(user_id):
    if users_collection is None: return {}
    user = users_collection.find_one({"user_id": user_id})
    
    if not user:
        user = {
            "user_id": user_id,
            "language": None, # 'en' or 'hi'
            "joined_at": time.time(),
            "trial_used": False, # Track 5 min trial
            "prediction_status": "NONE",
            "expiry_timestamp": 0,
            "balance": 0,
            "is_banned": False,
            "current_level": 1,
            "total_wins": 0,
            "total_losses": 0,
            "history": []
        }
        users_collection.insert_one(user)
    return user

def update_user_field(user_id, field, value):
    users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def increment_user_field(user_id, field, amount=1):
    users_collection.update_one({"user_id": user_id}, {"$inc": {field: amount}})

# --- Logic Checks ---
def is_user_banned(user_id):
    u = get_user_data(user_id)
    return u.get("is_banned", False)

def is_maintenance_mode():
    s = settings_collection.find_one({"_id": "config"})
    return s.get("maintenance", False) if s else False

def set_maintenance_mode(status: bool):
    settings_collection.update_one({"_id": "config"}, {"$set": {"maintenance": status}}, upsert=True)

def ban_user(user_id, status: bool):
    update_user_field(user_id, "is_banned", status)

# --- Gift Codes ---
def create_gift_code(plan_type):
    code = "GIFT-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    codes_collection.insert_one({"code": code, "plan": plan_type, "redeemed": False})
    return code

def redeem_code(user_id, code):
    c = codes_collection.find_one({"code": code, "redeemed": False})
    if not c: return False, "Invalid or Used Code"
    
    # Apply Plan
    from config import PREDICTION_PLANS
    plan = PREDICTION_PLANS.get(c['plan'])
    if not plan: return False, "Plan Config Error"
    
    expiry = time.time() + plan['duration_seconds']
    users_collection.update_one({"user_id": user_id}, {
        "$set": {"prediction_status": "ACTIVE", "expiry_timestamp": expiry}
    })
    codes_collection.update_one({"_id": c['_id']}, {"$set": {"redeemed": True, "redeemed_by": user_id}})
    return True, plan['name']

# --- Helpers ---
def get_total_users(): return users_collection.count_documents({})
def get_active_subs(): return users_collection.count_documents({"prediction_status": "ACTIVE"})
