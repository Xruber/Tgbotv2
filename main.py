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
from database import get_user_data, update_user_field, is_subscription_active, get_remaining_time_str
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome
from target_engine import start_target_session, process_target_outcome, calculate_sequence 

# States
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 WAITING_FOR_PERIOD_NUMBER, WAITING_FOR_FEEDBACK, 
 TARGET_START_MENU, WAITING_FOR_TARGET_PERIOD, TARGET_GAME_LOOP) = range(8)

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
    """Main Menu. Resets any active conversation."""
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
        "🛑 Hello I am prediction bot with 5-6levels also have target prediction with high and unlimited profit💰.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END

async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The Shop Menu."""
    keyboard = [
        [InlineKeyboardButton("🎯 Target Prediction Packs", callback_data="shop_target")],
        [InlineKeyboardButton(f"🔢 Number Shot Pack ({NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
    ]
    if update.callback_query:
        await update.callback_query.message.reply_text("🛍️ **Add-on Shop**\nSelect a category:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
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
        [InlineKeyboardButton(f"{'✅ ' if curr=='V3' else ''}V3: Analyzing Streak", callback_data="set_mode_V3")]
    ])
    await update.message.reply_text(f"⚙️ **Engine Switcher**\nCurrent: {curr}", reply_markup=kb)

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[-1]
    update_user_field(query.from_user.id, "prediction_mode", mode)
    await query.answer(f"Switched to {mode}")
    await query.edit_message_text(f"✅ Logic updated to **{mode}**.")

# --- PAYMENT FLOW ---

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    item_key = query.data.replace("buy_", "")
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    
    # Check Duplicate: Number Shot
    if item_key == NUMBER_SHOT_KEY:
        if user_data.get("has_number_shot"):
            await query.message.reply_text("✅ **You already own the Number Shot Pack!**")
            return ConversationHandler.END

    # Check Duplicate: Target Plans
    if item_key in TARGET_PACKS:
        if user_data.get("target_access"):
             current = TARGET_PACKS[user_data['target_access']]['name']
             await query.message.reply_text(f"⚠️ **Limit Reached:** You already have the **{current}**. Please finish using it first via /target.")
             return ConversationHandler.END

    context.user_data["buying_item"] = item_key
    
    # Determine Price/Name
    if item_key in PREDICTION_PLANS:
        info = f"{PREDICTION_PLANS[item_key]['name']} - {PREDICTION_PLANS[item_key]['price']}"
    elif item_key in TARGET_PACKS:
        info = f"{TARGET_PACKS[item_key]['name']} - {TARGET_PACKS[item_key]['price']}"
    elif item_key == NUMBER_SHOT_KEY:
        info = f"Number Shot Pack - {NUMBER_SHOT_PRICE}"
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["name"], callback_data=f"buy_{k}")] for k, p in PREDICTION_PLANS.items()])
        await query.edit_message_text("Select Plan:", reply_markup=kb)
        return SELECTING_PLAN

    caption = f"🛒 **Buying:** {info}\n\n1. Scan QR / Pay UPI.\n2. Click 'Sent 🟢'.\n3. Enter UTR."
    
    try: await query.message.delete()
    except: pass

    try:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=PAYMENT_IMAGE_URL,
            caption=caption,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sent 🟢", callback_data="sent")]])
        )
    except:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⚠️ Image Error.\n\n{caption}", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sent 🟢", callback_data="sent")]])
        )
    return WAITING_FOR_PAYMENT_PROOF

async def confirm_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_caption("✅ **Proof Received.**\n\n👇 Please reply with your **UTR / Reference Number** now:")
    except:
        await query.edit_message_text("✅ **Proof Received.**\n\n👇 Please reply with your **UTR / Reference Number** now:")
    return WAITING_FOR_UTR

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
    await update.message.reply_text("✅ **Payment Under Review.** You will be notified when approved.")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    action, uid = parts[1], int(parts[2])
    
    if action == "ok":
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
           f"{number_line}Level: {lvl} ({unit} Units)")
    
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
        f"Result: **{outcome.upper()}**\n\n🛑 Please follow bot's instructions\n\n➡️ **Next Prediction ({mode})**\n"
        f"Next Level: {new_lvl} ({unit} Units)\nReason: {pat}\n\n{PREDICTION_PROMPT}",
        parse_mode="Markdown"
    )
    return WAITING_FOR_PERIOD_NUMBER

# --- TARGET COMMAND FLOW ---
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Check active session
    if user_data.get("target_session"):
        await update.message.reply_text("⚠️ You already have an active Target session. Resume?", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Resume ▶️", callback_data="target_resume")]]))
        # If active, we go to MENU state to wait for Resume click
        return TARGET_START_MENU 

    # Check ownership
    owned_pack = user_data.get("target_access")
    if not owned_pack:
        await update.message.reply_text("❌ You haven't bought a Target Pack. Use /packs to buy one.")
        return ConversationHandler.END

    pack_name = TARGET_PACKS[owned_pack]['name']
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 START SESSION", callback_data="ask_period")]])
    await update.message.reply_text(f"🎯 **Ready to start {pack_name}?**\n\nOne-time use. Good luck!", reply_markup=kb)
    return TARGET_START_MENU

async def ask_target_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when user clicks 'START SESSION'."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔢 **Please enter the LAST Period Number** (e.g. 800):")
    return WAITING_FOR_TARGET_PERIOD

async def target_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when user clicks 'RESUME'."""
    query = update.callback_query
    await query.answer()
    
    # Set a flag to know we are resuming, not starting new
    context.user_data['is_resuming_target'] = True
    
    await query.edit_message_text("🔄 **Resuming...**\n\nPlease enter the **LAST Period Number** to sync (e.g. 805):")
    return WAITING_FOR_TARGET_PERIOD

async def handle_target_period_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles period input for both START and RESUME."""
    try:
        last_period = int(update.message.text)
    except:
        await update.message.reply_text("⚠️ Invalid number. Please enter only digits (e.g. 800).")
        return WAITING_FOR_TARGET_PERIOD

    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Check if we are resuming or starting new
    if context.user_data.get('is_resuming_target'):
        session = user_data.get("target_session")
        if session and session.get("is_active"):
            session['current_period'] = last_period + 1
            if "sequence" not in session:
                session["sequence"] = calculate_sequence(session["current_balance"])
            update_user_field(user_id, "target_session", session)
            context.user_data['is_resuming_target'] = False
            await display_target_step(update, session, "Resumed")
            return TARGET_GAME_LOOP
        else:
             await update.message.reply_text("❌ Active session lost. Please start new.")
             return ConversationHandler.END
    
    else:
        # START NEW SESSION
        session = start_target_session(user_id, user_data['target_access'], last_period)
        if not session:
            await update.message.reply_text("❌ Error starting session.")
            return ConversationHandler.END
        
        await display_target_step(update, session, "Started")
        return TARGET_GAME_LOOP

async def display_target_step(update_obj, session, status_text):
    """Handles display, ensuring we EDIT on button clicks and SEND on text input."""
    bal = session['current_balance']
    target = session['target_amount']
    lvl_idx = session['current_level_index']
    
    seq = session.get('sequence', [20, 50, 100, 250, 580]) 
    bet = seq[lvl_idx] if lvl_idx < len(seq) else seq[-1]
    
    pred = session['current_prediction']
    period_num = session.get("current_period", "Next")
    
    msg = (f"🎯 **TARGET PREDICTION** ({session['pack_name']})\n\n"
           f"📅 Period: **{period_num}**\n"
           f"💰 Balance: **{bal}** / {target}\n"
           f"🎲 Bet: **{pred}**\n"
           f"🪩 Amount: **{bet}**\n\n"
           f"Result of Period?")
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), 
        InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")
    ]])
    
    # FIX: Check for CallbackQuery first!
    if hasattr(update_obj, 'data'): # This indicates it's a CallbackQuery
         await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
         # Fallback to standard message reply (e.g. after text input)
         await update_obj.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

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
    await update.message.reply_text("Cancelled. Returning to main menu.")
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 1. Standard Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # 2. Global Callbacks
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_"))

    # 3. HANDLERS
    
    # BUY HANDLER
    buy_h = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_buy, pattern="^start_prediction_flow$"),
            CallbackQueryHandler(start_buy, pattern="^buy_")
        ],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(start_buy, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(confirm_sent, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(buy_h)

    # TARGET GAME HANDLER
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command)],
        states={
            TARGET_START_MENU: [
                CallbackQueryHandler(ask_target_period, pattern="^ask_period$"),
                CallbackQueryHandler(target_resume, pattern="^target_resume$")
            ],
            WAITING_FOR_TARGET_PERIOD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_target_period_input)
            ],
            TARGET_GAME_LOOP: [
                CallbackQueryHandler(target_game_loop, pattern="^tgt_"),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(target_h)

    # PREDICTION HANDLER
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_prediction, pattern="^show_prediction$")],
        states={
            WAITING_FOR_PERIOD_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_period_number)],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^feedback_")]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(pred_h)

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()