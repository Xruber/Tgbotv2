import time
import random
import string
import logging
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_pro_db
    users_col = db.users
    codes_col = db.codes
    settings_col = db.settings
    logger.info("✅ MongoDB Connected.")
except Exception as e:
    logger.error(f"❌ DB Error: {e}")

# --- User Management ---
def get_user_data(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "language": None,
            "joined_at": time.time(),
            "prediction_status": "NONE",
            "expiry_timestamp": 0,
            "is_banned": False,
            "current_level": 1,
            "total_wins": 0,
            "total_losses": 0,
            "balance": 0,
            "target_access": None
        }
        users_col.insert_one(user)
    return user

def update_user_field(user_id, field, value):
    users_col.update_one({"user_id": user_id}, {"$set": {field: value}})

def increment_user_field(user_id, field, amount=1):
    users_col.update_one({"user_id": user_id}, {"$inc": {field: amount}})

# --- Admin Systems ---
def is_user_banned(user_id):
    u = users_col.find_one({"user_id": user_id})
    return u.get("is_banned", False) if u else False

def ban_user(user_id, status: bool):
    users_col.update_one({"user_id": user_id}, {"$set": {"is_banned": status}})

def is_maintenance_mode():
    s = settings_col.find_one({"_id": "config"})
    return s.get("maintenance", False) if s else False

def set_maintenance_mode(status: bool):
    settings_col.update_one({"_id": "config"}, {"$set": {"maintenance": status}}, upsert=True)

# --- Gift Codes ---
def create_gift_code(plan_type):
    code = "GIFT-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    codes_col.insert_one({"code": code, "plan": plan_type, "redeemed": False})
    return code

def redeem_code(user_id, code):
    c = codes_col.find_one({"code": code, "redeemed": False})
    if not c: return False, "Invalid Code"
    
    # Unlock Plan
    from config import PREDICTION_PLANS
    plan = PREDICTION_PLANS.get(c['plan'])
    if not plan: return False, "Config Error"
    
    expiry = time.time() + plan['duration_seconds']
    users_col.update_one({"user_id": user_id}, {
        "$set": {"prediction_status": "ACTIVE", "expiry_timestamp": expiry}
    })
    codes_col.update_one({"_id": c['_id']}, {"$set": {"redeemed": True, "redeemed_by": user_id}})
    return True, plan['name']

def get_remaining_time_str(user_data) -> str:
    rem = int(user_data.get("expiry_timestamp", 0) - time.time())
    if rem <= 0: return "Expired"
    days = rem // 86400
    return f"{days} Days"
