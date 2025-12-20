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

# --- Configuration and Environment Setup ---
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_DB_CONNECTION_STRING")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6239774927")) 

REGISTER_LINK = "https://t.me/+pR0EE-BzatNjZjNl" 
PAYMENT_IMAGE_URL = "https://cdn.discordapp.com/attachments/980672312225460287/1433268868255580262/Screenshot_20251029-1135273.png"
PREDICTION_PROMPT = " **Please reply to this message with the Period Number** for which you want the next prediction."

PREDICTION_PLANS = {
    "7_day": {"name": "7 Day Access", "price": "300", "duration_seconds": 604800},
    "permanent": {"name": "Permanent Access", "price": "500", "duration_seconds": 1576800000},
}

(
    SELECTING_PLAN,
    WAITING_FOR_PAYMENT_PROOF,
    WAITING_FOR_UTR,
    WAITING_FOR_PERIOD_NUMBER, 
    WAITING_FOR_FEEDBACK,
) = range(5) 

BETTING_SEQUENCE = [1, 2, 4, 8, 16, 32] 
MAX_LEVEL = len(BETTING_SEQUENCE)
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
MAX_HISTORY_LENGTH = 5 

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Database Setup ---
users_collection = None 
try:
    client = MongoClient(MONGO_URI)
    db = client.prediction_bot_db
    users_collection = db.users
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")

# --- DB Utility Functions ---

def update_user_field(user_id, field, value):
    if users_collection is None: return
    users_collection.update_one({"user_id": user_id}, {"$set": {field: value}})

def get_user_data(user_id):
    if users_collection is None: return {}
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
            "history": [], 
            "current_pattern_name": "Random (New User)", 
            "last_game_id": '100',
            "consecutive_losses": 0, #  New tracker for your logic
        }
        users_collection.insert_one(user)
    
    # Migration for existing users
    updates = {}
    if "current_level" not in user: updates["current_level"] = 1
    if "consecutive_losses" not in user: updates["consecutive_losses"] = 0
    if "history" not in user: updates["history"] = []
    
    if updates:
        users_collection.update_one({"user_id": user_id}, {"$set": updates})
        user.update(updates)

    if user.get("prediction_status") == "ACTIVE" and user.get("expiry_timestamp", 0) < time.time():
        update_user_field(user_id, "prediction_status", "NONE")
        user["prediction_status"] = "NONE"
    return user

def is_subscription_active(user_data) -> bool:
    return user_data.get("prediction_status") == "ACTIVE" and user_data.get("expiry_timestamp", 0) > time.time()

def get_remaining_time_str(expiry_timestamp: int) -> str:
    remaining_seconds = int(expiry_timestamp - time.time())
    if remaining_seconds > 1000000000: return "Permanent"
    if remaining_seconds <= 0: return "Expired"
    days = remaining_seconds // 86400
    hours = (remaining_seconds % 86400) // 3600
    minutes = (remaining_seconds % 3600) // 60
    if days > 0: return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"

# --- Logic Implementation ---

def get_bet_unit(level: int) -> int:
    return BETTING_SEQUENCE[level - 1] if 1 <= level <= MAX_LEVEL else 1

def get_next_pattern_prediction(history: list) -> tuple[Optional[str], str]:
    recent_history = history[-MAX_HISTORY_LENGTH:]
    recent_history_len = len(recent_history)
    for pattern_list, pattern_name in ALL_PATTERNS:
        pattern_len = len(pattern_list)
        if recent_history_len < pattern_len:
            if recent_history == pattern_list[:recent_history_len]:
                return pattern_list[recent_history_len], pattern_name 
        elif recent_history_len == pattern_len:
            if recent_history == pattern_list:
                return pattern_list[0], pattern_name
    return None, "Random (No Match)"

def generate_new_prediction(user_id: int, outcome: str) -> str:
    """
    MODIFIED LOGIC:
    Win -> Repeat previous result.
    1st Loss -> Opposite of previous result.
    2nd+ Loss -> Run pattern matching.
    """
    state = get_user_data(user_id) 
    current_prediction = state.get('current_prediction')
    consecutive_losses = state.get('consecutive_losses', 0)
    
    # Step 1: Track actual result and update loss counter
    if outcome == 'win':
        actual_outcome = current_prediction
        consecutive_losses = 0
    else:
        actual_outcome = 'Big' if current_prediction == 'Small' else 'Small'
        consecutive_losses += 1
        
    history = state.get('history', [])
    history.append(actual_outcome)
    if len(history) > MAX_HISTORY_LENGTH: history.pop(0)

    # Step 2: Apply specific logic
    if outcome == 'win':
        # RULE: Continue with the SAME result
        new_prediction = actual_outcome
        pattern_name = "Winning Repeat"
    else:
        if consecutive_losses == 1:
            # RULE: 1st Loss -> Opposite result
            new_prediction = 'Big' if current_prediction == 'Small' else 'Small'
            pattern_name = "Recovery Switch"
        else:
            # RULE: 2 or more losses -> Patterns
            pattern_prediction, p_name = get_next_pattern_prediction(history)
            if pattern_prediction:
                new_prediction = pattern_prediction
                pattern_name = f"Pattern: {p_name}"
            else:
                new_prediction = random.choice(['Small', 'Big'])
                pattern_name = "Random (Pattern Search)"

    # Step 3: DB Updates
    users_collection.update_one({"user_id": user_id}, {"$set": {
        "history": history,
        "current_prediction": new_prediction,
        "current_pattern_name": pattern_name,
        "consecutive_losses": consecutive_losses
    }})
    return new_prediction

# --- Rest of the bot handlers (Standard Workflow) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    keyboard = get_main_keyboard(user_data) 
    msg = " Welcome! Purchase a package to get Martingale-based predictions."
    if update.message: await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='HTML')
    elif update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=keyboard, parse_mode='HTML')
    return ConversationHandler.END

def get_main_keyboard(user_data):
    buttons = [[InlineKeyboardButton(" Telegram Group", url=REGISTER_LINK)]]
    if is_subscription_active(user_data):
        buttons.append([InlineKeyboardButton(f" Get Strategy ({get_remaining_time_str(user_data['expiry_timestamp'])})", callback_data="show_prediction")])
    elif user_data.get("prediction_status") in ["ADMIN_REVIEW", "PENDING_UTR"]:
        buttons.append([InlineKeyboardButton(" Status: Under Review", callback_data="subscription_status")])
    else:
        buttons.append([InlineKeyboardButton(" Strategy Packages", callback_data="start_prediction_flow")])
    return InlineKeyboardMarkup(buttons)

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_data = get_user_data(query.from_user.id)
    if is_subscription_active(user_data):
        await context.bot.send_message(chat_id=query.from_user.id, text=f" **Access Active!**\n\n{PREDICTION_PROMPT}", parse_mode="Markdown")
        return WAITING_FOR_PERIOD_NUMBER
    return ConversationHandler.END

async def receive_period_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if not is_subscription_active(user_data): return ConversationHandler.END
    
    try:
        period = int(update.message.text.strip())
    except:
        await update.message.reply_text(" Invalid Period Number.")
        return WAITING_FOR_PERIOD_NUMBER

    lvl = user_data.get("current_level", 1)
    pred = user_data.get("current_prediction")
    unit = get_bet_unit(lvl)
    
    msg = (f" **Strategy for Period {period}:**\n\n"
           f"Bet On  **{pred}**\n"
           f"Bet Unit  **Level {lvl}** ({unit} Units)\n"
           f"Strategy  *{user_data.get('current_pattern_name')}*")
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(" WIN", callback_data="feedback_win"), 
                                 InlineKeyboardButton(" LOSS", callback_data="feedback_loss")]])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    return WAITING_FOR_FEEDBACK

async def handle_prediction_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    feedback = query.data.split("_")[-1] # 'win' or 'loss'
    user_data = get_user_data(user_id)
    
    # 1. Level Logic
    current_lvl = user_data.get("current_level", 1)
    if feedback == "win":
        new_lvl = 1
    else:
        new_lvl = min(current_lvl + 1, MAX_LEVEL)
        if current_lvl == MAX_LEVEL:
            await context.bot.send_message(ADMIN_ID, f" **User {user_id} hit Max Level Loss.**")

    update_user_field(user_id, "current_level", new_lvl)
    
    # 2. Logic Trigger
    new_pred = generate_new_prediction(user_id, feedback)
    
    await query.edit_message_text(f"Result recorded: **{feedback.upper()}**.\n\n"
                                  f" **Next Prediction:** **{new_pred}** (Lvl {new_lvl})\n\n"
                                  f"{PREDICTION_PROMPT}", parse_mode="Markdown")
    return WAITING_FOR_PERIOD_NUMBER

# --- Boilerplate Logic (Admin, Reset, Main) ---

async def grant_prediction_access(user_id, plan_key, reason, context):
    plan = PREDICTION_PLANS[plan_key]
    expiry = time.time() + plan["duration_seconds"]
    update_user_field(user_id, "prediction_status", "ACTIVE")
    update_user_field(user_id, "expiry_timestamp", int(expiry))
    update_user_field(user_id, "prediction_plan", plan_key)
    await context.bot.send_message(user_id, f" Access Granted: {plan['name']}")

async def admin_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    buyer_id, plan_key = int(parts[2]), "_".join(parts[3:])
    await grant_prediction_access(buyer_id, plan_key, "Paid", context)
    await query.edit_message_text(f" Access granted to {buyer_id}")

async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_field(user_id, "current_level", 1)
    update_user_field(user_id, "consecutive_losses", 0)
    update_user_field(user_id, "history", [])
    update_user_field(user_id, "current_prediction", random.choice(['Small', 'Big']))
    await update.message.reply_text(" Bot reset to Level 1.")

async def start_prediction_flow(update, context):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{p['name']} - {p['price']}", callback_data=f"select_plan_{k}")] for k, p in PREDICTION_PLANS.items()])
    await update.callback_query.edit_message_text("Select a package:", reply_markup=kb)
    return SELECTING_PLAN

async def select_plan(update, context):
    query = update.callback_query
    plan_key = query.data.replace("select_plan_", "")
    update_user_field(query.from_user.id, "prediction_plan", plan_key)
    await query.edit_message_text("Please complete payment to the QR and click 'Sended '")
    await context.bot.send_photo(query.from_user.id, photo=PAYMENT_IMAGE_URL, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sended ", callback_data="payment_sent")]]))
    return WAITING_FOR_PAYMENT_PROOF

async def payment_sent(update, context):
    await update.callback_query.message.reply_text("Now send your UTR number:")
    return WAITING_FOR_UTR

async def receive_utr(update, context):
    user_id = update.effective_user.id
    utr = update.message.text
    update_user_field(user_id, "prediction_status", "ADMIN_REVIEW")
    await update.message.reply_text("Payment under review.")
    await context.bot.send_message(ADMIN_ID, f"New Payment: User {user_id}, UTR: {utr}", 
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Accept", callback_data=f"admin_accept_{user_id}_7_day")]])) # Simplification
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reset", handle_reset))
    
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_prediction_flow, pattern="^start_prediction_flow$")],
        states={SELECTING_PLAN: [CallbackQueryHandler(select_plan, pattern="^select_plan_")],
                WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(payment_sent, pattern="^payment_sent$")],
                WAITING_FOR_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]},
        fallbacks=[CommandHandler("start", start_command)]))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={WAITING_FOR_PERIOD_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_period_number)],
                WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_prediction_feedback, pattern="^feedback_")]},
        fallbacks=[CommandHandler("start", start_command)]))
    
    app.add_handler(CallbackQueryHandler(admin_accept_request, pattern="^admin_accept_"))
    app.run_polling()

if __name__ == "__main__":
    main()
    