import time
import random
import logging
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

users_collection = None 
try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db
    users_collection = db.users
    logger.info("✅ Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")

def update_user_field(user_id, field, value):
    if users_collection is not None:
        users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

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
            # New Fields
            "has_number_shot": False,      # Boolean for Number Pack
            "target_access": None,         # Stores 'target_2k' etc. if bought
            "target_session": None         # Stores active /target game state
        }
        users_collection.insert_one(user)
    
    # Defaults for existing users (Migration)
    if "has_number_shot" not in user: user["has_number_shot"] = False
    if "target_access" not in user: user["target_access"] = None
    if "target_session" not in user: user["target_session"] = None
    if "prediction_mode" not in user: user["prediction_mode"] = "V2"

    # Check Subscription Expiry
    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
        
    return user

def is_subscription_active(user_data) -> bool:
    return user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time()

def get_remaining_time_str(expiry_timestamp: int) -> str:
    remaining = int(expiry_timestamp - time.time())
    if remaining > 1000000000: return "Permanent"
    if remaining <= 0: return "Expired"
    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    return f"{days}d {hours}h"