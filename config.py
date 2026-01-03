import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) 

# --- Constants ---
REGISTER_LINK = "https://t.me/+pR0EE-BzatNjZjNl" 
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png"
SUPPORT_USERNAME = "YourSupportHandle" # Change this

# --- Plans (Added 1 Day Plan) ---
PREDICTION_PLANS = {
    "1_day": {"name": "1 Day Trial", "price": "100₹", "duration_seconds": 86400},
    "7_day": {"name": "7 Day VIP", "price": "300₹", "duration_seconds": 604800},
    "permanent": {"name": "Lifetime Access", "price": "500₹", "duration_seconds": 3153600000}, # 100 years
}

# --- Game Logic ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32, 64] 
MAX_LEVEL = len(BETTING_SEQUENCE)
PATTERN_LENGTH = 4

# --- Language & Text ---
TEXTS = {
    "en": {
        "welcome": "👋 **Welcome!**\nPlease select your language:",
        "trial_active": "✅ **Free Trial Active** (5 Mins)\nEnjoy V5+ Engine!",
        "trial_ended": "🚫 **Free Trial Ended.**\nPlease purchase a VIP Plan to continue.",
        "plan_active": "💎 **VIP Active:** ",
        "wait_result": "⏳ **Result not out yet!**\nPlease wait for the period to end.",
        "maintenance": "🛠 **System under maintenance.**\nPlease try again later.",
        "banned": "🚫 **You are BANNED from using this bot.**",
        "menu_main": "🏠 **Main Menu**",
        "btn_pred": "🚀 Start Prediction",
        "btn_shop": "🛒 VIP Store",
        "btn_profile": "👤 Profile",
        "btn_support": "📞 Support"
    },
    "hi": {
        "welcome": "👋 **स्वागत है!**\nकृपया अपनी भाषा चुनें:",
        "trial_active": "✅ **फ्री ट्रायल सक्रिय** (5 मिनट)\nV5+ इंजन का आनंद लें!",
        "trial_ended": "🚫 **फ्री ट्रायल समाप्त।**\nजारी रखने के लिए कृपया VIP प्लान खरीदें।",
        "plan_active": "💎 **VIP सक्रिय:** ",
        "wait_result": "⏳ **परिणाम अभी नहीं आया!**\nकृपया परिणाम का इंतजार करें।",
        "maintenance": "🛠 **सिस्टम रखरखाव में है।**\nकृपया बाद में प्रयास करें।",
        "banned": "🚫 **आपको इस बॉट का उपयोग करने से प्रतिबंधित कर दिया गया है।**",
        "menu_main": "🏠 **मुख्य मेनू**",
        "btn_pred": "🚀 भविष्यवाणी शुरू करें",
        "btn_shop": "🛒 VIP स्टोर",
        "btn_profile": "👤 प्रोफाइल",
        "btn_support": "📞 सहायता"
    }
}

# --- States ---
(LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, SHOP_MENU, 
 ADMIN_PANEL, WAITING_PROOF, WAITING_UTR) = range(7)
