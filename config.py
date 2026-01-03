import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) 

# --- Constants ---
SUPPORT_USERNAME = "YourSupport" # Change this
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png"

# --- Plans ---
PREDICTION_PLANS = {
    "1_day": {"name": "1 Day Trial", "price": "100₹", "duration_seconds": 86400},
    "7_day": {"name": "7 Day VIP", "price": "300₹", "duration_seconds": 604800},
    "permanent": {"name": "Lifetime Access", "price": "500₹", "duration_seconds": 3153600000},
}

TARGET_PACKS = {
    "target_2k": {"name": "1K to 2K", "price": "200₹", "target": 2000, "start": 1000},
    "target_5k": {"name": "1K to 5K", "price": "500₹", "target": 5000, "start": 1000},
}

# --- Game Logic ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32, 64] 
MAX_LEVEL = len(BETTING_SEQUENCE)

# --- Multi-Language Texts ---
TEXTS = {
    "en": {
        "welcome": "👋 **Welcome!**\nPlease select your language:",
        "main_menu": "🏠 **Main Menu**\nSelect an option below:",
        "trial_active": "✅ **Free Trial Active** (5 Mins)\nEnjoy V5+ Engine!",
        "trial_ended": "🚫 **Free Trial Ended.**\nPlease purchase a VIP Plan.",
        "plan_active": "💎 **VIP Active:** ",
        "maintenance": "🛠 **System under maintenance.**\nCome back later.",
        "banned": "🚫 **You are BANNED.**\nContact support.",
        "btn_pred": "🚀 Start Prediction",
        "btn_shop": "🛒 VIP Store",
        "btn_profile": "👤 Profile",
        "btn_support": "📞 Support",
        "btn_redeem": "🎁 Redeem Code",
        "wait_result": "⏳ **Wait for Result!**\nDo not click until the period changes."
    },
    "hi": {
        "welcome": "👋 **स्वागत है!**\nकृपया अपनी भाषा चुनें:",
        "main_menu": "🏠 **मुख्य मेनू**\nनीचे एक विकल्प चुनें:",
        "trial_active": "✅ **फ्री ट्रायल सक्रिय** (5 मिनट)\nV5+ इंजन का आनंद लें!",
        "trial_ended": "🚫 **फ्री ट्रायल समाप्त।**\nकृपया VIP प्लान खरीदें।",
        "plan_active": "💎 **VIP सक्रिय:** ",
        "maintenance": "🛠 **सिस्टम रखरखाव में है।**\nकृपया बाद में आएं।",
        "banned": "🚫 **आपको प्रतिबंधित कर दिया गया है।**\nसहायता से संपर्क करें।",
        "btn_pred": "🚀 भविष्यवाणी शुरू करें",
        "btn_shop": "🛒 VIP स्टोर",
        "btn_profile": "👤 प्रोफाइल",
        "btn_support": "📞 सहायता",
        "btn_redeem": "🎁 कोड रिडीम करें",
        "wait_result": "⏳ **परिणाम का इंतजार करें!**\nअगले पीरियड तक क्लिक न करें।"
    }
}

# --- States ---
(LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, SHOP_MENU, 
 WAITING_UTR, REDEEM_PROCESS, TARGET_MENU, TARGET_LOOP) = range(8)
