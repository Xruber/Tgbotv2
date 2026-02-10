import time
import random
import logging
import uuid
from datetime import datetime
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

users_collection = None 
settings_collection = None
codes_collection = None
tokens_collection = None       # NEW
transactions_collection = None # NEW

try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db
    users_collection = db.users
    settings_collection = db.settings
    codes_collection = db.codes
    tokens_collection = db.tokens             # NEW
    transactions_collection = db.transactions # NEW
    logger.info("✅ Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")

# --- HELPER FUNCTIONS (EXISTING) ---

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
            "total_losses": 0,
            "wallet": {"balance": 0.0, "holdings": {}, "invested_amt": {}} # Ensure wallet exists
        }
        users_collection.insert_one(user)
    
    # Backfill defaults
    defaults = { "language": "EN", "is_banned": False, "prediction_mode": "V5" }
    for key, val in defaults.items():
        if key not in user: user[key] = val
        
    if "wallet" not in user:
        user["wallet"] = {"balance": 0.0, "holdings": {}, "invested_amt": {}}
        update_user_field(user_id, "wallet", user["wallet"])

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
    
    expiry = time.time() + c['duration']
    update_user_field(user_id, "prediction_status", "ACTIVE")
    update_user_field(user_id, "expiry_timestamp", int(expiry))
    codes_collection.update_one({"_id": c["_id"]}, {"$set": {"is_redeemed": True, "redeemed_by": user_id}})
    return True, c['plan_type']

# --- STATS FUNCTIONS ---
def get_total_users():
    if users_collection is not None: return users_collection.count_documents({})
    return 0

def get_active_subs_count():
    if users_collection is not None:
        return users_collection.count_documents({"prediction_status": "ACTIVE", "expiry_timestamp": {"$gt": time.time()}})
    return 0

def get_all_user_ids():
    if users_collection is not None: return users_collection.find({}, {"user_id": 1})
    return []

def get_top_referrers(limit=10):
    if users_collection is not None: return list(users_collection.find().sort("referral_purchases", -1).limit(limit))
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

# ==========================================
# NEW: TOKEN & CHART SYSTEM
# ==========================================

INITIAL_TOKENS = [
    {"symbol": "TET", "name": "Texhet", "price": 10.0, "history": [10.0]},
    {"symbol": "GLL", "name": "Gallium", "price": 5.5, "history": [5.5]},
    {"symbol": "GGC", "name": "GigaCoin", "price": 100.0, "history": [100.0]},
    {"symbol": "LKY", "name": "LOWKEY", "price": 0.5, "history": [0.5]},
    {"symbol": "TSK", "name": "Tasket", "price": 12.0, "history": [12.0]},
    {"symbol": "MKY", "name": "Milkyy", "price": 25.0, "history": [25.0]},
    {"symbol": "HOA", "name": "Hainoka", "price": 8.0, "history": [8.0]},
    {"symbol": "ZDR", "name": "Zendora", "price": 1.2, "history": [1.2]},
    {"symbol": "FLX", "name": "Flux", "price": 45.0, "history": [45.0]},
    {"symbol": "VRT", "name": "Vortex", "price": 150.0, "history": [150.0]},
    {"symbol": "CRM", "name": "Crimson", "price": 7.0, "history": [7.0]},
    {"symbol": "AER", "name": "Aether", "price": 90.0, "history": [90.0]},
    {"symbol": "PLS", "name": "Pulse", "price": 3.3, "history": [3.3]},
    {"symbol": "ION", "name": "Ion", "price": 18.0, "history": [18.0]},
    {"symbol": "NVX", "name": "NovaX", "price": 60.0, "history": [60.0]}
]

def init_tokens():
    if tokens_collection is not None and tokens_collection.count_documents({}) == 0:
        tokens_collection.insert_many(INITIAL_TOKENS)

def get_all_tokens():
    """Returns tokens and simulates live market movement for charts."""
    if tokens_collection is None: return []
    tokens = list(tokens_collection.find({}, {"_id": 0}))
    
    # Simulate Market Fluctuation
    for t in tokens:
        if random.random() > 0.6: # 40% chance to move
            change = random.uniform(0.95, 1.05)
            new_price = round(t['price'] * change, 2)
            
            # Update Price & History
            tokens_collection.update_one(
                {"symbol": t['symbol']}, 
                {
                    "$set": {"price": new_price},
                    "$push": {
                        "history": {
                            "$each": [new_price],
                            "$slice": -20 # Keep last 20 points
                        }
                    }
                }
            )
            t['price'] = new_price # Update local var
            
    return tokens

def get_token_details(symbol):
    """Fetches single token with history."""
    if tokens_collection is None: return None
    return tokens_collection.find_one({"symbol": symbol})

def update_token_price(symbol, new_price):
    if tokens_collection is not None:
        tokens_collection.update_one({"symbol": symbol}, {"$set": {"price": float(new_price)}, "$push": {"history": float(new_price)}})

# ==========================================
# NEW: WALLET FUNCTIONS
# ==========================================

def get_user_wallet(user_id):
    u = get_user_data(user_id)
    return u.get("wallet", {"balance": 0.0, "holdings": {}, "invested_amt": {}})

def update_wallet_balance(user_id, amount):
    if users_collection is not None:
        users_collection.update_one({"user_id": user_id}, {"$inc": {"wallet.balance": float(amount)}})

def update_token_holding(user_id, symbol, quantity, cost=0):
    if users_collection is not None:
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {f"wallet.holdings.{symbol}": quantity, f"wallet.invested_amt.{symbol}": cost}}
        )

def trade_token(user_id, symbol, quantity, price, is_buy=True):
    if users_collection is None: return
    cost = float(quantity * price)
    
    if is_buy:
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"wallet.balance": -cost, f"wallet.holdings.{symbol}": quantity, f"wallet.invested_amt.{symbol}": cost}}
        )
    else:
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"wallet.balance": cost, f"wallet.holdings.{symbol}": -quantity}}
        )

# ==========================================
# NEW: TRANSACTION HISTORY
# ==========================================

def create_transaction(user_id, tx_type, amount, method, details):
    if transactions_collection is None: return "ERROR"
    tx_id = str(uuid.uuid4())[:8]
    tx_data = {"tx_id": tx_id, "user_id": user_id, "type": tx_type, "amount": float(amount), "method": method, "details": details, "status": "pending", "timestamp": time.time()}
    transactions_collection.insert_one(tx_data)
    return tx_id

def get_user_transactions(user_id, limit=5):
    if transactions_collection is None: return []
    return list(transactions_collection.find({"user_id": user_id}).sort("timestamp", -1).limit(limit))

def get_transaction(tx_id):
    return transactions_collection.find_one({"tx_id": tx_id})

def update_transaction_status(tx_id, status):
    transactions_collection.update_one({"tx_id": tx_id}, {"$set": {"status": status}})

init_tokens()