import logging
import time
import random
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    CallbackQueryHandler, filters, ConversationHandler
)

# Import from other files
from config import BOT_TOKEN, ADMIN_ID, REGISTER_LINK, PAYMENT_IMAGE_URL, PREDICTION_PROMPT, PREDICTION_PLANS, MAX_LEVEL
from database import get_user_data, update_user_field, is_subscription_active, get_remaining_time_str
from prediction_engine import process_prediction_request, get_bet_unit

# States
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 WAITING_FOR_PERIOD_NUMBER, WAITING_FOR_FEEDBACK) = range(5)

logger = logging.getLogger(__name__)

# --- Helper: Grant Access ---
async def grant_prediction_access(user_id: int, plan_key: str, context: ContextTypes.DEFAULT_TYPE):
    plan = PREDICTION_PLANS.get(plan_key)
    if not plan: return
    
    expiry = time.time() + plan["duration_seconds"]
    update_user_field(user_id, "prediction_status", "ACTIVE")
    update_user_field(user_id, "expiry_timestamp", int(expiry))
    update_user_field(user_id, "prediction_plan", plan_key)
    
    # Schedule Expiry Job
    job_name = f"pred_expiry_{user_id}"
    current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs: job.schedule_removal()
    
    if plan_key != "permanent":
        context.application.job_queue.run_once(notify_expiry, plan["duration_seconds"], data={"buyer_id": user_id}, name=job_name)

    await context.bot.send_message(user_id, f"🟢 **Access Granted!**\nPlan: {plan['name']}\nMode: V2 (Default)")

async def notify_expiry(context: ContextTypes.DEFAULT_TYPE):
    uid = context.job.data["buyer_id"]
    update_user_field(uid, "prediction_status", "NONE")
    await context.bot.send_message(uid, "🛑 **Subscription Expired.** Use /start to renew.")

# --- SWITCH COMMAND (New) ---
async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows active users to switch between V1 and V2 logic."""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    if not is_subscription_active(user_data):
        await update.message.reply_text("❌ You need an active subscription to use this command.")
        return

    current_mode = user_data.get("prediction_mode", "V2")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅ ' if current_mode == 'V1' else ''}V1: Original", callback_data="set_mode_V1")],
        [InlineKeyboardButton(f"{'✅ ' if current_mode == 'V2' else ''}V2: Streak/Switch", callback_data="set_mode_V2")]
    ])
    
    await update.message.reply_text(
        f"⚙️ **Prediction Logic Switcher**\n\n"
        f"Current Mode: **{current_mode}**\n\n"
        "**V1 (Original):** Uses mixed probability and patterns.\n"
        "**V2 (New):** Win=Streak, Loss 1=Switch, Loss 2=Patterns.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def handle_switch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    new_mode = query.data.split("_")[-1] # V1 or V2
    update_user_field(query.from_user.id, "prediction_mode", new_mode)
    
    await query.edit_message_text(f"✅ **Success!** Logic updated to **{new_mode}**.")

# --- Standard Handlers (Start, Reset, Prediction) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user_data(update.effective_user.id)
    active = is_subscription_active(user_data)
    
    buttons = [[InlineKeyboardButton("💬 Group", url=REGISTER_LINK)]]
    if active:
        buttons.append([InlineKeyboardButton("✨ Get Strategy", callback_data="show_prediction")])
    else:
        buttons.append([InlineKeyboardButton("🔮 Buy Strategy", callback_data="start_prediction_flow")])
        
    await update.message.reply_text(
        f"👋 Welcome! Status: {'🟢 Active' if active else '🔴 Inactive'}\nUse /switch to change logic modes.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = get_user_data(query.from_user.id)
    
    if is_subscription_active(user_data):
        await context.bot.send_message(query.from_user.id, PREDICTION_PROMPT, parse_mode="Markdown")
        return WAITING_FOR_PERIOD_NUMBER
    else:
        await context.bot.send_message(query.from_user.id, "❌ Plan Expired.")
        return ConversationHandler.END

async def receive_period_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        period = int(update.message.text)
    except:
        await update.message.reply_text("⚠️ Enter a valid number.")
        return WAITING_FOR_PERIOD_NUMBER

    user_data = get_user_data(update.effective_user.id)
    pred = user_data.get("current_prediction", random.choice(['Small', 'Big']))
    lvl = user_data.get("current_level", 1)
    pat = user_data.get("current_pattern_name", "Start")
    unit = get_bet_unit(lvl)
    mode = user_data.get("prediction_mode", "V2")

    msg = (f"⏳ **Strategy (Mode: {mode})**\n\nPeriod: `{period}`\nBet: **{pred}**\n"
           f"Level: {lvl} ({unit} Units)\nPattern: {pat}")
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ WIN", callback_data="feedback_win"),
        InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss")
    ]])
    
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    outcome = query.data.split("_")[1] # win or loss
    
    user_data = get_user_data(uid)
    curr_lvl = user_data.get("current_level", 1)

    # Level Logic
    if outcome == "win":
        new_lvl = 1
    else:
        new_lvl = min(curr_lvl + 1, MAX_LEVEL)
        if new_lvl == MAX_LEVEL:
            await context.bot.send_message(ADMIN_ID, f"🚨 User {uid} hit Max Level!")

    update_user_field(uid, "current_level", new_lvl)
    
    # CALL THE ENGINE (V1 or V2 logic handled inside)
    new_pred, pattern = process_prediction_request(uid, outcome)
    
    unit = get_bet_unit(new_lvl)
    mode = user_data.get("prediction_mode", "V2")

    await query.edit_message_text(
        f"Result: **{outcome.upper()}**\n\n➡️ **Next Prediction ({mode})**\n"
        f"Bet: **{new_pred}**\nLevel: {new_lvl} ({unit} Units)\nReason: {pattern}\n\n"
        f"{PREDICTION_PROMPT}",
        parse_mode="Markdown"
    )
    return WAITING_FOR_PERIOD_NUMBER

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. /start")
    return ConversationHandler.END

# --- Buying Flow (Simplified) ---
async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["name"], callback_data=f"buy_{k}")] for k, p in PREDICTION_PLANS.items()])
    await query.edit_message_text("Select Plan:", reply_markup=kb)
    return SELECTING_PLAN

async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = query.data.split("_")[1]
    context.user_data["plan"] = key
    await context.bot.send_photo(query.from_user.id, PAYMENT_IMAGE_URL, caption="Pay & Send 'Sent'", 
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sent 🟢", callback_data="sent")]]))
    return WAITING_FOR_PAYMENT_PROOF

async def sent_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_caption("Please reply with **UTR Number**.")
    return WAITING_FOR_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    plan = context.user_data.get("plan")
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"adm_ok_{uid}_{plan}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"adm_no_{uid}")
    ]])
    await context.bot.send_message(ADMIN_ID, f"New Order!\nUser: {uid}\nUTR: {utr}\nPlan: {plan}", reply_markup=kb)
    await update.message.reply_text("Reviewing...")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    action, uid = data[1], int(data[2])
    
    if action == "ok":
        await grant_prediction_access(uid, data[3], context)
        await query.edit_message_text("Accepted.")
    else:
        await context.bot.send_message(uid, "❌ Rejected.")
        await query.edit_message_text("Rejected.")

# --- Main Run ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CallbackQueryHandler(handle_switch_callback, pattern="^set_mode_"))

    # Prediction Flow
    pred_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={
            WAITING_FOR_PERIOD_NUMBER: [MessageHandler(filters.TEXT, receive_period_number)],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^feedback_")]
        },
        fallbacks=[CommandHandler("cancel", cancel)], allow_reentry=True
    )
    
    # Buying Flow
    buy_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_buy, pattern="^start_prediction_flow$")],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(select_plan, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(sent_proof, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT, receive_utr)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(pred_handler)
    app.add_handler(buy_handler)
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_"))
    
    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()