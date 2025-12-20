import time
import random
import logging
from pymongo import MongoClient
from config import MONGO_URI, PREDICTION_PLANS

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Connection
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
            "prediction_mode": "V2"  # Default to V2
        }
        users_collection.insert_one(user)
    
    # Defaults for existing users
    if "prediction_mode" not in user: user["prediction_mode"] = "V2"
    if "current_level" not in user: user["current_level"] = 1
    if "history" not in user: user["history"] = []

    # Check Expiry
    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
        
    return user

def is_subscription_active(user_data) -> bool:
    if user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time():
        return True
    return False

def get_remaining_time_str(expiry_timestamp: int) -> str:
    remaining_seconds = int(expiry_timestamp - time.time())
    if remaining_seconds > 1000000000: return "Permanent"
    if remaining_seconds <= 0: return "Expired"
    days = remaining_seconds // 86400
    hours = (remaining_seconds % 86400) // 3600
    return f"{days}d {hours}h" if days > 0 else f"{hours}h {(remaining_seconds % 3600) // 60}m"