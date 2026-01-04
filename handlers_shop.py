from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_data, update_user_field, increment_user_field, get_remaining_time_str
from config import PREDICTION_PLANS, TARGET_PACKS, NUMBER_SHOT_PRICE, NUMBER_SHOT_KEY, PAYMENT_IMAGE_URL, ADMIN_ID
from datetime import datetime
from target_engine import start_target_session, process_target_outcome
from config import SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP

async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🎯 Target Strategies", callback_data="shop_target")],
        [InlineKeyboardButton(f"🎲 Number Shot (₹{NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
    ]
    msg = (
        "🛒 **PREMIUM STORE**\n\n"
        "🎯 **Target Packs:** Specialized logic to turn 1k -> 5k.\n"
        "🎲 **Number Shot:** High-risk AI for exact number prediction.\n"
    )
    if update.callback_query: await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "shop_target":
        buttons = []
        for key, pack in TARGET_PACKS.items():
            buttons.append([InlineKeyboardButton(f"{pack['name']} (₹{pack['price']})", callback_data=f"buy_{key}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="shop_main")])
        await q.edit_message_text("🎯 **CHOOSE TARGET GOAL**", reply_markup=InlineKeyboardMarkup(buttons))
    elif q.data == "shop_main":
        await packs_command(update, context)

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("buy_", "")
    uid = q.from_user.id
    ud = get_user_data(uid)
    
    if key == NUMBER_SHOT_KEY and ud.get("has_number_shot"):
        await q.message.reply_text("✅ Owned.")
        return ConversationHandler.END
    if key in TARGET_PACKS and ud.get("target_access"):
        await q.message.reply_text("⚠️ Finish active session first.")
        return ConversationHandler.END

    context.user_data["buying_item"] = key
    
    if key not in PREDICTION_PLANS and key not in TARGET_PACKS and key != NUMBER_SHOT_KEY:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["name"] + " - ₹" + p["price"], callback_data=f"buy_{k}")] for k, p in PREDICTION_PLANS.items()])
        await q.edit_message_text("💎 **SELECT VIP PLAN:**", reply_markup=kb)
        return SELECTING_PLAN

    if key in PREDICTION_PLANS: name, price = PREDICTION_PLANS[key]['name'], PREDICTION_PLANS[key]['price']
    elif key in TARGET_PACKS: name, price = TARGET_PACKS[key]['name'], TARGET_PACKS[key]['price']
    else: name, price = "Number Shot", NUMBER_SHOT_PRICE

    caption = (
        f"🧾 **DIGITAL INVOICE**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🛍 **Item:** {name}\n"
        f"💰 **Total:** ₹{price}\n"
        f"📅 **Date:** {datetime.now().strftime('%Y-%m-%d')}\n"
        f"━━━━━━━━━━━━━━\n"
        f"1. Scan QR -> Pay\n2. Click 'Paid'\n3. Send UTR"
    )
    try: await q.message.delete()
    except: pass
    await context.bot.send_photo(uid, PAYMENT_IMAGE_URL, caption=caption, 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data="sent")]]))
    return WAITING_FOR_PAYMENT_PROOF

async def confirm_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_caption("🔢 **Please Enter UTR Number:**")
    return WAITING_FOR_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr, uid = update.message.text, update.effective_user.id
    item = context.user_data.get("buying_item")
    
    # ADMIN RECEIPT
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"adm_ok_{uid}_{item}"),
        InlineKeyboardButton("Reject", callback_data=f"adm_no_{uid}")
    ]])
    await context.bot.send_message(ADMIN_ID, f"💳 **PAYMENT VERIFICATION**\n👤: `{uid}`\n🛒: `{item}`\n🔢: `{utr}`\n🏦 Check Bank!", reply_markup=kb, parse_mode="Markdown")
    await update.message.reply_text("⏳ **Verifying...** You will be notified. Please Wait About 2-3hrs Admin is Confirming 🕰️.")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    action, uid = parts[1], int(parts[2])
    
    if action == "ok":
        item_key = "_".join(parts[3:])
        await grant_access(uid, item_key, context)
        # Ref
        ref = get_user_data(uid).get("referred_by")
        if ref: increment_user_field(ref, "referral_purchases", 1)
        await q.edit_message_text("✅ Approved.")
    else:
        await context.bot.send_message(uid, "❌ **Payment Rejected.**\nInvalid Transaction ID.")
        await q.edit_message_text("🚫 Rejected.")

async def grant_access(user_id, item_key, context):
    if item_key in PREDICTION_PLANS:
        plan = PREDICTION_PLANS[item_key]
        expiry = __import__("time").time() + plan["duration_seconds"]
        update_user_field(user_id, "prediction_status", "ACTIVE")
        update_user_field(user_id, "expiry_timestamp", int(expiry))
        
        await context.bot.send_message(
            user_id, 
            f"🎉 **PREMIUM ACTIVATED!** 🎉\n"
            f"━━━━━━━━━━━━━━\n"
            f"💎 **Plan:** {plan['name']}\n"
            f"⏳ **Expires:** {get_remaining_time_str(get_user_data(user_id))}\n"
        )
        
    elif item_key == NUMBER_SHOT_KEY:
        update_user_field(user_id, "has_number_shot", True)
        await context.bot.send_message(user_id, "🎲 **NUMBER SHOT UNLOCKED!** 🎲")

    elif item_key in TARGET_PACKS:
        update_user_field(user_id, "target_access", item_key)
        pack = TARGET_PACKS[item_key]
        await context.bot.send_message(
            user_id, 
            f"🎯 **TARGET SESSION READY** 🎯\n"
            f"📦 **Pack:** {pack['name']}\n"
            f"🏁 **Goal:** {pack['target']}\n"
            f"🚀 Type /target to begin."
        )

# --- TARGET COMMANDS ---
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for Target Session."""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data.get("target_session"):
        await update.message.reply_text("⚠️ **Active Session Found.**\nResuming...", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Resume", callback_data="target_resume")]]))
        return TARGET_START_MENU 

    if not user_data.get("target_access"):
        await update.message.reply_text("🚫 **Access Denied.**\nYou need to buy a Target Pack from the Shop first.")
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 WINGO 30 SEC", callback_data="tgt_game_30s")],
        [InlineKeyboardButton("🕐 WINGO 1 MIN", callback_data="tgt_game_1m")]
    ])
    await update.message.reply_text("🎯 **TARGET SESSION SETUP**\nSelect Game Mode:", reply_markup=kb)
    return TARGET_SELECT_GAME

async def start_target_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    gtype = "30s" if q.data == "tgt_game_30s" else "1m"
    uid = q.from_user.id
    ud = get_user_data(uid)
    await q.edit_message_text("⏳ **Initializing...**")
    session = start_target_session(uid, ud['target_access'], gtype)
    if not session:
        await q.edit_message_text("❌ **API Error.**")
        return ConversationHandler.END
    await display_target(q, session)
    return TARGET_GAME_LOOP

async def target_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sess = get_user_data(q.from_user.id).get("target_session")
    if not sess:
        await q.edit_message_text("⌛ Expired.")
        return ConversationHandler.END
    await display_target(q, sess)
    return TARGET_GAME_LOOP

async def display_target(update_obj, sess):
    # PROGRESS BAR & PROFIT LOGIC
    start_bal = sess.get("start_balance", 1000)
    current_bal = sess['current_balance']
    target_bal = sess['target_amount']
    
    # Progress Calculation
    needed = target_bal - start_bal
    made = current_bal - start_bal
    pct = made / needed if needed > 0 else 0
    p_bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
    
    profit_sign = "+" if made >= 0 else ""
    color = "🔴" if sess['current_prediction'] == "Big" else "🟢"
    
    # Sequence Logic Display
    seq_idx = sess['current_level_index']
    seq = sess['sequence']
    bet_amt = seq[seq_idx] if seq_idx < len(seq) else seq[-1]
    
    msg = (
        f"🎯 **TARGET SESSION**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🥅 **Goal:** {target_bal}\n"
        f"📊 **Progress:** {p_bar}\n"
        f"💰 **Balance:** {current_bal} ({profit_sign}{made})\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 **Period:** `{sess['current_period']}`\n"
        f"🔮 **BET:** {color} **{sess['current_prediction'].upper()}**\n"
        f"💸 **Amount:** {bet_amt}\n"
        f"━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")]])
    await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

async def target_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    out = q.data.replace("tgt_", "")
    sess, stat = process_target_outcome(q.from_user.id, out)
    if stat in ["TargetReached", "Bankrupt", "Ended"]:
        txt = "🎉 **TARGET HIT!**" if stat == "TargetReached" else "💀 **FAILED.**"
        await q.edit_message_text(txt + f"\nFinal: {sess['current_balance']}")
        return ConversationHandler.END
    await display_target(q, sess)
    return TARGET_GAME_LOOP