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
from database import (
    get_user_data, update_user_field, increment_user_field, get_top_referrers, 
    is_subscription_active, get_remaining_time_str, check_and_reset_monthly_stats
)
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome, get_v5_logic
from target_engine import start_target_session, process_target_outcome
from salt_service import start_salt_service
from api_helper import get_game_data

# States
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, 
 TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP) = range(8)

logger = logging.getLogger(__name__)

# --- UTILS & COMMANDS ---
async def grant_access(user_id, item_key, context):
    if item_key in PREDICTION_PLANS:
        plan = PREDICTION_PLANS[item_key]
        expiry = __import__("time").time() + plan["duration_seconds"]
        update_user_field(user_id, "prediction_status", "ACTIVE")
        update_user_field(user_id, "expiry_timestamp", int(expiry))
        await context.bot.send_message(user_id, f"✅ **{plan['name']} Activated!**\nUse /start to play.")
    elif item_key == NUMBER_SHOT_KEY:
        update_user_field(user_id, "has_number_shot", True)
        await context.bot.send_message(user_id, "✅ **Number Shot Pack Activated!**\nYou will now see numbers in predictions.")
    elif item_key in TARGET_PACKS:
        update_user_field(user_id, "target_access", item_key)
        name = TARGET_PACKS[item_key]['name']
        await context.bot.send_message(user_id, f"✅ **{name} Purchased!**\nType /target to start your session (One-time use).")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id) 
    
    if context.args and not user_data.get("referred_by"):
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                ref_data = get_user_data(referrer_id)
                if ref_data:
                    update_user_field(user_id, "referred_by", referrer_id)
                    try: await context.bot.send_message(referrer_id, f"🎉 **New Referral!**\n{update.effective_user.first_name} joined using your link.")
                    except: pass
        except ValueError: pass

    active = is_subscription_active(user_data)
    buttons = [
        [InlineKeyboardButton("💬 Telegram Group", url=REGISTER_LINK)],
        [InlineKeyboardButton("🛍️ Add-on Shop (Packs)", callback_data="shop_main")]
    ]
    if active:
        buttons.insert(1, [InlineKeyboardButton("✨ Get Strategy", callback_data="select_game_type")])
    else:
        buttons.insert(1, [InlineKeyboardButton("🔮 Buy Strategy", callback_data="start_prediction_flow")])
        
    await update.message.reply_text(
        f"👋 Welcome! Status: {'🟢 Active' if active else '🔴 Inactive'}\n"
        "🛑 Prediction Bot with 5-6 levels & API Integration.\n\n"
        "Use /invite to get your referral link.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    bot_username = context.bot.username
    invite_link = f"https://t.me/{bot_username}?start={user_id}"
    sales = user_data.get("referral_purchases", 0)
    await update.message.reply_text(
        f"📢 **Your Referral Link**\n\nShare: `{invite_link}`\n\n📊 Sales (Month): **{sales}**",
        parse_mode="Markdown"
    )

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    top_refs = get_top_referrers(limit=10)
    if not top_refs:
        await update.message.reply_text("📉 No data.")
        return
    msg = "🏆 **Top Referrers**\n\n"
    for i, user in enumerate(top_refs):
        msg += f"{i+1}. `{user.get('user_id')}` - **{user.get('referral_purchases', 0)}**\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_field(user_id, "current_level", 1)
    update_user_field(user_id, "history", [])
    update_user_field(user_id, "current_prediction", random.choice(['Small', 'Big']))
    update_user_field(user_id, "current_pattern_name", "Random (Reset)")
    await update.message.reply_text("🔄 **Reset Done.**")

async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎯 Target Packs", callback_data="shop_target")],
        [InlineKeyboardButton(f"🔢 Number Shot ({NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
    ]
    msg_func = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    await msg_func("🛍️ **Add-on Shop**", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "shop_target":
        buttons = []
        for key, pack in TARGET_PACKS.items():
            buttons.append([InlineKeyboardButton(f"{pack['name']} - {pack['price']}", callback_data=f"buy_{key}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="shop_main")])
        await query.edit_message_text("🎯 **Select Pack:**", reply_markup=InlineKeyboardMarkup(buttons))
    elif query.data == "shop_main":
        await packs_command(update, context)

async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user_data(update.effective_user.id)
    if not is_subscription_active(user_data):
        await update.message.reply_text("❌ Subscription Required.")
        return
    curr = user_data.get("prediction_mode", "V2")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅ ' if curr=='V1' else ''}V1: Pattern/Streak", callback_data="set_mode_V1")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V2' else ''}V2: Streak/Switch", callback_data="set_mode_V2")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V3' else ''}V3: Random AI", callback_data="set_mode_V3")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V4' else ''}V4: Safety & Trend", callback_data="set_mode_V4")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V5' else ''}V5: SHA256 Logic", callback_data="set_mode_V5")]
    ])
    await update.message.reply_text(f"⚙️ **Engine Switcher**\nCurrent: {curr}", reply_markup=kb)

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[-1]
    update_user_field(query.from_user.id, "prediction_mode", mode)
    await query.answer(f"Switched to {mode}")
    await query.edit_message_text(f"✅ Logic updated to **{mode}**.")

# --- JOB ---
async def monthly_reset_job(context: ContextTypes.DEFAULT_TYPE):
    if check_and_reset_monthly_stats():
        await context.bot.send_message(ADMIN_ID, "📅 **Monthly Reset Complete!**")

# --- BUY FLOW ---
async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_key = query.data.replace("buy_", "")
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    
    if item_key == NUMBER_SHOT_KEY and user_data.get("has_number_shot"):
        await query.message.reply_text("✅ You already have this.")
        return ConversationHandler.END
    if item_key in TARGET_PACKS and user_data.get("target_access"):
        await query.message.reply_text("⚠️ Limit reached. Finish current session first.")
        return ConversationHandler.END

    context.user_data["buying_item"] = item_key
    caption = "🛒 **Pay now.**"
    try: await query.message.delete()
    except: pass
    await context.bot.send_photo(chat_id=user_id, photo=PAYMENT_IMAGE_URL, caption=caption, 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sent 🟢", callback_data="sent")]]))
    return WAITING_FOR_PAYMENT_PROOF

async def confirm_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption("✅ **Received.** Send UTR now:")
    return WAITING_FOR_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    item = context.user_data.get("buying_item")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"adm_ok_{uid}_{item}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"adm_no_{uid}")
    ]])
    await context.bot.send_message(ADMIN_ID, f"💸 **Order**\nUser: `{uid}`\nUTR: `{utr}`", parse_mode="Markdown", reply_markup=kb)
    await update.message.reply_text("✅ Reviewing...")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    action, uid = parts[1], int(parts[2])
    if action == "ok":
        item_key = "_".join(parts[3:])
        await grant_access(uid, item_key, context)
        # Referral
        buyer = get_user_data(uid)
        if buyer.get("referred_by"):
            increment_user_field(buyer["referred_by"], "referral_purchases", 1)
        await query.edit_message_text("✅ Approved.")
    else:
        await query.edit_message_text("❌ Rejected.")

# --- GAME FLOW ---
async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ WINGO 30 SEC", callback_data="game_30s")],
        [InlineKeyboardButton("🕐 WINGO 1 MIN", callback_data="game_1m")]
    ])
    await query.edit_message_text("🎮 **Select Game Mode:**", reply_markup=kb)
    return SELECTING_GAME_TYPE

async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_type = "30s" if query.data == "game_30s" else "1m"
    context.user_data["game_type"] = game_type
    await query.edit_message_text(f"🔄 Fetching **Wingo {game_type.upper()}**...")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        user_id = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        user_id = update.effective_user.id

    user_data = get_user_data(user_id)
    game_type = context.user_data.get("game_type", "30s")
    
    period, history = get_game_data(game_type)
    if not period or period == "None":
        await msg_func("❌ **API Error.** Retry in 10s.")
        return ConversationHandler.END

    mode = user_data.get("prediction_mode", "V2")
    
    # --- LOGIC SELECTION ---
    if mode == "V5":
        # Pass game_type to V5 logic
        pred, pat, v5_digit = get_v5_logic(period, game_type)
        shot_num = v5_digit if user_data.get("has_number_shot") else None
    else:
        pred, pat = process_prediction_request(user_id, "win", api_history=history)
        shot_num = get_number_for_outcome(pred) if user_data.get("has_number_shot") else None

    update_user_field(user_id, "current_prediction", pred)
    update_user_field(user_id, "current_pattern_name", pat)

    lvl = user_data.get("current_level", 1)
    unit = get_bet_unit(lvl)
    num_line = f"Number: **{shot_num}**\n" if shot_num is not None else ""

    msg = (f"🎮 **WINGO {game_type.upper()}** (Mode: {mode})\n\n"
           f"📅 Period: `{period}`\n"
           f"🎲 Bet: **{pred}**\n"
           f"{num_line}💰 Level: {lvl} ({unit} Units)\n"
           f"🔍 Pattern: {pat}")
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ WIN", callback_data="feedback_win"), InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss")]])
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    outcome = query.data.split("_")[1]
    
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    curr_lvl = user_data.get("current_level", 1)
    new_lvl = 1 if outcome == "win" else min(curr_lvl + 1, MAX_LEVEL)
    update_user_field(user_id, "current_level", new_lvl)
    
    await query.edit_message_text("🔄 **Calculating next round...**")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- TARGET ---
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data.get("target_session"):
        await update.message.reply_text("⚠️ Active session. Resume?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Resume ▶️", callback_data="target_resume")]]))
        return TARGET_START_MENU 
    if not user_data.get("target_access"):
        await update.message.reply_text("❌ No Target Pack.")
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
    await query.edit_message_text(f"🔄 Starting **{game_type.upper()}** session...")
    
    session = start_target_session(user_id, user_data['target_access'], game_type)
    if not session:
        await query.edit_message_text("❌ API Error.")
        return ConversationHandler.END
    await display_target_step(query, session)
    return TARGET_GAME_LOOP

async def target_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    session = get_user_data(query.from_user.id).get("target_session")
    if not session:
        await query.edit_message_text("❌ No session.")
        return ConversationHandler.END
    await display_target_step(query, session)
    return TARGET_GAME_LOOP

async def display_target_step(update_obj, session):
    msg = (f"🎯 **TARGET**\n📅 `{session['current_period']}`\n💰 {session['current_balance']} / {session['target_amount']}\n🎲 Bet: **{session['current_prediction']}**\n💵 {session['sequence'][session['current_level_index']]}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")]])
    await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

async def target_game_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    outcome = query.data.replace("tgt_", "")
    session, status = process_target_outcome(query.from_user.id, outcome)
    if status in ["TargetReached", "Bankrupt", "Ended"]:
        await query.edit_message_text(f"🛑 **{status}**")
        return ConversationHandler.END
    await display_target_step(query, session)
    return TARGET_GAME_LOOP

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("invite", invite_command)) 
    app.add_handler(CommandHandler("refstats", admin_referral_stats_command)) 
    app.add_handler(CommandHandler("cancel", cancel))
    
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_"))
    
    app.job_queue.run_repeating(monthly_reset_job, interval=3600, first=60)

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
    
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_buy, pattern="^start_prediction_flow$"), CallbackQueryHandler(start_buy, pattern="^buy_")],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(start_buy, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(confirm_sent, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    ))
    
    print("🚀 Starting Background Salt Cracker Service...")
    start_salt_service()

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()