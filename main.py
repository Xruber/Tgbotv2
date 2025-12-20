import logging
import random
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    CallbackQueryHandler, filters, ConversationHandler
)

from config import (
    BOT_TOKEN, ADMIN_ID, REGISTER_LINK, PAYMENT_IMAGE_URL, PREDICTION_PROMPT, 
    PREDICTION_PLANS, TARGET_PACKS, TARGET_SEQUENCE, NUMBER_SHOT_PRICE, NUMBER_SHOT_KEY, MAX_LEVEL
)
from database import get_user_data, update_user_field, is_subscription_active, get_remaining_time_str
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome
from target_engine import start_target_session, process_target_outcome

# States
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 WAITING_FOR_PERIOD_NUMBER, WAITING_FOR_FEEDBACK, TARGET_GAME_LOOP) = range(6)

logger = logging.getLogger(__name__)

# --- UTILS ---
async def grant_access(user_id, item_key, context):
    """Generic granter for Plans, Packs, and Target."""
    # 1. Subscription Plans
    if item_key in PREDICTION_PLANS:
        plan = PREDICTION_PLANS[item_key]
        expiry = __import__("time").time() + plan["duration_seconds"]
        update_user_field(user_id, "prediction_status", "ACTIVE")
        update_user_field(user_id, "expiry_timestamp", int(expiry))
        await context.bot.send_message(user_id, f"✅ **{plan['name']} Activated!**\nUse /start to play.")
        
    # 2. Number Shot Pack
    elif item_key == NUMBER_SHOT_KEY:
        update_user_field(user_id, "has_number_shot", True)
        await context.bot.send_message(user_id, "✅ **Number Shot Pack Activated!**\nYou will now see numbers in predictions.")

    # 3. Target Packs
    elif item_key in TARGET_PACKS:
        update_user_field(user_id, "target_access", item_key)
        name = TARGET_PACKS[item_key]['name']
        await context.bot.send_message(user_id, f"✅ **{name} Purchased!**\nType /target to start your session (One-time use).")

# --- COMMANDS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main Menu."""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    active = is_subscription_active(user_data)
    
    buttons = [
        [InlineKeyboardButton("💬 Telegram Group", url=REGISTER_LINK)],
        [InlineKeyboardButton("🛍️ Add-on Shop (Packs)", callback_data="shop_main")]
    ]
    
    if active:
        buttons.insert(1, [InlineKeyboardButton("✨ Get Strategy", callback_data="show_prediction")])
    else:
        buttons.insert(1, [InlineKeyboardButton("🔮 Buy Strategy", callback_data="start_prediction_flow")])
        
    await update.message.reply_text(
        f"👋 Welcome! Status: {'🟢 Active' if active else '🔴 Inactive'}\n"
        "Use /switch to change engines or /target to play Target Mode.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END

async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The Shop Menu."""
    keyboard = [
        [InlineKeyboardButton("🎯 Target Prediction Packs", callback_data="shop_target")],
        [InlineKeyboardButton(f"🔢 Number Shot Pack ({NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
    ]
    await update.message.reply_text("🛍️ **Add-on Shop**\nSelect a category:", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "shop_target":
        # Show Target Options
        buttons = []
        for key, pack in TARGET_PACKS.items():
            buttons.append([InlineKeyboardButton(f"{pack['name']} - {pack['price']}", callback_data=f"buy_{key}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="shop_main")])
        await query.edit_message_text("🎯 **Select Target Pack:**", reply_markup=InlineKeyboardMarkup(buttons))
        
    elif data == "shop_main":
        # Back to main shop
        keyboard = [
            [InlineKeyboardButton("🎯 Target Prediction Packs", callback_data="shop_target")],
            [InlineKeyboardButton(f"🔢 Number Shot Pack ({NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
        ]
        await query.edit_message_text("🛍️ **Add-on Shop**", reply_markup=InlineKeyboardMarkup(keyboard))

async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user_data(update.effective_user.id)
    if not is_subscription_active(user_data):
        await update.message.reply_text("❌ Subscription Required.")
        return
        
    curr = user_data.get("prediction_mode", "V2")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅ ' if curr=='V1' else ''}V1: Original", callback_data="set_mode_V1")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V2' else ''}V2: Streak/Switch", callback_data="set_mode_V2")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V3' else ''}V3: Random 0-9", callback_data="set_mode_V3")]
    ])
    await update.message.reply_text(f"⚙️ **Engine Switcher**\nCurrent: {curr}", reply_markup=kb)

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[-1]
    update_user_field(query.from_user.id, "prediction_mode", mode)
    await query.answer(f"Switched to {mode}")
    await query.edit_message_text(f"✅ Logic updated to **{mode}**.")

# --- PAYMENT FLOW (Generic) ---
async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Extract item key
    item_key = query.data.replace("buy_", "")
    context.user_data["buying_item"] = item_key
    
    # Determine Price/Name for display
    if item_key in PREDICTION_PLANS:
        info = f"{PREDICTION_PLANS[item_key]['name']} - {PREDICTION_PLANS[item_key]['price']}"
    elif item_key in TARGET_PACKS:
        info = f"{TARGET_PACKS[item_key]['name']} - {TARGET_PACKS[item_key]['price']}"
    elif item_key == NUMBER_SHOT_KEY:
        info = f"Number Shot Pack - {NUMBER_SHOT_PRICE}"
    else:
        # Fallback for main menu "Buy Strategy" button if no plan selected yet
        # Shows the plan selection menu instead
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["name"], callback_data=f"buy_{k}")] for k, p in PREDICTION_PLANS.items()])
        await query.edit_message_text("Select Plan:", reply_markup=kb)
        return SELECTING_PLAN

    caption = f"🛒 **Buying:** {info}\n\n1. Scan QR / Pay UPI.\n2. Click 'Sent 🟢'.\n3. Enter UTR."
    
    try:
        await context.bot.send_photo(query.from_user.id, PAYMENT_IMAGE_URL, caption=caption, 
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sent 🟢", callback_data="sent")]]))
    except:
        await context.bot.send_message(query.from_user.id, f"⚠️ Image Error.\n\n{caption}", 
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sent 🟢", callback_data="sent")]]))
    return WAITING_FOR_PAYMENT_PROOF

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    item = context.user_data.get("buying_item")
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"adm_ok_{uid}_{item}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"adm_no_{uid}")
    ]])
    await context.bot.send_message(ADMIN_ID, f"💸 **New Order**\nUser: `{uid}`\nItem: `{item}`\nUTR: `{utr}`", 
                                   parse_mode="Markdown", reply_markup=kb)
    await update.message.reply_text("✅ **Payment Under Review.** You will be notified.")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    action, uid = parts[1], int(parts[2])
    
    if action == "ok":
        # Rejoin item key if it had underscores (e.g. target_2k)
        item_key = "_".join(parts[3:])
        await grant_access(uid, item_key, context)
        await query.edit_message_text(f"✅ Approved item '{item_key}' for {uid}.")
    else:
        try: await context.bot.send_message(uid, "❌ **Payment Rejected.** Check UTR and try again.")
        except: pass
        await query.edit_message_text("❌ Rejected.")

# --- STANDARD PREDICTION FLOW ---
async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if is_subscription_active(get_user_data(query.from_user.id)):
        await context.bot.send_message(query.from_user.id, PREDICTION_PROMPT, parse_mode="Markdown")
        return WAITING_FOR_PERIOD_NUMBER
    await context.bot.send_message(query.from_user.id, "❌ Expired.")
    return ConversationHandler.END

async def receive_period_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: period = int(update.message.text)
    except: return WAITING_FOR_PERIOD_NUMBER
    
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Get Prediction Data
    pred = user_data.get("current_prediction", "Small")
    lvl = user_data.get("current_level", 1)
    pat = user_data.get("current_pattern_name", "Start")
    mode = user_data.get("prediction_mode", "V2")
    unit = get_bet_unit(lvl)

    # Number Shot Logic
    number_line = ""
    if user_data.get("has_number_shot"):
        shot_num = get_number_for_outcome(pred)
        number_line = f"Number: **{shot_num}**\n"

    msg = (f"⏳ **Strategy (Mode: {mode})**\n\nPeriod: `{period}`\nBet: **{pred}**\n"
           f"{number_line}Level: {lvl} ({unit} Units)\nPattern: {pat}")
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ WIN", callback_data="feedback_win"), InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss")]])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    outcome = query.data.split("_")[1]
    
    # Logic Update
    user_data = get_user_data(uid)
    curr_lvl = user_data.get("current_level", 1)
    new_lvl = 1 if outcome == "win" else min(curr_lvl + 1, MAX_LEVEL)
    update_user_field(uid, "current_level", new_lvl)
    
    # Engine
    new_pred, pat = process_prediction_request(uid, outcome)
    
    # Display
    mode = user_data.get("prediction_mode", "V2")
    unit = get_bet_unit(new_lvl)
    
    number_line = ""
    if user_data.get("has_number_shot"):
        shot_num = get_number_for_outcome(new_pred)
        number_line = f"Number: **{shot_num}**\n"

    await query.edit_message_text(
        f"Result: **{outcome.upper()}**\n\n➡️ **Next Prediction ({mode})**\n"
        f"Bet: **{new_pred}**\n{number_line}Level: {new_lvl} ({unit} Units)\nReason: {pat}\n\n{PREDICTION_PROMPT}",
        parse_mode="Markdown"
    )
    return WAITING_FOR_PERIOD_NUMBER

# --- TARGET COMMAND FLOW ---
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Check if active session exists
    if user_data.get("target_session"):
        await update.message.reply_text("⚠️ You already have an active Target session. Resume?", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Resume ▶️", callback_data="target_resume")]]))
        return ConversationHandler.END

    # Check if they own a pack
    owned_pack = user_data.get("target_access")
    if not owned_pack:
        await update.message.reply_text("❌ You haven't bought a Target Pack. Use /packs to buy one.")
        return ConversationHandler.END

    pack_name = TARGET_PACKS[owned_pack]['name']
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 START SESSION", callback_data="target_start")]])
    await update.message.reply_text(f"🎯 **Ready to start {pack_name}?**\n\nOne-time use. Good luck!", reply_markup=kb)
    return TARGET_GAME_LOOP

async def target_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    
    session = start_target_session(user_id, user_data['target_access'])
    if not session:
        await query.edit_message_text("❌ Error starting session.")
        return ConversationHandler.END
        
    await display_target_step(query, session, "Started")
    return TARGET_GAME_LOOP

async def display_target_step(query, session, status_text):
    # Format message
    bal = session['current_balance']
    target = session['target_amount']
    lvl_idx = session['current_level_index']
    bet = TARGET_SEQUENCE[lvl_idx]
    pred = session['current_prediction']
    
    msg = (f"🎯 **TARGET PREDICTION** ({session['pack_name']})\n\n"
           f"💰 Balance: **{bal}** / {target}\n"
           f"🎲 Bet: **{bet}** on **{pred}**\n\n"
           f"Result of Period?")
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), 
        InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")
    ]])
    
    if query.message: await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else: await query.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def target_game_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    outcome = query.data.replace("tgt_", "") # win or loss
    
    session, status = process_target_outcome(user_id, outcome)
    
    if status == "TargetReached":
        await query.edit_message_text(f"🏆 **TARGET REACHED!**\n\nFinal Balance: {session['current_balance']}\nSession Ended.")
        return ConversationHandler.END
    elif status == "Bankrupt":
        await query.edit_message_text("💀 **Bankrupt.** Session Ended.")
        return ConversationHandler.END
    elif status == "Ended":
        await query.edit_message_text("❌ Session Error.")
        return ConversationHandler.END
        
    await display_target_step(query, session, outcome.upper())
    return TARGET_GAME_LOOP

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 1. Main Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    
    # 2. Shop & Settings Callbacks
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_"))

    # 3. Standard Prediction Loop
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={
            WAITING_FOR_PERIOD_NUMBER: [MessageHandler(filters.TEXT, receive_period_number)],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^feedback_")]
        },
        fallbacks=[CommandHandler("cancel", cancel)], allow_reentry=True
    )
    app.add_handler(pred_h)

    # 4. Target Game Loop
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command)],
        states={
            TARGET_GAME_LOOP: [
                CallbackQueryHandler(target_start, pattern="^target_start$"),
                CallbackQueryHandler(target_game_loop, pattern="^tgt_"),
                CallbackQueryHandler(target_start, pattern="^target_resume$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)], allow_reentry=True
    )
    app.add_handler(target_h)

    # 5. Purchase Loop (Shared)
    buy_h = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_buy, pattern="^start_prediction_flow$"),
            CallbackQueryHandler(start_buy, pattern="^buy_")
        ],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(start_buy, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_caption("Reply with UTR") or WAITING_FOR_UTR, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT, receive_utr)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(buy_h)

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()