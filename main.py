import logging
import random
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    CallbackQueryHandler, filters, ConversationHandler
)

from config import (
    BOT_TOKEN, ADMIN_ID, REGISTER_LINK, PAYMENT_IMAGE_URL, PREDICTION_PROMPT, 
    PREDICTION_PLANS, TARGET_PACKS, NUMBER_SHOT_PRICE, NUMBER_SHOT_KEY, MAX_LEVEL
)
from database import get_user_data, update_user_field, increment_user_field, get_top_referrers, is_subscription_active, get_remaining_time_str, check_and_reset_monthly_stats
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome, get_v5_logic
from target_engine import start_target_session, process_target_outcome
from api_helper import get_game_data # NEW IMPORT

# States
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, # Removed Manual Period Input
 TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP) = range(8)

logger = logging.getLogger(__name__)

# --- UTILS & COMMANDS ---
# (Keep grant_access, start_command, etc. the same as before)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Same as previous code) ...
    user_id = update.effective_user.id
    user_data = get_user_data(user_id) 
    active = is_subscription_active(user_data)
    
    buttons = [
        [InlineKeyboardButton("💬 Telegram Group", url=REGISTER_LINK)],
        [InlineKeyboardButton("🛍️ Add-on Shop (Packs)", callback_data="shop_main")]
    ]
    
    if active:
        # Changed callback to 'select_game_type' instead of 'show_prediction'
        buttons.insert(1, [InlineKeyboardButton("✨ Get Strategy", callback_data="select_game_type")])
    else:
        buttons.insert(1, [InlineKeyboardButton("🔮 Buy Strategy", callback_data="start_prediction_flow")])
        
    await update.message.reply_text(
        f"👋 Welcome! Status: {'🟢 Active' if active else '🔴 Inactive'}\n"
        "🛑 Hello I am prediction bot with 5-6levels.\n\n"
        "Use /invite to get your referral link.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END

# --- NEW: GAME SELECTION ---
async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ WINGO 30 SEC", callback_data="game_30s")],
        [InlineKeyboardButton("🕐 WINGO 1 MIN", callback_data="game_1m")]
    ])
    await query.edit_message_text("🎮 **Select Game Mode:**", reply_markup=kb, parse_mode="Markdown")
    return SELECTING_GAME_TYPE

async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 1. Determine Game Type
    game_type = "30s" if query.data == "game_30s" else "1m"
    context.user_data["game_type"] = game_type # Store in temporary context
    
    await query.edit_message_text(f"🔄 Fetching **Wingo {game_type.upper()}** data from API...")
    
    # 2. Trigger the Prediction Display
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- UPDATED: AUTOMATED PREDICTION DISPLAY ---
async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle both callback (from buttons) and regular calls
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        user_id = update.callback_query.from_user.id
    else:
        # Fallback if called manually
        msg_func = update.message.reply_text
        user_id = update.effective_user.id

    user_data = get_user_data(user_id)
    game_type = context.user_data.get("game_type", "30s")
    
    # 1. Fetch API Data
    period, history = get_game_data(game_type)
    
    if not period:
        await msg_func("❌ **API Error.** Could not fetch game data. Try again later.")
        return ConversationHandler.END

    mode = user_data.get("prediction_mode", "V2")
    
    # 2. Logic Selection
    if mode == "V5":
        pred, pat, v5_digit = get_v5_logic(period)
        shot_num = v5_digit if user_data.get("has_number_shot") else None
    else:
        # Standard Engines: Pass API History to Engine
        # We need a 'dummy' outcome to trigger the engine, 
        # but for the *first* run of a session, we might just want the prediction.
        # Actually, let's recalculate based on the new history.
        
        # NOTE: For V1/V4 to work, we need to pass the history.
        # We assume 'Small' as a dummy 'outcome' just to trigger the function return,
        # but the function will rely on 'history' list.
        pred, pat = process_prediction_request(user_id, "win", api_history=history)
        
        shot_num = get_number_for_outcome(pred) if user_data.get("has_number_shot") else None

    # Save to DB
    update_user_field(user_id, "current_prediction", pred)
    update_user_field(user_id, "current_pattern_name", pat)

    # 3. Display
    lvl = user_data.get("current_level", 1)
    unit = get_bet_unit(lvl)
    number_line = f"Number: **{shot_num}**\n" if shot_num is not None else ""

    msg = (f"🎮 **WINGO {game_type.upper()}** (Mode: {mode})\n\n"
           f"📅 Period: `{period}`\n"
           f"🎲 Bet: **{pred}**\n"
           f"{number_line}💰 Level: {lvl} ({unit} Units)\n"
           f"🔍 Pattern: {pat}")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="feedback_win"), 
         InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss")]
    ])
    
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    outcome = query.data.split("_")[1] # 'win' or 'loss'
    
    # 1. Update Level
    user_data = get_user_data(user_id)
    curr_lvl = user_data.get("current_level", 1)
    new_lvl = 1 if outcome == "win" else min(curr_lvl + 1, MAX_LEVEL)
    update_user_field(user_id, "current_level", new_lvl)
    
    # 2. Recursively call show_prediction to get the NEXT period from API
    # We update the message to "Loading..." first for better UX
    await query.edit_message_text("🔄 **Calculating next round...**")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- UPDATED: TARGET COMMAND FLOW ---
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data.get("target_session"):
        await update.message.reply_text("⚠️ Active Target session found. Resume?", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Resume ▶️", callback_data="target_resume")]]))
        return TARGET_START_MENU 

    # Check Pack Ownership
    if not user_data.get("target_access"):
        await update.message.reply_text("❌ You need a Target Pack. Buy one in /packs.")
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ WINGO 30 SEC", callback_data="tgt_game_30s")],
        [InlineKeyboardButton("🕐 WINGO 1 MIN", callback_data="tgt_game_1m")]
    ])
    await update.message.reply_text("🎯 **Select Target Game:**", reply_markup=kb)
    return TARGET_SELECT_GAME

async def start_target_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    game_type = "30s" if query.data == "tgt_game_30s" else "1m"
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    
    await query.edit_message_text(f"🔄 Starting Target Session for **{game_type.upper()}**...")
    
    # Start Session (Fetches API automatically inside)
    session = start_target_session(user_id, user_data['target_access'], game_type)
    
    if not session:
        await query.edit_message_text("❌ API Error. Could not fetch period.")
        return ConversationHandler.END
        
    await display_target_step(query, session, "Started")
    return TARGET_GAME_LOOP

async def target_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_user_data(user_id).get("target_session")
    
    if not session:
        await query.edit_message_text("❌ No session found.")
        return ConversationHandler.END
        
    await display_target_step(query, session, "Resumed")
    return TARGET_GAME_LOOP

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("invite", invite_command)) 
    app.add_handler(CommandHandler("refstats", admin_referral_stats_command)) 
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Global Callbacks
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_"))

    # Jobs
    app.job_queue.run_repeating(monthly_reset_job, interval=3600, first=60)

    # Standard Game Handler
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_game_type, pattern="^select_game_type$")],
        states={
            SELECTING_GAME_TYPE: [CallbackQueryHandler(start_game_flow, pattern="^game_")],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^feedback_")]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(pred_h)

    # Target Game Handler
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command)],
        states={
            TARGET_START_MENU: [CallbackQueryHandler(target_resume, pattern="^target_resume$")],
            TARGET_SELECT_GAME: [CallbackQueryHandler(start_target_game, pattern="^tgt_game_")],
            TARGET_GAME_LOOP: [CallbackQueryHandler(target_game_loop, pattern="^tgt_")]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(target_h)
    
    # Buy Handler (Keep existing)
    # ... (Include the Buy Handler code from previous responses here) ...

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()