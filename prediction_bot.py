import logging
import os
import time
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
    # 🆕 NEW STATE FOR WIN/LOSS FEEDBACK
    WAITING_FOR_FEEDBACK,
) = range(5) # Changed range from 4 to 5

# --- Constants ---
REGISTER_LINK = "https://example.com/register"
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png?ex=69041327&is=6902c1a7&hm=517ecf60348db21c748797801a6bcdc08336d7020d3bf41c889abe22ba4a4d26&"
# ⚠️ UPDATED CONSTANT TO BE THE PROMPT
PREDICTION_PROMPT = "➡️ **Please reply to this message with the Period Number** for which you want the next prediction."

PREDICTION_PLANS = {
    # Duration is in seconds for easy calculation
    "1_hour": {"name": "1 Hour Access", "price": "40₹", "duration_seconds": 3600},
    "1_day": {"name": "1 Day Access", "price": "150₹", "duration_seconds": 86400},
    "7_day": {"name": "7 Day Access", "price": "500₹", "duration_seconds": 604800},
}

# 🆕 NEW CONSTANT: Original Prediction Pattern (Used when loss_streak = 0)
PREDICTION_PATTERN = ["Small", "Big", "Big", "Small"]

# 🆕 NEW CONSTANT: Loss Recovery Pattern (Used when loss_streak > 0)
LOSS_RECOVERY_PATTERN = ["Big", "Small"]


# --- Utility Functions ---

def get_user_data(user_id):
    """Retrieves user data from MongoDB or creates a new entry if not found."""
    # FIX APPLIED HERE (The corrected check for Collection object)
    if users_collection is None: 
        logger.warning("Database connection unavailable. Returning empty user data.")
        return {}
        
    user = users_collection.find_one({"user_id": user_id})
    if user is None:
        user = {
            "user_id": user_id,
            "username": None,
            # NONE: No sub | PENDING_UTR: Waiting for UTR | ADMIN_REVIEW: Waiting for admin | ACTIVE: Subscription active
            "prediction_status": "NONE", 
            "prediction_plan": None,
            "expiry_timestamp": 0, # Timestamp when subscription ends (0 if none)
            # 🆕 NEW: Loss tracking field
            "loss_streak": 0, # Consecutive losses
        }
        users_collection.insert_one(user)
    # 🆕 Ensure loss_streak exists for existing users
    elif "loss_streak" not in user:
        user["loss_streak"] = 0
        update_user_field(user_id, "loss_streak", 0) # Update DB
        
    return user

def update_user_field(user_id, field, value):
    """Updates a single field for a user in MongoDB."""
    # FIX APPLIED HERE (The corrected check for Collection object)
    if users_collection is None: 
        logger.warning(f"Cannot update DB for user {user_id}. Connection unavailable.")
        return
        
    users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def is_subscription_active(user_data) -> bool:
    """Checks if the subscription is currently active based on expiry time."""
    # A user is active if status is 'ACTIVE' AND the expiry time is in the future
    if user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time():
        return True
    return False

def get_remaining_time_str(expiry_timestamp: int) -> str:
    """Formats the remaining time string."""
    remaining_seconds = int(expiry_timestamp - time.time())
    if remaining_seconds <= 0:
        return "Expired"
        
    days = remaining_seconds // 86400
    hours = (remaining_seconds % 86400) // 3600
    minutes = (remaining_seconds % 3600) // 60
    
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def get_prediction_keyboard(user_data):
    """Generates the main keyboard based on user status."""
    status = user_data.get("prediction_status")
    expiry_timestamp = user_data.get("expiry_timestamp", 0)
    
    buttons = [
        [
            InlineKeyboardButton("🔗 Register Link", url=REGISTER_LINK),
        ]
    ]
    
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
    user_data = get_user_data(user_id)
    
    # Update username if it changed
    if user_data.get("username") != username:
        update_user_field(user_id, "username", username)
    
    # Check if a subscription just expired and clean up status
    if user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user_data["prediction_status"] = "NONE" # Update local data for this run
        
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
        # This handles the 'start' pattern callback if used to refresh the menu
        try:
            await update.callback_query.edit_message_text(initial_message, reply_markup=keyboard)
        except Exception:
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
    await context.bot.send_photo(
        chat_id=user_id,
        photo=PAYMENT_IMAGE_URL,
        caption=payment_message,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    return WAITING_FOR_PAYMENT_PROOF


async def payment_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: User confirms payment, asks for UTR."""
    query = update.callback_query
    await query.answer()
    
    try:
        await query.edit_message_caption(
            caption="Thank you for confirming! Now, please **reply to this message** with your **UTR (Unique Transaction Reference) Number** so the admin can verify your payment.",
            reply_markup=None, # Remove the 'Sended' button
        )
    except:
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
    Admin clicks ACCEPT. Calculates expiry time, sets status to ACTIVE, and schedules expiry job.
    """
    query = update.callback_query
    await query.answer("Granting access...")

    # Extract the user ID of the buyer from callback data
    buyer_id = int(query.data.split("_")[-1])
    
    # 1. Get user data to find the purchased plan
    buyer_data = get_user_data(buyer_id)
    plan_key = buyer_data.get("prediction_plan")

    if not plan_key or plan_key not in PREDICTION_PLANS:
        await query.edit_message_text(f"Error: Could not find valid plan for user `{buyer_id}`. Rejected.")
        update_user_field(buyer_id, "prediction_status", "NONE")
        return ConversationHandler.END
        
    plan = PREDICTION_PLANS[plan_key]
    duration_seconds = plan["duration_seconds"]
    
    # 2. Calculate Expiry Time
    expiry_timestamp = time.time() + duration_seconds
    
    # 3. Update User Status in DB
    update_user_field(buyer_id, "prediction_status", "ACTIVE")
    update_user_field(buyer_id, "expiry_timestamp", int(expiry_timestamp))
    
    # 4. Schedule the Expiry Job (to notify user when time is up)
    # Ensure any previous expiry job for this user is removed
    job_name = f"pred_expiry_{buyer_id}"
    current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
        
    context.application.job_queue.run_once(
        notify_subscription_expired,
        duration_seconds, # run in the plan's duration time
        data={"buyer_id": buyer_id},
        name=job_name,
    )
    
    # 5. Inform Admin
    time_left_str = get_remaining_time_str(int(expiry_timestamp))
    await query.edit_message_text(
        f"✅ Access granted to user `{buyer_id}` for **{plan['name']}**.\n"
        f"Subscription expires in: {time_left_str}."
    )
    
    # 6. Inform User (Buyer)
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="🟢 Payment Approved! Subscription Activated! 🟢\n\n"
                 f"You now have {plan['name']} access.\n"
                 "Please use the 'Get Prediction' button in your main menu (/start) to receive your exclusive content repeatedly until your access expires.",
        )
    except Exception as e:
        logger.warning(f"Could not message buyer {buyer_id}: {e}")

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
    # Reset loss streak on expiry
    update_user_field(buyer_id, "loss_streak", 0) 
    
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
 
        # 3. MOVE TO THE NEW STATE
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
        
        await query.edit_message_reply_markup(get_prediction_keyboard(user_data))
        
        # End the conversation if access is denied
        return ConversationHandler.END


async def receive_period_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the period number and generates the pattern-based prediction."""
    period_number_str = update.message.text.strip()
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    loss_streak = user_data.get("loss_streak", 0)
    
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
        
    # --- Prediction Logic based on Loss Streak ---
    
    current_pattern = PREDICTION_PATTERN
    prediction_type = ""
    
    if loss_streak == 0:
        # 1. Original Pattern: PREDICTION_PATTERN
        current_pattern = PREDICTION_PATTERN
        
    elif loss_streak >= 4:
        # 2. SURESHOT Pattern (Loss Recovery Pattern)
        current_pattern = LOSS_RECOVERY_PATTERN
        prediction_type = "🚨 SURESHOT BET 🚨\n\n"
        # Reset streak AFTER delivering the sureshot prediction
        update_user_field(user_id, "loss_streak", 0)
        
    else: # loss_streak is 1, 2, or 3
        # 3. Loss Recovery Pattern (BIG, SMALL)
        current_pattern = LOSS_RECOVERY_PATTERN
        prediction_type = f"💸 Recovery Stage ({loss_streak}/4) \n\n"
        
    # Index calculation:
    # Original pattern (length 4): (period_number - 1) % 4
    # Recovery pattern (length 2): (period_number - 1) % 2
    pattern_index = (period_number - 1) % len(current_pattern)
    prediction = current_pattern[pattern_index]
    
    # --- Response Generation ---
    response_message = (
        f"{prediction_type}"
        f"⏳ **Prediction for Period {period_number}:**\n\n"
        f"Period Number → `{period_number}`\n"
        f"Bet On → **{prediction}**\n"
        f"Note → *Keep lvl 5*"
    )
    
    # 🆕 NEW: WIN/LOSS Feedback Keyboard
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
    
    # 🆕 NEW: Transition to the state that awaits WIN/LOSS feedback
    return WAITING_FOR_FEEDBACK


# --- New Handler for WIN/LOSS feedback ---

async def handle_prediction_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user clicking WIN or LOSS and updates the loss streak."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    feedback = query.data.split("_")[-1]  # 'win' or 'loss'
    
    user_data = get_user_data(user_id)
    current_streak = user_data.get("loss_streak", 0)

    if feedback == "win":
        # Reset streak on a WIN
        new_streak = 0
        update_user_field(user_id, "loss_streak", 0)
        
        message = "✅ Great! The loss streak is reset. What is the next Period Number?"
        
    elif feedback == "loss":
        # Increment streak on a LOSS
        new_streak = current_streak + 1
        update_user_field(user_id, "loss_streak", new_streak)
        
        if new_streak > 4:
        	message = f"🚫⚠️ 5 LEVEL HAS CROSSED. ADMIN IS NOTIFIED & REFUND WILL BE INITIATED SOON ⚠️🚫."
       admin_loss_message = (
            "🚨 ALERT 🚨\n\n"                 
           f"User: [{user_name}](tg://user?id={user_id})\n"
           f"User ID: `{user_id}`\n"
           f"5 LEVEL HAS BEEN CROSSED FOR THE USER INTIATE THE REFUND IF POSSIBLE"
        )
        
        try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_loss_message,
            )
        
        if new_streak >= 4:
            message = f"❌ Loss streak reached {new_streak}. The next prediction will be a **SURESHOT**! Please provide the next Period Number."
        else:
            message = f"📉 Loss streak is now {new_streak}. Continuing with the recovery pattern. What is the next Period Number?"
    else:
        await query.edit_message_text("Invalid feedback received. Please use /start to refresh.")
        return ConversationHandler.END

    # Edit the feedback message and prompt for the next period number
    await query.edit_message_text(
        f"You recorded a **{feedback.upper()}** for the last prediction.\n\n{message}\n\n{PREDICTION_PROMPT}",
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
    
    # 1. Main Command Handler (Start and Subscription Status)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel)) # Added global cancel handler

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
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)], # Added cancel fallback
        allow_reentry=True,
    )
    application.add_handler(prediction_flow_handler)

    # 3. 🆕 UPDATED: Prediction REQUEST Conversation Handler to handle feedback
    prediction_request_handler = ConversationHandler(
        # Entry point is the 'Get Prediction' button
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={
            WAITING_FOR_PERIOD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_period_number),
            ],
            # 🆕 NEW STATE: Wait for WIN or LOSS button click
            WAITING_FOR_FEEDBACK: [
                CallbackQueryHandler(handle_prediction_feedback, pattern="^feedback_"),
            ],
        },
        # Allow /start or /cancel to interrupt the flow
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)], 
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

    # Start the Bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

    










