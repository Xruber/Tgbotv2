import logging
import time
import os
import random
import re
from typing import Callable, Awaitable, Optional

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, error
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters,
    ConversationHandler,
)

# New Imports for Database and Config
from pymongo import MongoClient
from dotenv import load_dotenv

# --- Configuration and Environment Setup (New) ---
load_dotenv()

# IMPORTANT: Replace with your actual Bot Token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
# Replace with your MongoDB connection string
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_DB_CONNECTION_STRING")
# Replace with the actual chat ID of the administrator
ADMIN_ID = int(os.getenv("ADMIN_ID", "6239774927")) # ⚠️ REPLACE THIS

# --- Prediction & Payment Constants (New/Updated) ---
REGISTER_LINK = "https://t.me/+pR0EE-BzatNjZjNl" # Replace with your group link
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png?ex=69041327&is=6902c1a7&hm=517ecf60348db21c748797801a6bcdc08336d7020d3bf41c889abe22ba4a4d26&" # ⚠️ REPLACE THIS WITH YOUR QR/UPI IMAGE URL
PREDICTION_PROMPT = "➡️ **Please reply to this message with the Period Number** for which you want the next prediction."

# ⭐ Prediction Plans (As requested)
PREDICTION_PLANS = {
    "7_day": {"name": "7 Day Access", "price": "300₹", "duration_seconds": 604800},
    "permanent": {"name": "Permanent Access", "price": "500₹", "duration_seconds": 1576800000},
}

# --- States for ConversationHandler (New) ---
(
    SELECTING_PLAN,
    WAITING_FOR_PAYMENT_PROOF,
    WAITING_FOR_UTR,
    WAITING_FOR_PERIOD_NUMBER, 
    WAITING_FOR_FEEDBACK,
) = range(5) 

# --- Pattern Definitions (Original Martingale) ---
BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32] 
MAX_LEVEL = len(BETTING_SEQUENCE)

# --- NEW SIMPLIFIED PATTERN LOGIC CONSTANTS ---
# Loss sequence patterns (actual outcomes) to trigger a prediction switch
LOSS_PATTERN_1 = ['Small', 'Big', 'Small'] # User's case: Loss, Win, Loss (Actual: S, B, S) -> Predict Big
LOSS_PATTERN_2 = ['Big', 'Small', 'Big']   # User's case: Loss, Win, Loss (Actual: B, S, B) -> Predict Small
PATTERN_LENGTH = 3
MAX_HISTORY_LENGTH = 3 # Only need 3 outcomes to check the pattern


# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Database Setup (MongoDB) (New) ---
users_collection = None 
try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db  # Database name
    users_collection = db.users  # Collection for user data and requests
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")

# --- DB Utility Functions (New) ---

def update_user_field(user_id, field, value):
    """Updates a single field for a user in MongoDB."""
    if users_collection is None: 
        logger.warning(f"Cannot update DB for user {user_id}. Connection unavailable.")
        return
    users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def get_user_data(user_id):
    """Retrieves user data from MongoDB or creates a new entry if not found."""
    if users_collection is None: 
        return {}
        
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
            "history": [], # History tracks the actual outcomes (S/B)
            "current_pattern_name": "Random (New User)", 
            "last_game_id": '100', # Original key
        }
        users_collection.insert_one(user)
    
    # 📝 Ensure all keys are present for existing users (Migration logic)
    if "current_level" not in user:
        user["current_level"] = 1
    if "current_prediction" not in user:
        user["current_prediction"] = random.choice(['Small', 'Big'])
    if "history" not in user:
        user["history"] = []
    if "current_pattern_name" not in user:
        user["current_pattern_name"] = "Random (No History)"
    if "last_game_id" not in user:
        user["last_game_id"] = '100'

    # Clean up expired subscription status on load
    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
        
    return user

def is_subscription_active(user_data) -> bool:
    """Checks if the subscription is currently active based on expiry time."""
    if user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time():
        return True
    return False

def get_remaining_time_str(expiry_timestamp: int) -> str:
    """Formats the remaining time string."""
    remaining_seconds = int(expiry_timestamp - time.time())
    if remaining_seconds > 1000000000: return "Permanent"
    if remaining_seconds <= 0: return "Expired"
    days = remaining_seconds // 86400
    hours = (remaining_seconds % 86400) // 3600
    minutes = (remaining_seconds % 3600) // 60
    if days > 0: return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"

# --- Core Prediction Logic (SIMPLIFIED/REVISED) ---

def get_bet_unit(level: int) -> int:
    """Returns the current bet unit based on the user's current level."""
    if 1 <= level <= MAX_LEVEL:
        return BETTING_SEQUENCE[level - 1]
    return 1

def generate_new_prediction(user_id: int, outcome: str) -> str:
    """
    Generates the next prediction based on the user's simplified logic:
    1. WIN: Repeat the previous prediction.
    2. LOSS: Opposite of the previous prediction (unless 3-loss pattern is met).
    3. 3 Consecutive LOSSES (Level 4 or higher): Check the actual outcome pattern
       for ['Small', 'Big', 'Small'] or ['Big', 'Small', 'Big'] and predict the pattern's next value.
    """
    state = get_user_data(user_id)
    current_prediction = state.get('current_prediction', random.choice(['Small', 'Big']))
    current_level = state.get('current_level', 1)

    # 1. Determine the actual outcome of the previous round
    # The actual outcome is the opposite of the prediction if it was a 'loss'
    # The actual outcome is the prediction itself if it was a 'win'
    actual_outcome = current_prediction if outcome == 'win' else ('Big' if current_prediction == 'Small' else 'Small')

    # --- 2. Update History ---
    # History tracks the ACTUAL OUTCOMES of the last N games (for pattern check).
    history = state.get('history', [])
    history.append(actual_outcome)
    # We only need enough history to check the 3-loss pattern.
    if len(history) > MAX_HISTORY_LENGTH:
        history.pop(0)
    update_user_field(user_id, "history", history)

    # Default to current prediction (matches 'WIN' case)
    new_prediction = current_prediction 
    pattern_name = "Repeat on Win" 

    # --- 3. Apply New Logic ---

    if outcome == 'win':
        # Case 1: WIN -> Continue with the same prediction (Repeat Last Bet).
        new_prediction = current_prediction
        pattern_name = "Repeat on Win"

    elif outcome == 'loss':
        # Case 2: LOSS (Standard) -> Opposite of the prediction.
        # Next prediction is the opposite of the current one.
        new_prediction = 'Big' if current_prediction == 'Small' else 'Small'
        pattern_name = "Opposite on Loss (Default)"

        # Case 3: Check for 3 Consecutive LOSSES
        # A 3rd loss moves the level to 4. We check history *after* updating it with the 3rd loss.
        if current_level >= PATTERN_LENGTH + 1:
            recent_outcomes = history[-PATTERN_LENGTH:] # The last 3 ACTUAL OUTCOMES

            # Pattern 1: Small, Big, Small -> Next should be Big
            if recent_outcomes == LOSS_PATTERN_1:
                new_prediction = 'Big'
                pattern_name = "Pattern Match: S-B-S -> Big"
            
            # Pattern 2: Big, Small, Big -> Next should be Small
            elif recent_outcomes == LOSS_PATTERN_2:
                new_prediction = 'Small'
                pattern_name = "Pattern Match: B-S-B -> Small"
            
            # If 3 losses occurred but didn't match the specific patterns, it defaults to Case 2 logic.
            
    # --- 4. Update state for the next round in DB ---
    update_user_field(user_id, "current_prediction", new_prediction)
    update_user_field(user_id, "current_pattern_name", pattern_name)
    
    return new_prediction

# --- New Function to grant access (called by admin_accept) ---
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
    update_user_field(user_id, "prediction_plan", plan_key) # Ensure plan is stored

    # 3. Schedule the Expiry Job 
    job_name = f"pred_expiry_{user_id}"
    if plan_key != "permanent": 
        current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs: job.schedule_removal()
            
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
                 "Use the 'Get Strategy' button in your main menu (/start) to receive your predictions.",
        )
    except Exception as e:
        logger.warning(f"Could not message user {user_id} after granting access: {e}")

# --- General Utility Functions (New) ---

def get_main_keyboard(user_data):
    """Generates the main keyboard based on user status."""
    status = user_data.get("prediction_status")
    expiry_timestamp = user_data.get("expiry_timestamp", 0)
    
    buttons = [
        [
            InlineKeyboardButton("💬 Telegram Group", url=REGISTER_LINK),
        ]
    ]
    
    if is_subscription_active(user_data):
        time_left = get_remaining_time_str(expiry_timestamp)
        buttons.append([
            InlineKeyboardButton(f"✨ Get Strategy (Time Left: {time_left})", callback_data="show_prediction")
        ])
    elif status == "ADMIN_REVIEW" or status == "PENDING_UTR":
        buttons.append([
            InlineKeyboardButton("🔍 Subscription Status: Under Review", callback_data="subscription_status")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🔮 Strategy Packages", callback_data="start_prediction_flow")
        ])
    
    return InlineKeyboardMarkup(buttons)

# --- Telegram Command Handlers (Refactored) ---

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allows user to cancel the current conversation flow."""
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer()
        await context.bot.send_message(user_id, "Operation cancelled. Returning to main menu. Type /start.")
    else:
        await update.message.reply_text("Operation cancelled. Returning to main menu. Type /start.")
    return ConversationHandler.END


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the initial message and main menu keyboard."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    user_data = get_user_data(user_id) # Initializes state in DB
    
    if user_data.get("username") != username:
        update_user_field(user_id, "username", username)
    
    keyboard = get_main_keyboard(user_data) 
    
    initial_message = (
        f"👋 Welcome, {update.effective_user.first_name}!\n\n"
        "I am your Game Strategy Helper, using a <b>6 Level Martingale Sequence</b> and **Pattern Blended** strategy.\n"
        "Please purchase a package to get predictions."
    )

    if update.message:
        await update.message.reply_text(
            initial_message,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(initial_message, reply_markup=keyboard, parse_mode='HTML')
        except Exception:
            await update.callback_query.message.reply_text(initial_message, reply_markup=keyboard, parse_mode='HTML')
        
    return ConversationHandler.END


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resets the betting sequence and generates a new prediction in DB."""
    user_id = update.effective_user.id
    
    # Reset state in DB
    update_user_field(user_id, "current_level", 1)
    update_user_field(user_id, "history", [])
    
    new_prediction = random.choice(['Small', 'Big']) 
    update_user_field(user_id, "current_prediction", new_prediction)
    update_user_field(user_id, "current_pattern_name", "Random (Full Reset)")
    update_user_field(user_id, "last_game_id", '100')
    
    new_level, new_unit = 1, get_bet_unit(1) 
    
    await update.message.reply_text(
        "🛑 <b>Strategy Sequence Refreshed.</b>\n"
        f"Your betting sequence and pattern tracking have been completely reset.\n\n"
        f"➡️ <b>NEXT STRATEGY:</b>\n"
        f"  - <b>Predict:</b> 🎲 <b>{new_prediction}</b>\n"
        f"  - <b>Bet Unit:</b> 💰 Level {new_level} (<b>{new_unit} Unit{'s' if new_unit > 1 else ''}</b>)\n"
        f"  - <b>Tracked Pattern:</b> 📉 Random (Full Reset)\n"
        f"  - <b>NOTE:</b> Please get a new prediction (/getprediction) when your subscription is active.",
        parse_mode='HTML'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the help message."""
    await update.message.reply_text(
        "<b>Helper Bot Commands & Flow:</b>\n"
        "• /start: Main menu to check status or purchase a package.\n"
        "• Once active, click **'Get Strategy'** to start the prediction flow.\n"
        "• /reset: Reset the betting level back to 1 and clear the history/pattern tracking.\n"
        "• /cancel: Cancel any ongoing process.",
        parse_mode='HTML'
    )

# --- Prediction Purchase Flow (New Conversation Handlers) ---

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

    context.user_data["selected_plan_key"] = plan_key
    update_user_field(user_id, "prediction_plan", plan_key)
    update_user_field(user_id, "prediction_status", "PENDING_UTR")
    
    payment_message = (
        f"✅ You selected: {plan['name']} - ({plan['price']})\n\n"
        "Please complete the payment to the displayed QR code/UPI ID and click 'Sended 🟢'.\n\n"
        "**NOTE:** This is a demonstration. Use a real payment method in a production bot."
    )
    
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Sended 🟢", callback_data="payment_sent")]]
    )
    
    try:
         await query.edit_message_text("Payment instructions are being sent via a new message...")
    except:
         pass 

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
            text=f"🚨 **An error occurred** while fetching payment details. Please contact support.",
        )
        return ConversationHandler.END 


    return WAITING_FOR_PAYMENT_PROOF


async def payment_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: User confirms payment, asks for UTR."""
    query = update.callback_query
    await query.answer()
    
    try:
        await query.edit_message_caption(
            caption="Thank you for confirming! Now, please **reply to this message** with your **UTR (Unique Transaction Reference) Number** so the admin can verify your payment.",
            reply_markup=None,
        )
    except Exception:
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
    plan_key = user_data.get('prediction_plan') 

    if not plan_key or plan_key not in PREDICTION_PLANS:
        await update.message.reply_text("Error: Plan data missing. Please try /start again.")
        return ConversationHandler.END
    
    update_user_field(user_id, "last_utr", utr)
    update_user_field(user_id, "prediction_status", "ADMIN_REVIEW")
    
    # 1. Inform User 
    await update.message.reply_text(
        f"**Payment Notification Received!**\n\n"
        f"Your payment (UTR: `{utr}`) is now under review by the administrator.\n"
        "You will receive a notification once your access is approved.",
        parse_mode='Markdown'
    )
    
    # 2. Alert Admin
    admin_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Accept Request", callback_data=f"admin_accept_{user_id}_{plan_key}"), # Add plan key to data
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

# --- Admin Panel Handlers (New) ---

async def admin_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicks ACCEPT."""
    query = update.callback_query
    await query.answer("Granting access...")

    try:
        parts = query.data.split("_")
        
        # Check if the data has the minimum required structure: "admin_accept_ID_KEY"
        if len(parts) < 4:
            raise ValueError("Callback data too short.")
            
        # The user ID is guaranteed to be the third element (index 2)
        buyer_id_str = parts[2]
        
        # The plan key is everything from the fourth element (index 3) onwards,
        # joined back together by underscores.
        plan_key = "_".join(parts[3:]) 
        
    except Exception:
        # Fallback for corrupted data
        await query.edit_message_text("Error: Could not parse callback data. Button data corrupted.")
        return ConversationHandler.END


    buyer_id = int(buyer_id_str)

    if not plan_key or plan_key not in PREDICTION_PLANS:
        # This is where your error came from, because plan_key was 'day' not '7_day'
        await query.edit_message_text(f"Error: Could not find valid plan for user `{buyer_id}` (key: {plan_key}). User status reset.")
        update_user_field(buyer_id, "prediction_status", "NONE")
        return ConversationHandler.END
        
    await grant_prediction_access(buyer_id, plan_key, 'Paid Access', context)
    
    plan = PREDICTION_PLANS[plan_key]
    await query.edit_message_text(
        f"  Access granted to user `{buyer_id}` for **{plan['name']}**."
    )
    return ConversationHandler.END
    
async def admin_reject_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicks REJECT."""
    query = update.callback_query
    await query.answer("Rejecting request...")

    buyer_id = int(query.data.split("_")[-1])
    
    update_user_field(buyer_id, "prediction_status", "NONE")
    update_user_field(buyer_id, "prediction_plan", None)
    
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="❌ **Payment Verification Failed**\n\n"
                 "The UTR provided could not be verified. Your request has been rejected. "
                 "Please check your payment and try again via /start."
        )
    except Exception as e:
        logger.warning(f"Could not message rejected user {buyer_id}: {e}")
        
    await query.edit_message_text(f"❌ Request for user `{buyer_id}` has been rejected and user was notified.")
    return ConversationHandler.END

# --- JobQueue Callback Function ---

async def notify_subscription_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job function that runs when the subscription expires."""
    job_data = context.job.data
    buyer_id = job_data["buyer_id"]
    
    # Reset state variables on expiry
    update_user_field(buyer_id, "prediction_status", "NONE")
    update_user_field(buyer_id, "expiry_timestamp", 0)
    update_user_field(buyer_id, "prediction_plan", None)
    update_user_field(buyer_id, "current_level", 1) 
    update_user_field(buyer_id, "current_prediction", random.choice(['Small', 'Big'])) 
    update_user_field(buyer_id, "history", []) 
    update_user_field(buyer_id, "current_pattern_name", "Random (Reset)") 
    
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="🛑 **SUBSCRIPTION EXPIRED!** 🛑\n\n"
                 "Your exclusive access has ended. Please use /start to view new subscription options.",
        )
    except Exception as e:
        logger.error(f"Failed to send EXPIRY notification to user {buyer_id}: {e}")

# --- Strategy Delivery Flow (New Conversation Handlers) ---

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for active users to request a prediction."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    user_data = get_user_data(user_id)
    
    if is_subscription_active(user_data):
        time_left_str = get_remaining_time_str(user_data["expiry_timestamp"])
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🟢 **Access Active!** Remaining: {time_left_str}\n\n{PREDICTION_PROMPT}",
            parse_mode="Markdown",
        )
        return WAITING_FOR_PERIOD_NUMBER
        
    else:
        # Access denied/expired logic
        await context.bot.send_message(
             chat_id=user_id,
             text="❌ **Access Denied/Expired.** Please use /start to renew your prediction package.",
             reply_markup=get_main_keyboard(user_data)
        )
        return ConversationHandler.END
        
async def receive_period_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    period_number_str = update.message.text.strip()
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    # 🛑 Re-check subscription status
    if not is_subscription_active(user_data):
        await update.message.reply_text(
            "❌ **Access Denied/Expired.** Please use /start to renew your prediction package.",
            reply_markup=get_main_keyboard(user_data)
        )
        return ConversationHandler.END
        
    try:
        # Check if the input is a number
        if not re.match(r'^\d+$', period_number_str):
             raise ValueError
        period_number = period_number_str

    except ValueError:
        await update.message.reply_text("⚠️ Invalid Period Number. Please send a valid number.")
        return WAITING_FOR_PERIOD_NUMBER
        
    # --- Prediction Logic ---
    current_level = user_data.get("current_level", 1)
    prediction = user_data.get("current_prediction", random.choice(['Small', 'Big'])) 
    pattern_name = user_data.get("current_pattern_name", "Analyzing...")
    bet_unit = get_bet_unit(current_level)
    
    # Store the period number temporarily (if needed for tracking, though not strictly required by the logic)
    update_user_field(user_id, "last_game_id", period_number)
    
    prediction_type = "🚨 SURESHOT BET (Max Level Reached) 🚨\n\n" if current_level >= MAX_LEVEL else ""
        
    response_message = (
        f"{prediction_type}"
        f"⏳ **Strategy for Period {period_number}:**\n\n"
        f"Period Number → `{period_number}`\n"
        f"Bet On → **{prediction}**\n"
        f"Bet Unit → **Level {current_level}** ({bet_unit} Units)\n"
        f"Tracked Pattern → *{pattern_name}*\n"
        f"Note → *Please report the outcome with the buttons below.*"
    )
    
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
    
    return WAITING_FOR_FEEDBACK


async def handle_prediction_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles WIN/LOSS feedback, updates state, and prompts for next period number."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_name = query.from_user.full_name 
    
    feedback = query.data.split("_")[-1]  # 'win' or 'loss'
    user_data = get_user_data(user_id)
    current_level = user_data.get("current_level", 1)
    
    # --- 1. Update Martingale Level (Tracks consecutive losses) ---
    if feedback == "win":
        new_level = 1
        update_user_field(user_id, "current_level", new_level)
        level_message = "✅ Great! Sequence reset to Level 1."
        
    elif feedback == "loss":
        if current_level < MAX_LEVEL:
            new_level = current_level + 1
            update_user_field(user_id, "current_level", new_level)
            level_message = f"📉 Loss. Sequence advanced to **Level {new_level}**."
        else:
            new_level = MAX_LEVEL
            level_message = f"⚠️ **MAX LEVEL REACHED ({MAX_LEVEL})**."
            
            admin_loss_message = (
                "🚨 ALERT 🚨\n\n"
                f"User: [{user_name}](tg://user?id={user_id})\n" 
                f"User ID: `{user_id}`\n"
                f"**MAX LEVEL CROSSED** for the user. Monitor closely."
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_loss_message, parse_mode="Markdown")

    # --- 2. Generate Next Prediction and Update State (History/Pattern) ---
    # The new logic implements the user's specific rules: Repeat on Win, Opposite on Loss, special check on 3rd loss.
    new_prediction = generate_new_prediction(user_id, feedback)
    
    new_user_data = get_user_data(user_id) 
    new_pattern_name = new_user_data.get("current_pattern_name", "Analyzing...")
    new_bet_unit = get_bet_unit(new_level)
    
    # --- 3. Edit the feedback message and prompt for the next period number ---
    response_message = (
        f"You recorded a **{feedback.upper()}** for the last prediction. {level_message}\n\n"
        f"➡️ **NEXT SUGGESTED STRATEGY**\n"
        f"Bet On → **{new_prediction}**\n"
        f"Bet Unit → **Level {new_level}** ({new_bet_unit} Units)\n"
        f"Tracked Pattern → *{new_pattern_name}*\n\n"
        f"{PREDICTION_PROMPT}"
    )

    await query.edit_message_text(response_message, parse_mode="Markdown")
    
    return WAITING_FOR_PERIOD_NUMBER
    
async def show_subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Informs the user about their current payment/review status."""
    query = update.callback_query
    await query.answer(cache_time=1) 

    user_data = get_user_data(query.from_user.id)
    current_status = user_data.get("prediction_status", "NONE")

    if current_status == "ADMIN_REVIEW":
        await query.answer("Your payment is currently being reviewed by the admin. Please wait for the approval notification.", show_alert=True)
    elif current_status == "PENDING_UTR":
        await query.answer("You need to enter your UTR number to proceed with payment verification.", show_alert=True)
    elif current_status == "NONE":
         await query.answer("You do not have an active request or subscription. Please purchase a plan.", show_alert=True)
    else:
        await query.answer(f"Status: {current_status}", show_alert=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "An unexpected bot error occurred. Please try again. Use /start to refresh.",
            parse_mode='HTML'
        )

async def set_up_commands(application: Application):
    """Sets the list of commands for the bot's menu (simplified)."""
    commands = [
        BotCommand("start", "🏠 Main Menu & Status"),
        BotCommand("reset", "🔄 Reset Level to 1 & New Strategy"),
        BotCommand("help", "❓ Help & Command List"),
        BotCommand("cancel", "🛑 Cancel ongoing process"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully.")

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).post_init(set_up_commands).build()

    # 1. Main Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", handle_reset))
    application.add_handler(CommandHandler("cancel", cancel))

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
        fallbacks=[CommandHandler("start", start_command), CommandHandler("cancel", cancel)], 
        allow_reentry=True,
    )
    application.add_handler(prediction_flow_handler)

    # 3. Prediction REQUEST Conversation Handler (for active users)
    prediction_request_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={
            WAITING_FOR_PERIOD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_period_number),
            ],
            WAITING_FOR_FEEDBACK: [
                   CallbackQueryHandler(handle_prediction_feedback, pattern="^feedback_"),
            ],
        },
        fallbacks=[CommandHandler("start", start_command), CommandHandler("cancel", cancel)], 
        allow_reentry=True,
    )
    application.add_handler(prediction_request_handler) 
    
    # 4. Admin Approval Handler (only for the admin)
    application.add_handler(
        CallbackQueryHandler(admin_accept_request, pattern="^admin_accept_")
    )
    application.add_handler(
        CallbackQueryHandler(admin_reject_request, pattern="^admin_reject_")
    )
    
    # 5. Final Status Handler
    application.add_handler(CallbackQueryHandler(show_subscription_status, pattern="^subscription_status$"))

    # Register the error handler
    application.add_error_handler(error_handler)

    # Run the bot
    print("Bot is running... Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()