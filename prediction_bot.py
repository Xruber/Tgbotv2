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
    JobQueue,
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
try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db  # Database name
    users_collection = db.users  # Collection for user data and requests
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    # Exit or handle gracefully if DB connection is critical

# --- States for ConversationHandler ---
(
    SELECTING_PLAN,
    WAITING_FOR_PAYMENT_PROOF,
    WAITING_FOR_UTR,
    WAITING_FOR_ADMIN_TIME,
) = range(4)

# --- Constants ---
REGISTER_LINK = "https://example.com/register"
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433082788600483871/Screenshot_20251029-1135273.png?ex=690365da&is=6902145a&hm=ce70f29e49b58738d5d79f228f307c33e0fb2cccd0bc9edb6bc466a2b05db110&"
PREDICTION_MESSAGE = "🌟 **Your Exclusive Prediction is Here!** 🌟\n\nThis is the winning advice you paid for. Good luck!"

PREDICTION_PLANS = {
    "1_hour": {"name": "1 Hour Prediction", "price": "70₹", "duration_minutes": 60},
    "1_day": {"name": "1 Day Prediction", "price": "300₹", "duration_minutes": 1440},
    "7_day": {"name": "7 Day Prediction", "price": "1000₹", "duration_minutes": 10080},
}

# --- Utility Functions ---

def get_user_data(user_id):
    """Retrieves user data from MongoDB or creates a new entry if not found."""
    user = users_collection.find_one({"user_id": user_id})
    if user is None:
        user = {
            "user_id": user_id,
            "username": None,
            "prediction_status": "NONE",  # NONE, PENDING_UTR, ADMIN_REVIEW, ACCEPTED, READY
            "prediction_plan": None,
            "prediction_available_at": None,
        }
        users_collection.insert_one(user)
    return user

def update_user_field(user_id, field, value):
    """Updates a single field for a user in MongoDB."""
    users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def get_prediction_keyboard(user_status):
    """Generates the main keyboard based on user status."""
    buttons = [
        [
            InlineKeyboardButton("🔗 Register Link", url=REGISTER_LINK),
        ]
    ]
    
    if user_status == "READY":
        buttons.append([InlineKeyboardButton("✨ Get Prediction Now", callback_data="show_prediction")])
    elif user_status == "ACCEPTED":
        buttons.append([InlineKeyboardButton(f"⏳ Prediction Ready: {datetime.fromtimestamp(user_status['prediction_available_at']).strftime('%H:%M:%S')}", callback_data="show_prediction")])
    elif user_status == "ADMIN_REVIEW":
        buttons.append([InlineKeyboardButton("🔍 Prediction Status: Under Review", callback_data="prediction_status")])
    else:
        # Default Prediction Menu
        buttons.append([InlineKeyboardButton("🔮 Prediction (Paid)", callback_data="start_prediction_flow")])
    
    return InlineKeyboardMarkup(buttons)

# --- Bot Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the initial message and main menu keyboard."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    user_data = get_user_data(user_id)
    
    # Update username if it has changed
    if user_data.get("username") != username:
        update_user_field(user_id, "username", username)

    status_code = user_data.get("prediction_status")
    
    keyboard = get_prediction_keyboard(status_code)

    await update.message.reply_text(
        f"👋 Welcome, {update.effective_user.first_name}!\n\n"
        "Use the buttons below to register or start your prediction package.",
        reply_markup=keyboard,
    )
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
        "Choose your prediction package:",
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
        f"✅ You selected: **{plan['name']}** ({plan['price']})\n\n"
        "Please complete the payment to the displayed QR code/UPI ID.\n\n"
        "**NOTE:** This is a demonstration. Use a real payment method in a production bot."
    )
    
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Sended 🟢", callback_data="payment_sent")]]
    )

    await context.bot.send_photo(
        chat_id=user_id,
        photo=PAYMENT_IMAGE_URL,
        caption=payment_message,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    # Clean up the previous message
    await query.edit_message_text("Payment instructions sent to chat.")
    
    return WAITING_FOR_PAYMENT_PROOF


async def payment_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: User confirms payment, asks for UTR."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "Thank you for confirming! Now, please reply with your **UTR (Unique Transaction Reference) Number** so the admin can verify your payment."
    )
    
    return WAITING_FOR_UTR


async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4: User sends UTR, payment successful message, and alerts admin."""
    utr = update.message.text
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    
    # Store UTR and update status
    update_user_field(user_id, "last_utr", utr)
    update_user_field(user_id, "prediction_status", "ADMIN_REVIEW")
    
    # 1. Inform User
    await update.message.reply_text(
        "**Payment Sucessful!**\n\n"
        "Your payment (UTR: `{utr}`) is now under review.\n"
        "You will receive a notification once your prediction is approved and ready. This typically happens within 1-2 hours."
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
        f"Plan: **{PREDICTION_PLANS[context.user_data.get('selected_plan_key')]['name']}**\n"
        f"UTR Provided: `{utr}`\n\n"
        "Please check your bank records and confirm the payment."
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
        await update.message.reply_text("ERROR: Could not notify admin. Please contact support manually.")
    
    # End the UTR conversation
    return ConversationHandler.END

# --- Admin Panel Handlers ---

async def admin_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicks ACCEPT. Asks for delay time."""
    query = update.callback_query
    await query.answer("Accepting request...")

    # Extract the user ID of the buyer from callback data
    buyer_id = int(query.data.split("_")[-1])
    
    # Store the buyer_id for the next conversation step
    context.user_data["current_buyer_id"] = buyer_id
    
    await query.edit_message_text(
        f"✅ Payment accepted for user `{buyer_id}`.\n\n"
        "**Now, please enter the prediction delay in seconds** "
        "(e.g., enter `3600` for 1 hour, or `10` for testing):"
    )
    
    return WAITING_FOR_ADMIN_TIME

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
    return ConversationHandler.END


async def set_delay_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin enters delay time, and the prediction job is scheduled."""
    try:
        delay_seconds = int(update.message.text.strip())
        if delay_seconds <= 0:
            raise ValueError("Time must be positive.")
    except ValueError:
        await update.message.reply_text("Invalid time. Please enter a valid number of seconds (e.g., `600`):")
        return WAITING_FOR_ADMIN_TIME
    
    buyer_id = context.user_data.get("current_buyer_id")
    if not buyer_id:
        await update.message.reply_text("Error: Buyer ID not found. Please restart the admin process.")
        return ConversationHandler.END
    
    # Schedule the job
    context.job_queue.run_once(
        send_prediction_ready_notification,
        delay_seconds,
        data={"buyer_id": buyer_id, "delay": delay_seconds},
        name=f"pred_ready_{buyer_id}",
        chat_id=buyer_id,
    )
    
    # Calculate ready time
    ready_time = datetime.now() + timedelta(seconds=delay_seconds)
    
    # Update user status in DB
    update_user_field(buyer_id, "prediction_status", "ACCEPTED")
    update_user_field(buyer_id, "prediction_available_at", int(ready_time.timestamp()))
    
    # Inform Admin
    await update.message.reply_text(
        f"⏰ Prediction for user `{buyer_id}` scheduled!\n"
        f"Delivery time: **{delay_seconds} seconds**.\n"
        f"User will be notified at: **{ready_time.strftime('%Y-%m-%d %H:%M:%S')}**."
    )
    
    # Inform User (Buyer)
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="🟢 **Payment Success & Prediction Scheduled!** 🟢\n\n"
                 "The admin has approved your payment. Your prediction will be ready to view in "
                 f"**{delay_seconds} seconds** (around {ready_time.strftime('%H:%M:%S')}).\n"
                 "You will receive a notification when the time is up, and the 'Prediction' button on your main menu will become active.",
        )
    except Exception as e:
        logger.warning(f"Could not message buyer {buyer_id}: {e}")

    # End the admin conversation
    return ConversationHandler.END

# --- JobQueue Callback Function ---

async def send_prediction_ready_notification(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job function that runs after the delay to mark the prediction as ready."""
    job_data = context.job.data
    buyer_id = job_data["buyer_id"]
    
    # Set status to READY
    update_user_field(buyer_id, "prediction_status", "READY")
    
    # Send final notification to user
    try:
        await context.bot.send_message(
            chat_id=buyer_id,
            text="✨ **PREDICTION IS READY!** ✨\n\n"
                 "Your wait is over! Please click the 'Get Prediction Now' button in the main menu to view your content. /start",
            reply_markup=get_prediction_keyboard("READY"),
        )
    except Exception as e:
        logger.error(f"Failed to send READY notification to user {buyer_id}: {e}")

# --- Final Prediction Delivery ---

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delivers the prediction message if the user is in the 'READY' state."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    user_data = get_user_data(user_id)
    
    if user_data.get("prediction_status") == "READY":
        # Send the prediction message
        await query.edit_message_text(
            text=PREDICTION_MESSAGE,
            parse_mode="Markdown",
            reply_markup=get_prediction_keyboard("NONE") # Show the default menu again
        )
        # Reset the user's status after they receive the prediction
        update_user_field(user_id, "prediction_status", "NONE")
        update_user_field(user_id, "prediction_available_at", None)
        update_user_field(user_id, "prediction_plan", None)
    else:
        # If not READY, show status
        current_status = user_data.get("prediction_status", "NONE")
        if current_status == "ACCEPTED" and user_data.get("prediction_available_at"):
            # Calculate remaining time
            available_at = datetime.fromtimestamp(user_data["prediction_available_at"])
            remaining_time = available_at - datetime.now()
            
            if remaining_time.total_seconds() > 0:
                # Still waiting
                hours, remainder = divmod(int(remaining_time.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                time_left_str = f"{hours}h {minutes}m {seconds}s"
                
                await query.answer(f"Prediction is still scheduled! Remaining time: {time_left_str}", show_alert=True)
            else:
                # Should have been marked ready, force update status
                update_user_field(user_id, "prediction_status", "READY")
                await query.answer("It looks like your prediction is ready! Please tap the button again.", show_alert=True)
                await query.edit_message_reply_markup(get_prediction_keyboard("READY"))
                
        elif current_status == "ADMIN_REVIEW":
             await query.answer("Your payment is currently being reviewed by the admin. Please wait for the approval notification.", show_alert=True)
        else:
             await query.answer("You must purchase a prediction plan first to view content.", show_alert=True)
             await query.edit_message_reply_markup(get_prediction_keyboard(current_status))


# --- Main Application Setup ---

def main() -> None:
    """Run the bot."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 1. Main Command Handler
    application.add_handler(CommandHandler("start", start))

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
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )
    application.add_handler(prediction_flow_handler)
    
    # 3. Admin Approval Conversation Handler (only for the admin)
    admin_approval_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_accept_request, pattern="^admin_accept_"),
            CallbackQueryHandler(admin_reject_request, pattern="^admin_reject_"),
        ],
        states={
            WAITING_FOR_ADMIN_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID), set_delay_time),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        # The admin must be the only one who can interact with this conversation
        # This is enforced by filters.User(ADMIN_ID) in the WAITING_FOR_ADMIN_TIME step
        allow_reentry=False,
    )
    application.add_handler(admin_approval_handler)

    # 4. Final Prediction Viewer Handler
    application.add_handler(CallbackQueryHandler(show_prediction, pattern="^show_prediction$|^prediction_status$"))

    # Start the Bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

    
