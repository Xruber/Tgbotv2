import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) 

# --- Constants ---
REGISTER_LINK = "https://t.me/+pR0EE-BzatNjZjNl" 
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/888361275464220733/1451949298928455831/Screenshot_20251029-1135273.png"
PREDICTION_PROMPT = "➡️ **Please wait for the next period...**"

# --- Localization (FULL CONTENT RESTORED) ---
LANGUAGES = {
    "EN": {
        "welcome": "👋 Hello, **{name}**!",
        "select_lang": "🌍 **Select Language / भाषा चुनें:**",
        "maintenance": "🚧 **System under maintenance.** Please wait.",
        "banned": "🚫 **You are banned from using this bot.**",
        "result_wait": "⏳ **Result not yet released.**\nPlease wait 10-20 seconds.",
        "win_msg": "💰 **WIN CONFIRMED!**\nResult: {result}",
        "loss_msg": "📉 **LOSS CONFIRMED.**\nResult: {result}",
        "wait_next": "➡️ **Please wait for the next period...**"
    },
    "HI": {
        "welcome": "👋 नमस्ते, **{name}**!",
        "select_lang": "🌍 **भाषा चुनें:**",
        "maintenance": "🚧 **सिस्टम रखरखाव (Maintenance) के तहत है।**",
        "banned": "🚫 **आपको प्रतिबंधित कर दिया गया है।**",
        "result_wait": "⏳ **परिणाम अभी नहीं आया है।**\nकृपया 10-20 सेकंड प्रतीक्षा करें।",
        "win_msg": "💰 **जीत पक्की! (WIN)**\nपरिणाम: {result}",
        "loss_msg": "📉 **हार (LOSS).**\nपरिणाम: {result}",
        "wait_next": "➡️ **अगले पीरियड का इंतज़ार करें...**"
    }
}

# --- Subscription Plans ---
PREDICTION_PLANS = {
    "1_day": {"name": "1 Day Access", "price": "100₹", "duration_seconds": 86400},
    "7_day": {"name": "7 Day Access", "price": "300₹", "duration_seconds": 604800},
    "permanent": {"name": "Permanent Access", "price": "500₹", "duration_seconds": 1576800000},
}

# --- Packs & Target ---
NUMBER_SHOT_PRICE = "100₹"
NUMBER_SHOT_KEY = "number_shot_pack"

TARGET_PACKS = {
    "target_2k": {"name": "1K - 2K Target", "price": "200₹", "target": 2000, "start": 1000},
    "target_3k": {"name": "1K - 3K Target", "price": "300₹", "target": 3000, "start": 1000},
    "target_4k": {"name": "1K - 4K Target", "price": "400₹", "target": 4000, "start": 1000},
    "target_5k": {"name": "1K - 5K Target", "price": "500₹", "target": 5000, "start": 1000},
}

# --- Game Logic Constants ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32] 
MAX_LEVEL = len(BETTING_SEQUENCE)
MAX_HISTORY_LENGTH = 12 
PATTERN_LENGTH = 4
PATTERN_PROBABILITY = 0.8

# --- SALTS ---
V5_SALT = "ar-lottery-v5-plus"
TRUSTWIN_SALT = "gods_plan"

ALL_PATTERNS = [
    (['Big', 'Big', 'Big', 'Big'], "BBBB"),
    (['Small', 'Small', 'Small', 'Small'], "SSSS"),
    (['Big', 'Big', 'Small', 'Small'], "BBSS"),
    (['Small', 'Small', 'Big', 'Big'], "SSBB"),
    (['Big', 'Small', 'Big', 'Small'], "BSBS"),
    (['Small', 'Big', 'Small', 'Big'], "SBSB"),
    (['Small', 'Big', 'Big', 'Small'], "SBBS"),
    (['Big', 'Small', 'Small', 'Big'], "BSSB"),
]

# --- SHARED STATES (Used across modules) ---
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, 
 TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP,
 ADMIN_BROADCAST_MSG, SURESHOT_MENU, SURESHOT_LOOP,
 ADMIN_GIFT_WAIT, SELECTING_PLATFORM) = range(13)
