import logging
import os
import time
import random # ⬅️ ADDED: Required for pattern logic
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from pymongo import MongoClient
from dotenv import load_dotenv

# 🆕 Import the new referral system functions
from referral_system import (
    check_and_award_referral, 
    handle_refer, 
    redeem_points_prompt,
    confirm_redeem,
    cancel_redeem,
    get_referral_link, # Needed for the main start message link
    REFERRAL_POINTS_AWARD, # For documentation/logging
    PACKAGE_POINT_COST, # For documentation/logging
)

# --- Configuration and Environment Setup ---
load_dotenv()

# Replace with your actual Bot Token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
# Replace with your MongoDB connection string (e.g., "mongodb+srv://user:pass@cluster.mongodb.net/dbname")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_DB_CONNECTION_STRING")
# Replace with the actual chat ID of the administrator
ADMIN_ID = int(os.getenv("ADMIN_ID", "YOUR_ADMIN_CHAT_ID"))

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Setup (MongoDB) ---
users_collection = None # Initialize outside try/except
try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db  # Database name
    users_collection = db.users  # Collection for user data and requests
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")

# --- States for ConversationHandler ---
(
    SELECTING_PLAN,
    WAITING_FOR_PAYMENT_PROOF,
    WAITING_FOR_UTR,
    # Existing state for prediction request
    WAITING_FOR_PERIOD_NUMBER, 
    # NEW STATE FOR WIN/LOSS FEEDBACK
    WAITING_FOR_FEEDBACK,
) = range(5) 

# --- Constants ---
REGISTER_LINK = "https://t.me/+pR0EE-BzatNjZjNl"
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png?ex=69041327&is=6902c1a7&hm=517ecf60348db21c748797801a6bcdc08336d7020d3bf41c889abe22ba4a4d26&"
PREDICTION_PROMPT = "➡️ **Please reply to this message with the Period Number** for which you want the next prediction."

# ⭐ UPDATED: Only 7 Day and PERMANENT plans
PREDICTION_PLANS = {
    # Duration is in seconds for easy calculation
    "7_day": {"name": "7 Day Access", "price": "300₹", "duration_seconds": 604800},
    # Use a very large number for 'Permanent' access (e.g., 50 years)
    "permanent": {"name": "Permanent Access", "price": "500₹", "duration_seconds": 1576800000},
}

# ⬇️ REMOVED: OLD PREDICTION PATTERN CONSTANTS ⬇️
# PREDICTION_PATTERN = ["Small", "Big", "Big", "Small"]
# LOSS_RECOVERY_PATTERN = ["Big", "Small"]

# --- NEW: Advanced Prediction & Martingale Constants (from game_helper_bot.py) ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32] # Martingale betting units
MAX_LEVEL = len(BETTING_SEQUENCE)       # Maximum level (6)
MAX_HISTORY_LENGTH = 5                  # How many past results to track for pattern matching
PATTERN_PROBABILITY = 0.6               # 60% chance to follow Martingale trend on a Loss

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
# --- END NEW CONSTANTS ---


# --- Utility Functions ---

def update_user_field(user_id, field, value):
    """Updates a single field for a user in MongoDB."""
    if users_collection is None: 
        logger.warning(f"Cannot update DB for user {user_id}. Connection unavailable.")
        return
        
    users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def get_user_data(user_id):
    """Retrieves user data from MongoDB or creates a new entry if not found."""
    if users_collection is None: 
        logger.warning("Database connection unavailable. Returning empty user data.")
        return {}
        
    user = users_collection.find_one({"user_id": user_id})
    if user is None:
        user = {
            "user_id": user_id,
            "username": None,
            "prediction_status": "NONE", 
            "prediction_plan": None,
            "expiry_timestamp": 0, # Timestamp when subscription ends (0 if none)
            # ⬇️ NEW FIELDS replacing 'loss_streak'
            "current_level": 1, # Martingale Level 1-6
            "current_prediction": random.choice(['Small', 'Big']), # Last prediction given
            "history": [], # Last N outcomes (Small/Big)
            "current_pattern_name": "Random (New User)", 
            # 🆕 NEW FIELDS FOR REFERRAL SYSTEM
            "referrer_id": None, # ID of the user who referred this new user
            "referral_points": 0, # Points balance for redemption
        }
        users_collection.insert_one(user)
    else:
        # ⬇️ CLEANUP AND INITIALIZE NEW FIELDS FOR EXISTING USERS
        # Clean up old field if it exists
        if "loss_streak" in user:
            del user["loss_streak"]
            update_user_field(user_id, "loss_streak", None) # Remove from DB
        
        # Check and initialize new fields
        if "current_level" not in user:
            user["current_level"] = 1
            update_user_field(user_id, "current_level", 1) 
        if "current_prediction" not in user:
            user["current_prediction"] = random.choice(['Small', 'Big'])
            update_user_field(user_id, "current_prediction", user["current_prediction"])
        if "history" not in user:
            user["history"] = []
            update_user_field(user_id, "history", [])
        if "current_pattern_name" not in user:
            user["current_pattern_name"] = "Random (No History)"
            update_user_field(user_id, "current_pattern_name", user["current_pattern_name"])
            
        # 🆕 Ensure new fields exist for existing users on load (Referral system)
        if "referrer_id" not in user:
            user["referrer_id"] = None
            update_user_field(user_id, "referrer_id", None) 
        if "referral_points" not in user:
            user["referral_points"] = 0
            update_user_field(user_id, "referral_points", 0) 
        
    return user

def is_subscription_active(user_data) -> bool:
    """Checks if the subscription is currently active based on expiry time."""
    if user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time():
        return True
    return False

def get_remaining_time_str(expiry_timestamp: int) -> str:
    """Formats the remaining time string."""
    remaining_seconds = int(expiry_timestamp - time.time())
    
    # Check for 'Permanent' (very large timestamp)
    if remaining_seconds > 1000000000: # Over ~31 years, assume permanent
        return "Permanent"
        
    if remaining_seconds <= 0:
        return "Expired"
        
    days = remaining_seconds // 86400
    hours = (remaining_seconds % 86400) // 3600
    minutes = (remaining_seconds % 3600) // 60
    
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"

# --- CORE PATTERN MATCHING AND PREDICTION LOGIC ---

def get_bet_unit(level: int) -> int:
    """Returns the current bet unit based on the user's current level."""
    # Sequence is 0-indexed, so Level 1 is index 0
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1 # Default to 1 if level is out of bounds

def get_next_pattern_prediction(history: list) -> tuple[str | None, str]:
    """
    Analyzes the history to find the best matching pattern and determines the next prediction.
    Returns (next_prediction, pattern_name).
    """
    history_len = len(history)
    
    if history_len == 0:
        return random.choice(['Small', 'Big']), "Random (No History)"
    
    # Only consider the most recent MAX_HISTORY_LENGTH results
    recent_history = history[-MAX_HISTORY_LENGTH:]
    recent_history_len = len(recent_history)
    
    best_match_prediction = None
    best_pattern_name = "Random (No Pattern Match)"

    for pattern_list, pattern_name in ALL_PATTERNS:
        pattern_len = len(pattern_list)
        
        # Scenario 1: History is the START of a pattern
        if recent_history_len < pattern_len:
            # Check if the recent history matches the start of the pattern
            if recent_history == pattern_list[:recent_history_len]:
                best_match_prediction = pattern_list[recent_history_len] # Predict the next element
                best_pattern_name = pattern_name
                return best_match_prediction, best_pattern_name 
        
        # Scenario 2: History is an EXACT match for a completed pattern
        elif recent_history_len == pattern_len:
            if recent_history == pattern_list:
                # If a full pattern matches, predict the start of the pattern to loop the cycle
                best_match_prediction = pattern_list[0] 
                best_pattern_name = pattern_name
                # Prioritize a full MAX_HISTORY_LENGTH match if possible
                if pattern_len == MAX_HISTORY_LENGTH:
                    return best_match_prediction, best_pattern_name
                
    return best_match_prediction, best_pattern_name


def generate_new_prediction(user_id: int, outcome: str) -> str:
    """
    Generates the next prediction based on history, pattern matching, and Martingale blending.
    This function updates the user's history and the prediction for the next round.
    """
    # Use the local get_user_data/update_user_field
    state = get_user_data(user_id) 
    current_prediction = state.get('current_prediction', random.choice(['Small', 'Big']))
    
    # 1. Determine the actual outcome of the previous round
    if outcome == 'win':
        actual_outcome = current_prediction
    else: # outcome == 'loss'
        actual_outcome = 'Big' if current_prediction == 'Small' else 'Small'
        
    # Add the actual outcome to history and trim
    history = state.get('history', [])
    history.append(actual_outcome)
    if len(history) > MAX_HISTORY_LENGTH:
        history.pop(0) 
        
    # Update DB with new history
    update_user_field(user_id, "history", history)

    # 2. Get Pattern Suggested Prediction
    pattern_prediction, pattern_name = get_next_pattern_prediction(history)
    
    new_prediction = current_prediction # Default: Martingale trend repeat (in case of loss)
    
    if outcome == 'win':
        # WIN: Always follow the pattern's suggestion if available, otherwise alternate.
        if pattern_prediction:
            new_prediction = pattern_prediction
        else:
            new_prediction = 'Big' if current_prediction == 'Small' else 'Small'
        
    elif outcome == 'loss':
        # LOSS: Martingale blend logic (60% trend / 40% pattern break)
        
        if random.random() < PATTERN_PROBABILITY:
            # 60% chance: Follow Martingale Trend (repeat the failed bet)
            new_prediction = current_prediction
            
        else:
            # 40% chance: Introduce "thinking" by following the suggested pattern if available, 
            # otherwise, break the Martingale trend by picking the opposite.
            if pattern_prediction:
                new_prediction = pattern_prediction
            else:
                new_prediction = 'Big' if current_prediction == 'Small' else 'Small'

    # 3. Update state for the next round in DB
    update_user_field(user_id, "current_prediction", new_prediction)
    update_user_field(user_id, "current_pattern_name", pattern_name)
    
    return new_prediction

# --- END CORE PATTERN MATCHING AND PREDICTION LOGIC ---

def get_prediction_keyboard(user_data):
    """Generates the main keyboard based on user status."""
    status = user_data.get("prediction_status")
    expiry_timestamp = user_data.get("expiry_timestamp", 0)
    
    # Get user's points for display/redemption access
    current_points = user_data.get("referral_points", 0)
    
    buttons = [
        [
            InlineKeyboardButton("💬 Telegram", url=REGISTER_LINK),
        ]
    ]
    
    # 🆕 Add the referral/points button to the main keyboard
    buttons.append([
        InlineKeyboardButton(f"⭐ Points: {current_points}", callback_data="open_referral_menu")
    ])
    
    if is_subscription_active(user_data):
        time_left = get_remaining_time_str(expiry_timestamp)
        buttons.append([
            InlineKeyboardButton(f"✨ Get Prediction (Time Left: {time_left})", callback_data="show_prediction")
        ])
    elif status == "ADMIN_REVIEW" or status == "PENDING_UTR":
        buttons.append([
            InlineKeyboardButton("🔍 Subscription Status: Under Review", callback_data="subscription_status")
        ])
    else:
        # Default or Expired
        buttons.append([
            InlineKeyboardButton("🔮 Prediction Packages", callback_data="start_prediction_flow")
        ])
    
    return InlineKeyboardMarkup(buttons)

# --- New Function to grant access (called by admin_accept AND point redemption) ---
async def grant_prediction_access(user_id: int, plan_key: str, reason: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Calculates expiry time, sets status to ACTIVE, and schedules expiry job."""
    
    if plan_key not in PREDICTION_PLANS:
        logger.error(f"Attempted to grant unknown plan key: {plan_key} to user {user_id}")
        return
        
    plan = PREDICTION_PLANS[plan_key]
    duration_seconds = plan["duration_seconds"]
    
    # 1. Calculate Expiry Time
    expiry_timestamp = time.time() + duration_seconds
    
    # 2. Update User Status in DB
    update_user_field(user_id, "prediction_status", "ACTIVE")
    update_user_field(user_id, "expiry_timestamp", int(expiry_timestamp))
    
    # 3. Schedule the Expiry Job (to notify user when time is up)
    job_name = f"pred_expiry_{user_id}"
    if plan_key != "permanent": 
        current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
            
        context.application.job_queue.run_once(
            notify_subscription_expired,
            duration_seconds, 
            data={"buyer_id": user_id},
            name=job_name,
        )
        
    # 4. Inform User
    time_left_str = get_remaining_time_str(int(expiry_timestamp))
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🟢 Subscription Activated! ({reason}) 🟢\n\n"
                 f"You now have {plan['name']} access. Expires: {time_left_str}.\n"
                 "Please use the 'Get Prediction' button in your main menu (/start) to receive your exclusive content repeatedly until your access expires.",
        )
    except Exception as e:
        logger.warning(f"Could not message user {user_id} after granting access: {e}")

# --- Bot Command Handlers ---

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allows user to cancel the current conversation flow."""
    user_id = update.effective_user.id
    
    if update.callback_query:
        await update.callback_query.answer()
        # Attempt to edit the message the button was on
        try:
            await update.callback_query.edit_message_text("Operation cancelled. Returning to main menu. Type /start.")
        except Exception:
            await context.bot.send_message(user_id, "Operation cancelled. Returning to main menu. Type /start.")
    else:
        await update.message.reply_text("Operation cancelled. Returning to main menu. Type /start.")

    return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the initial message and main menu keyboard."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # --- 1. Get/Create User Data ---
    user_data = get_user_data(user_id)
    
    # Update username if it changed
    if user_data.get("username") != username:
        update_user_field(user_id, "username", username)
    
    # Check if a subscription just expired and clean up status
    if user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) != 0 and user_data.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user_data["prediction_status"] = "NONE" # Update local data for this run
        
    
    # --- 2. Check for Referral ID in /start Payload ---
    if update.message and update.message.text and update.message.text.startswith('/start '):
        # Extract payload: '/start 123456789' -> '123456789'
        start_payload = update.message.text.split(' ', 1)[-1] 
        
        # Pass necessary dependencies to the imported function
        await check_and_award_referral(
            context, 
            user_id, 
            start_payload, 
            users_collection,
            update_user_field # Pass the local update function
        )
        
        # Re-fetch user data to reflect potential points or referrer_id change
        user_data = get_user_data(user_id) 

    # --- 3. Generate Response ---
    keyboard = get_prediction_keyboard(user_data) # Generate keyboard based on latest status
    
    initial_message = f"👋 Welcome, {update.effective_user.first_name}!\n\nUse the buttons below to register or manage your prediction package."

    # If the user's status was just reset from active to none
    if user_data.get("prediction_status") == "NONE" and user_data.get("expiry_timestamp", 0) != 0:
        initial_message = (
            f"👋 Welcome, {update.effective_user.first_name}!\n\n"
            "⚠️ Your previous subscription has expired. Please purchase a new package to continue 📦."
        )

    
    if update.message:
        await update.message.reply_text(
            initial_message,
            reply_markup=keyboard,
        )
    elif update.callback_query:
        # FIX: Ensure menu refresh works correctly when called from a callback
        try:
            await update.callback_query.edit_message_text(initial_message, reply_markup=keyboard)
        except Exception:
            # If the original message is too old to edit
            await update.callback_query.message.reply_text(initial_message, reply_markup=keyboard)
        
    return ConversationHandler.END


# --- Prediction Purchase Flow (ConversationHandler) ---

async def start_prediction_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Displays prediction options."""
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{p['name']} - {p['price']}", callback_data=f"select_plan_{k}")
            ]
            for k, p in PREDICTION_PLANS.items()
        ]
    )

    await query.edit_message_text(
        "Choose your prediction package for continuous access:",
        reply_markup=keyboard,
    )
    return SELECTING_PLAN

async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: User selects a plan and is prompted for payment proof."""
    query = update.callback_query
    await query.answer() 
    
    plan_key = query.data.replace("select_plan_", "") 
    plan = PREDICTION_PLANS.get(plan_key)
    user_id = query.from_user.id

    if not plan:
        await query.edit_message_text("Invalid plan selected. Please restart with /start.")
        return ConversationHandler.END

    # Store selected plan in conversation context and DB
    context.user_data["selected_plan_key"] = plan_key
    update_user_field(user_id, "prediction_plan", plan_key)
    update_user_field(user_id, "prediction_status", "PENDING_UTR")
    
    # Send Payment Instructions and Image
    payment_message = (
        f"✅ You selected: {plan['name']} - ({plan['price']})\n\n"
        "Please complete the payment to the displayed QR code/UPI ID and click 'Sended 🟢'.\n\n"
        "**NOTE:** This is a demonstration. Use a real payment method in a production bot."
    )
    
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Sended 🟢", callback_data="payment_sent")]]
    )
    
    # Edit the text message to prompt for the photo and caption
    try:
         await query.edit_message_text("Payment instructions are being sent via a new message...")
    except:
         pass # Ignore edit errors if message was already edited or is old

    # Send new photo message with payment details
    try:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=PAYMENT_IMAGE_URL,
            caption=payment_message,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Failed to send payment photo to user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🚨 **An error occurred** while fetching payment details. Please contact support. (Error: {e})",
        )
        return ConversationHandler.END 


    return WAITING_FOR_PAYMENT_PROOF


async def payment_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: User confirms payment, asks for UTR."""
    query = update.callback_query
    await query.answer()
    
    try:
        # FIX: Use edit_message_caption since the last message was a photo
        await query.edit_message_caption(
            caption="Thank you for confirming! Now, please **reply to this message** with your **UTR (Unique Transaction Reference) Number** so the admin can verify your payment.",
            reply_markup=None, # Remove the 'Sended' button
        )
    except Exception:
         # Fallback to text message edit if caption edit fails (e.g., if message wasn't a photo)
         await query.edit_message_text(
             "Thank you for confirming! Now, please **reply to this message** with your **UTR (Unique Transaction Reference) Number** so the admin can verify your payment."
         )
         
         return WAITING_FOR_UTR


async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4: User sends UTR, updates status to ADMIN_REVIEW, and alerts admin."""
    utr = update.message.text
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    
    user_data = get_user_data(user_id)
    plan_key = user_data.get('prediction_plan') # Get the plan key from the user's DB entry

    if not plan_key or plan_key not in PREDICTION_PLANS:
        await update.message.reply_text("Error: Plan data missing. Please try /start again.")
        return ConversationHandler.END
    
    # Store UTR and update status
    update_user_field(user_id, "last_utr", utr)
    update_user_field(user_id, "prediction_status", "ADMIN_REVIEW")
    
    # 1. Inform User
    await update.message.reply_text(
        f"**Payment Notification Received!**\n\n"
        f"Your payment (UTR: `{utr}`) is now under review by the administrator.\n"
        "You will receive a notification once your access is approved."
    )
    
    # 2. Alert Admin
    admin_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Accept Request", callback_data=f"admin_accept_{user_id}"),
                InlineKeyboardButton("❌ Reject Request", callback_data=f"admin_reject_{user_id}"),
            ]
        ]
    )
    
    admin_message = (
        "🔔 **NEW PAYMENT REVIEW REQUIRED**\n\n"
        f"User: [{user_name}](tg://user?id={user_id})\n"
        f"User ID: `{user_id}`\n"
        f"Plan: **{PREDICTION_PLANS[plan_key]['name']}**\n"
        f"UTR Provided: `{utr}`\n\n"
        "Please check your bank records and confirm the payment. Click Accept to grant access."
    )
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            reply_markup=admin_keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")
    
    # End the UTR conversation
    return ConversationHandler.END

# --- Admin Panel Handlers ---

async def admin_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Admin clicks ACCEPT. Uses the new grant_prediction_access function.
    """
    query = update.callback_query
    await query.answer("Granting access...")

    # Extract the user ID of the buyer from callback data
    buyer_id = int(query.data.split("_")[-1])
    
    # 1. Get user data to find the purchased plan
    buyer_data = get_user_data(buyer_id)
    plan_key = buyer_data.get("prediction_plan")

    if not plan_key or plan_key not in PREDICTION_PLANS:
        # FIX: Reset user status on error
        update_user_field(buyer_id, "prediction_status", "NONE")
        await query.edit_message_text(f"Error: Could not find valid plan for user `{buyer_id}`. User status reset.")
        return ConversationHandler.END
        
    # 2. Grant Access
    await grant_prediction_access(buyer_id, plan_key, 'Paid Access', context)
    
    # 3. Inform Admin
    plan = PREDICTION_PLANS[plan_key]
    time_left_str = get_remaining_time_str(int(time.time() + plan['duration_seconds']))
    await query.edit_message_text(
        f"✅ Access granted to user `{buyer_id}` for **{plan['name']}**.\n"
        f"Subscription expires in: {time_left_str}."
    )
    
    # No need for a conversation state change, as this is a single action
    return ConversationHandler.END
    
async def admin_reject_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicks REJECT."""
    query = update.callback_query
    await query.answer("Rejecting request...")

    buyer_id = int(query.data.split("_")[-1])
    
    # Reset user status
    update_user_field(buyer_id, "prediction_status", "NONE")
    update_user_field(buyer_id, "prediction_plan", None)
    
    # Inform user of rejection
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="❌ **Payment Verification Failed**\n\n"
                 "The UTR provided could not be verified. Your request has been rejected. "
                 "Please check your payment and try again via /start or contact support."
        )
    except Exception as e:
        logger.warning(f"Could not message rejected user {buyer_id}: {e}")
        
    await query.edit_message_text(f"❌ Request for user `{buyer_id}` has been rejected and user was notified.")
    # No conversation to end here, just an action
    return ConversationHandler.END
    
    
    # --- JobQueue Callback Function ---

async def notify_subscription_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job function that runs when the subscription expires."""
    job_data = context.job.data
    buyer_id = job_data["buyer_id"]
    
    # Set status to NONE (Expired)
    update_user_field(buyer_id, "prediction_status", "NONE")
    update_user_field(buyer_id, "expiry_timestamp", 0)
    update_user_field(buyer_id, "prediction_plan", None)
    
    # ⬇️ Reset new state variables on expiry (Replacing old 'loss_streak' reset)
    update_user_field(buyer_id, "current_level", 1) 
    update_user_field(buyer_id, "current_prediction", random.choice(['Small', 'Big'])) 
    update_user_field(buyer_id, "history", []) 
    update_user_field(buyer_id, "current_pattern_name", "Random (Reset)") 
    
    # Send final notification to user
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="🛑 **SUBSCRIPTION EXPIRED!** 🛑\n\n"
                 "Your exclusive access has ended. Please use /start to view new subscription options.",
        )
    except Exception as e:
        logger.error(f"Failed to send EXPIRY notification to user {buyer_id}: {e}")

# --- Final Prediction Delivery (Recurring Access) ---

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Delivers the prediction message if the user is in the 'ACTIVE' state, or starts the conversation to get the period number."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    user_data = get_user_data(user_id)
    
    if is_subscription_active(user_data):
        time_left_str = get_remaining_time_str(user_data["expiry_timestamp"])
        
        # 1. Inform the user and enter the new state
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🟢 **Access Active!** Access remaining: {time_left_str}\n\n{PREDICTION_PROMPT}",
            parse_mode="Markdown",
        )
        
        # 2. MOVE TO THE NEW STATE
        return WAITING_FOR_PERIOD_NUMBER
        
    else:
        # Subscription is inactive or expired
        if user_data.get("prediction_status") == "ACTIVE":
             update_user_field(user_id, "prediction_status", "NONE")
             user_data["prediction_status"] = "NONE"

        await context.bot.send_message(
             chat_id=user_id,
             text="❌ **Access Denied/Expired.** Please use /start to renew your prediction package.",
             reply_markup=get_prediction_keyboard(user_data)
        )
        
        # FIX: Ensure the button they clicked updates to reflect the expired status
        await query.edit_message_reply_markup(get_prediction_keyboard(user_data))
        
        # End the conversation if access is denied
        return ConversationHandler.END
        
async def receive_period_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    period_number_str = update.message.text.strip()
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    # 🛑 Re-check subscription status
    if not is_subscription_active(user_data):
        # 1. Inform the user
        await update.message.reply_text(
            "❌ **Access Denied/Expired.** Your subscription is no longer active. Please use /start to renew your prediction package.",
            reply_markup=get_prediction_keyboard(user_data)
        )
        # 2. End the conversation so they can't send another period number
        return ConversationHandler.END
        
    # Basic validation: check if it's a number
    try:
        period_number = int(period_number_str)
        if period_number < 1: 
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid Period Number. Please send a valid positive number."
        )
        return WAITING_FOR_PERIOD_NUMBER # Stay in the same state
        
    # --- Prediction Logic based on User State (NEW LOGIC) ---
    
    # 1. Get the current strategy details from the user's state
    current_level = user_data.get("current_level", 1)
    # This is the prediction generated in the *previous* round (or initial prediction)
    prediction = user_data.get("current_prediction", random.choice(['Small', 'Big'])) 
    pattern_name = user_data.get("current_pattern_name", "Analyzing...")
    
    bet_unit = get_bet_unit(current_level)
    
    # 2. Determine the message type (SURESHOT if max level is reached)
    prediction_type = ""
    if current_level >= MAX_LEVEL:
        prediction_type = "🚨 SURESHOT BET (Max Level Reached) 🚨\n\n"
        
    # --- Response Generation ---
    response_message = (
        f"{prediction_type}"
        f"⏳ **Strategy for Period {period_number}:**\n\n"
        f"Period Number → `{period_number}`\n"
        f"Bet On → **{prediction}**\n"
        f"Bet Unit → **Level {current_level}** ({bet_unit} Units)\n"
        f"Tracked Pattern → *{pattern_name}*\n"
        f"Note → *Please report the outcome with the buttons below.*"
    )
    
    # WIN/LOSS Feedback Keyboard
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ WIN", callback_data="feedback_win"),
            InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss"),
        ]]
    )
    
    await update.message.reply_text(
        response_message,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    
    # Transition to the state that awaits WIN/LOSS feedback
    return WAITING_FOR_FEEDBACK


# --- Handler for WIN/LOSS feedback (UPDATED LOGIC) ---

async def handle_prediction_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user clicking WIN or LOSS, updates the Martingale level, and generates the next prediction."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_name = query.from_user.full_name 
    
    feedback = query.data.split("_")[-1]  # 'win' or 'loss'
    
    user_data = get_user_data(user_id)
    current_level = user_data.get("current_level", 1)
    
    # --- 1. Update Martingale Level based on Feedback ---
    
    if feedback == "win":
        # Reset level on a WIN
        new_level = 1
        update_user_field(user_id, "current_level", new_level)
        level_message = "✅ Great! Sequence reset to Level 1."
        
    elif feedback == "loss":
        # Advance level on a LOSS
        if current_level < MAX_LEVEL:
            new_level = current_level + 1
            update_user_field(user_id, "current_level", new_level)
            level_message = f"📉 Loss. Sequence advanced to **Level {new_level}**."
        else:
            # Max level reached, do not advance, but alert admin
            new_level = MAX_LEVEL
            level_message = f"⚠️ **MAX LEVEL REACHED ({MAX_LEVEL})**."
            
            # Message for the ADMIN
            admin_loss_message = (
                "🚨 ALERT 🚨\n\n"
                f"User: [{user_name}](tg://user?id={user_id})\n" 
                f"User ID: `{user_id}`\n"
                f"**MAX LEVEL CROSSED** for the user. Monitor closely or initiate refund."
            )
         
            await context.bot.send_message( # Send the admin message
                chat_id=ADMIN_ID,
                text=admin_loss_message,
                parse_mode="Markdown",
            )
    else:
        await query.edit_message_text("Invalid feedback received. Please use /start to refresh.")
        return ConversationHandler.END

    # --- 2. Generate Next Prediction and Update State (History/Pattern) ---
    
    # This function internally updates the 'current_prediction', 'history', and 'current_pattern_name'
    new_prediction = generate_new_prediction(user_id, feedback)
    
    # 3. Get the new strategy details for the next message display
    new_user_data = get_user_data(user_id) # Re-fetch to get new pattern name, etc.
    new_pattern_name = new_user_data.get("current_pattern_name", "Analyzing...")
    new_bet_unit = get_bet_unit(new_level)
    
    # --- 4. Edit the feedback message and prompt for the next period number ---
    
    response_message = (
        f"You recorded a **{feedback.upper()}** for the last prediction. {level_message}\n\n"
        f"➡️ **NEXT SUGGESTED STRATEGY**\n"
        f"Bet On → **{new_prediction}**\n"
        f"Bet Unit → **Level {new_level}** ({new_bet_unit} Units)\n"
        f"Tracked Pattern → *{new_pattern_name}*\n\n"
        f"{PREDICTION_PROMPT}"
    )

    await query.edit_message_text(
        response_message,
        parse_mode="Markdown"
    )
    
    # We must return to WAITING_FOR_PERIOD_NUMBER to get the next input
    return WAITING_FOR_PERIOD_NUMBER
    
async def show_subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Informs the user about their current payment/review status."""
    query = update.callback_query
    await query.answer(cache_time=1) # Prevent endless spinning

    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    current_status = user_data.get("prediction_status", "NONE")

    if current_status == "ADMIN_REVIEW":
        await query.answer("Your payment is currently being reviewed by the admin. Please wait for the approval notification.", show_alert=True)
    elif current_status == "PENDING_UTR":
        await query.answer("You need to enter your UTR number to proceed with payment verification.", show_alert=True)
    elif current_status == "NONE":
         await query.answer("You do not have an active request or subscription. Please purchase a plan.", show_alert=True)
    else:
        await query.answer(f"Status: {current_status}", show_alert=True)


# --- Main Application Setup ---

def main() -> None:
    """Run the bot."""
    # Build application with JobQueue implicitly included
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 🆕 Add the database dependencies to the application context 
    # so they can be accessed by functions in referral_system.py
    if users_collection is not None:
        application.user_data_accessors = {
            'users_collection': users_collection,
            'update_user_field': update_user_field,
            'get_user_data': get_user_data,
            'grant_prediction_access': lambda user_id, plan_key, reason, context: grant_prediction_access(user_id, plan_key, reason, context),
        }
    
    # 1. Main Command Handler (Start and Subscription Status)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel)) # Added global cancel handler
    
    # 🆕 New Referral Command Handler
    application.add_handler(CommandHandler("refer", handle_refer))


    # 2. Prediction Purchase Conversation Handler
    prediction_flow_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_prediction_flow, pattern="^start_prediction_flow$")],
        states={
               SELECTING_PLAN: [
                CallbackQueryHandler(select_plan, pattern="^select_plan_"), 
            ],
            WAITING_FOR_PAYMENT_PROOF: [
                CallbackQueryHandler(payment_sent, pattern="^payment_sent$"),
            ],
            WAITING_FOR_UTR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr),
            ],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)], 
        allow_reentry=True,
    )
    application.add_handler(prediction_flow_handler)

    # 3. Prediction REQUEST Conversation Handler to handle feedback
    prediction_request_handler = ConversationHandler(
        # Entry point is the 'Get Prediction' button
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={
            WAITING_FOR_PERIOD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_period_number),
            ],
            # NEW STATE: Wait for WIN or LOSS button click
            WAITING_FOR_FEEDBACK: [
                   CallbackQueryHandler(handle_prediction_feedback, pattern="^feedback_"),
            ],
        },
        # Allow /start or /cancel to interrupt the flow
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)], 
        allow_reentry=True,
    )
    application.add_handler(prediction_request_handler) 
    
    # 🆕 Referral/Redemption Handlers
    application.add_handler(CallbackQueryHandler(handle_refer, pattern="^open_referral_menu$"))
    application.add_handler(CallbackQueryHandler(redeem_points_prompt, pattern="^redeem_points$"))
    application.add_handler(CallbackQueryHandler(confirm_redeem, pattern="^confirm_redeem$"))
    application.add_handler(CallbackQueryHandler(cancel_redeem, pattern="^cancel_redeem$"))
    
    # 4. Admin Approval Handler (only for the admin)
    application.add_handler(
        CallbackQueryHandler(admin_accept_request, pattern="^admin_accept_")
    )
    application.add_handler(
        CallbackQueryHandler(admin_reject_request, pattern="^admin_reject_")
    )
    
    # 5. Final Status Handler
    application.add_handler(CallbackQueryHandler(show_subscription_status, pattern="^subscription_status$"))

    # Start the Bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":


    main()
