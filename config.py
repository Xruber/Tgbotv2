import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) 

# --- Constants ---
REGISTER_LINK = "https://t.me/+pR0EE-BzatNjZjNl" 
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/888361275464220733/1451949298928455831/Screenshot_20251029-1135273.png?ex=694808a8&is=6946b728&hm=2b920f75e28d14bf4aa34e27193217c3a0e61a2f0ff782378f787d22898e84a3&"
PREDICTION_PROMPT = "➡️ **Please reply to this message with the Period Number** for which you want the next prediction."

# --- Plans ---
PREDICTION_PLANS = {
    "7_day": {"name": "7 Day Access", "price": "300₹", "duration_seconds": 604800},
    "permanent": {"name": "Permanent Access", "price": "500₹", "duration_seconds": 1576800000},
}

# --- Game Logic Constants ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32] 
MAX_LEVEL = len(BETTING_SEQUENCE)
MAX_HISTORY_LENGTH = 5 
PATTERN_PROBABILITY = 0.8 # Used in V1

ALL_PATTERNS = [
    (['Small', 'Small', 'Big', 'Big'], "SSBB"),
    (['Big', 'Big', 'Big', 'Big'], "BBBB"),
    (['Small', 'Small', 'Small', 'Small'], "SSSS"),
    (['Big', 'Big', 'Small', 'Small'], "BBSS"),
    (['Small', 'Small', 'Big', 'Small'], "SSBS"),
    (['Big', 'Big', 'Small', 'Big'], "BBSB"),
    (['Small', 'Small', 'Big', 'Small', 'Small'], "SSBSS"),
    (['Big', 'Big', 'Small', 'Big', 'Big'], "BBSBB"),
    (['Small', 'Big', 'Big', 'Small'], "SBBS"),
    (['Big', 'Small', 'Small', 'Big'], "BSSB"),

]

