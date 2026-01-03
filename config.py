import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) 

# --- Constants ---
SUPPORT_USERNAME = "YourSupport" 
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png"

# --- Plans ---
PREDICTION_PLANS = {
    "1_day": {"name": "1 Day Trial", "price": "100₹", "duration_seconds": 86400},
    "7_day": {"name": "7 Day VIP", "price": "300₹", "duration_seconds": 604800},
    "permanent": {"name": "Lifetime Access", "price": "500₹", "duration_seconds": 3153600000},
}

# --- Target & Special Packs ---
NUMBER_SHOT_PRICE = "100₹"
NUMBER_SHOT_KEY = "number_shot"

TARGET_PACKS = {
    "target_2k": {"name": "Target: 1K ➔ 2K", "price": "200₹", "target": 2000, "start": 1000},
    "target_5k": {"name": "Target: 1K ➔ 5K", "price": "500₹", "target": 5000, "start": 1000},
}

# --- Game Logic ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32, 64] 
MAX_LEVEL = len(BETTING_SEQUENCE)

# --- States ---
(LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, SHOP_MENU, 
 WAITING_UTR, REDEEM_PROCESS, TARGET_MENU, TARGET_LOOP) = range(8)

# --- Texts ---
TEXTS = {
    "en": {
        "welcome": "👋 **Welcome!**\nSelect Language:",
        "main_menu": "🏠 **DASHBOARD**",
        "banned": "🚫 **ACCESS DENIED**\nYou have been banned.",
        "maintenance": "🛠 **MAINTENANCE**\nBot is currently updating.",
        "trial_ended": "🔒 **Trial Expired**",
        "plan_active": "💎 **VIP Active**",
        "btn_pred": "🚀 Start Prediction",
        "btn_target": "🎯 Target Session",
        "btn_shop": "🛒 Store",
        "btn_profile": "👤 My Stats",
        "btn_redeem": "🎁 Redeem",
        "wait_result": "⏳ Wait for result..."
    },
    "hi": {
        "welcome": "👋 **स्वागत है!**\nभाषा चुनें:",
        "main_menu": "🏠 **डैशबोर्ड**",
        "banned": "🚫 **प्रतिबंधित**\nआपको बैन कर दिया गया है।",
        "maintenance": "🛠 **रखरखाव**\nबॉट अपडेट हो रहा है।",
        "trial_ended": "🔒 **ट्रायल समाप्त**",
        "plan_active": "💎 **VIP सक्रिय**",
        "btn_pred": "🚀 भविष्यवाणी",
        "btn_target": "🎯 टारगेट सेशन",
        "btn_shop": "🛒 स्टोर",
        "btn_profile": "👤 प्रोफाइल",
        "btn_redeem": "🎁 रिडीम",
        "wait_result": "⏳ परिणाम का इंतजार करें..."
    }
}
