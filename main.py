import logging
import random
import datetime
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

# --- UTILS ---
def generate_progress_bar(current, total, length=10):
    percent = min(1.0, current / total)
    filled_len = int(length * percent)
    bar = "█" * filled_len + "░" * (length - filled_len)
    return f"[{bar}] {int(percent * 100)}%"

# --- COMMANDS ---

async def grant_access(user_id, item_key, context):
    """Detailed Grant Access Message."""
    if item_key in PREDICTION_PLANS:
        plan = PREDICTION_PLANS[item_key]
        expiry = __import__("time").time() + plan["duration_seconds"]
        update_user_field(user_id, "prediction_status", "ACTIVE")
        update_user_field(user_id, "expiry_timestamp", int(expiry))
        
        await context.bot.send_message(
            user_id, 
            f"🎉 **PREMIUM ACTIVATED!** 🎉\n\n"
            f"💎 **Plan:** {plan['name']}\n"
            f"⏳ **Expires:** {get_remaining_time_str(get_user_data(user_id))}\n"
            f"🚀 **Features Unlocked:**\n"
            f"   - API Integration (30s/1m)\n"
            f"   - V1-V5 Prediction Engines\n"
            f"   - Money Management Strategy\n\n"
            f"👇 **Next Steps:**\n"
            f"1. Use /switch to choose your logic.\n"
            f"2. Use /start to begin playing."
        )
        
    elif item_key == NUMBER_SHOT_KEY:
        update_user_field(user_id, "has_number_shot", True)
        await context.bot.send_message(
            user_id, 
            "🎯 **NUMBER SHOT UNLOCKED!** 🎯\n\n"
            "✅ You will now see **Exact Number Predictions** alongside Big/Small.\n"
            "💡 *Tip: Number bets pay 9x. Use small stakes for high rewards.*"
        )

    elif item_key in TARGET_PACKS:
        update_user_field(user_id, "target_access", item_key)
        pack = TARGET_PACKS[item_key]
        await context.bot.send_message(
            user_id, 
            f"🚀 **TARGET SESSION READY** 🚀\n\n"
            f"📦 **Pack:** {pack['name']}\n"
            f"💰 **Goal:** {pack['target']}\n"
            f"📉 **Stop Loss:** 0 (Bankrupt protection active)\n\n"
            f"⚠️ **Important:** This is a one-time session. Do not close the bot until you reach the target.\n\n"
            f"👉 Type /target to begin."
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rich Main Menu."""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id) 
    
    # Referral Handling
    if context.args and not user_data.get("referred_by"):
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                ref_data = get_user_data(referrer_id)
                if ref_data:
                    update_user_field(user_id, "referred_by", referrer_id)
                    try: await context.bot.send_message(referrer_id, f"🎉 **New Referral!**\n{update.effective_user.first_name} joined via your link.")
                    except: pass
        except ValueError: pass

    active = is_subscription_active(user_data)
    
    status_icon = "🟢 ACTIVE" if active else "🔴 EXPIRED / INACTIVE"
    expiry_txt = get_remaining_time_str(user_data) if active else "No Plan"
    
    buttons = [
        [InlineKeyboardButton("💬 Official Community", url=REGISTER_LINK)],
        [InlineKeyboardButton("🛍️ Add-on Shop (Target/Numbers)", callback_data="shop_main")]
    ]
    
    if active:
        buttons.insert(1, [InlineKeyboardButton("🚀 START PREDICTION", callback_data="select_game_type")])
    else:
        buttons.insert(1, [InlineKeyboardButton("💎 Buy Premium Access", callback_data="start_prediction_flow")])
        
    msg = (
        f"👋 **Welcome, {update.effective_user.first_name}!**\n\n"
        f"🤖 **Bot Status:** {status_icon}\n"
        f"⏳ **Validity:** {expiry_txt}\n\n"
        f"**Available Features:**\n"
        f"🔹 **Live API:** Wingo 30s & 1 Min\n"
        f"🔹 **Engines:** V1 Streak, V2 Switch, V3 AI, V4 Trend, V5 SHA256\n"
        f"🔹 **Target Mode:** Auto-compounding strategy\n\n"
        f"👇 **Choose an option below:**"
    )
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    return ConversationHandler.END

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    bot_username = context.bot.username
    
    invite_link = f"https://t.me/{bot_username}?start={user_id}"
    sales = user_data.get("referral_purchases", 0)
    income = sales * 100  # Assuming 100 INR per sale
    
    await update.message.reply_text(
        f"📢 **AFFILIATE PROGRAM**\n\n"
        f"💼 **Your Link:**\n`{invite_link}`\n\n"
        f"📊 **Performance (This Month):**\n"
        f"👥 Referrals: **{sales}**\n"
        f"💰 Estimated Earnings: **₹{income}**\n\n"
        f"💡 **How it works:**\n"
        f"1. Share your link with friends.\n"
        f"2. They buy a plan.\n"
        f"3. You earn **₹100** per sale!\n\n"
        f"💸 _Payouts are processed manually. DM Support to claim._",
        parse_mode="Markdown"
    )

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    top_refs = get_top_referrers(limit=15)
    
    msg = "🏆 **LEADERBOARD (Top Referrers)**\n\n"
    if not top_refs:
        msg += "📉 No data available."
    else:
        for i, user in enumerate(top_refs):
            uid = user.get('user_id')
            sales = user.get('referral_purchases', 0)
            msg += f"#{i+1} 👤 `{uid}` → **{sales} Sales** (₹{sales*100})\n"
            
    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_field(user_id, "current_level", 1)
    update_user_field(user_id, "history", [])
    update_user_field(user_id, "current_prediction", random.choice(['Small', 'Big']))
    await update.message.reply_text("🔄 **Session Reset.**\nHistory cleared and Betting Level reset to 1.")

async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎯 Target Prediction Packs", callback_data="shop_target")],
        [InlineKeyboardButton(f"🔢 Number Shot Pack (₹{NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
    ]
    msg = (
        "🛍️ **ADD-ON SHOP**\n\n"
        "🔥 **Target Packs:** Guaranteed logic to reach 2K-5K balances.\n"
        "🔢 **Number Shot:** Unlocks high-risk, high-reward number predictions (9x payout).\n\n"
        "👇 Select a category:"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "shop_target":
        buttons = []
        for key, pack in TARGET_PACKS.items():
            buttons.append([InlineKeyboardButton(f"{pack['name']} - {pack['price']}", callback_data=f"buy_{key}")])
        buttons.append([InlineKeyboardButton("🔙 Back to Shop", callback_data="shop_main")])
        await query.edit_message_text(
            "🎯 **SELECT TARGET PACK**\n\n"
            "These packs use a specialized compounding algorithm to reach the target balance safely.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
    elif data == "shop_main":
        await packs_command(update, context)

async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user_data(update.effective_user.id)
    if not is_subscription_active(user_data):
        await update.message.reply_text("❌ **Premium Required.**\nPlease buy a plan to use advanced engines.")
        return
        
    curr = user_data.get("prediction_mode", "V2")
    
    # Detailed descriptions
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'🟢 ' if curr=='V1' else ''}V1: Pattern Matcher", callback_data="set_mode_V1")],
        [InlineKeyboardButton(f"{'🟢 ' if curr=='V2' else ''}V2: Streak/Switch (Balanced)", callback_data="set_mode_V2")],
        [InlineKeyboardButton(f"{'🟢 ' if curr=='V3' else ''}V3: Random AI (Unpredictable)", callback_data="set_mode_V3")],
        [InlineKeyboardButton(f"{'🟢 ' if curr=='V4' else ''}V4: Trend Follower (Safe)", callback_data="set_mode_V4")],
        [InlineKeyboardButton(f"{'🟢 ' if curr=='V5' else ''}V5: V5 SHA256 (Hash Logic)", callback_data="set_mode_V5")]
    ])
    await update.message.reply_text(
        f"⚙️ **PREDICTION ENGINE SETTINGS**\n\n"
        f"🔧 **Current Engine:** `{curr}`\n\n"
        f"📝 **Description:**\n"
        f"• **V1:** Follows AABB, ABAB patterns.\n"
        f"• **V2:** Standard level-based switching.\n"
        f"• **V5:** Uses server hash salt analysis (Most Advanced).\n\n"
        f"👇 Select Engine:",
        reply_markup=kb, parse_mode="Markdown"
    )

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[-1]
    update_user_field(query.from_user.id, "prediction_mode", mode)
    await query.answer(f"Updated to {mode}")
    await query.edit_message_text(f"✅ **Engine Updated!**\n\nNow using: **{mode} Logic**\nYour next prediction will use this algorithm.")

# --- JOB QUEUE ---
async def monthly_reset_job(context: ContextTypes.DEFAULT_TYPE):
    if check_and_reset_monthly_stats():
        await context.bot.send_message(ADMIN_ID, "📅 **SYSTEM ALERT**\nMonthly referral stats have been reset.")

# --- PAYMENT FLOW ---

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_key = query.data.replace("buy_", "")
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    
    # Check duplicates
    if item_key == NUMBER_SHOT_KEY and user_data.get("has_number_shot"):
        await query.message.reply_text("✅ You already own the Number Shot Pack.")
        return ConversationHandler.END
    if item_key in TARGET_PACKS and user_data.get("target_access"):
        await query.message.reply_text("⚠️ **Active Session Found.**\nPlease complete your current Target Session before buying another.")
        return ConversationHandler.END

    context.user_data["buying_item"] = item_key
    
    # Get details
    if item_key in PREDICTION_PLANS:
        info = f"{PREDICTION_PLANS[item_key]['name']} (₹{PREDICTION_PLANS[item_key]['price']})"
    elif item_key in TARGET_PACKS:
        info = f"{TARGET_PACKS[item_key]['name']} (₹{TARGET_PACKS[item_key]['price']})"
    elif item_key == NUMBER_SHOT_KEY:
        info = f"Number Shot Pack (₹{NUMBER_SHOT_PRICE})"
    else:
        # Default Plan Selection
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["name"] + " - " + p["price"], callback_data=f"buy_{k}")] for k, p in PREDICTION_PLANS.items()])
        await query.edit_message_text("💎 **Select Premium Plan:**", reply_markup=kb)
        return SELECTING_PLAN

    caption = (
        f"🛒 **CHECKOUT**\n"
        f"📦 **Item:** {info}\n\n"
        f"💳 **Instructions:**\n"
        f"1. Scan the QR Code above.\n"
        f"2. Pay exactly the amount shown.\n"
        f"3. Click 'Payment Sent' below.\n"
        f"4. Enter the UTR/Reference ID."
    )
    
    try: await query.message.delete()
    except: pass
    
    try:
        await context.bot.send_photo(
            chat_id=user_id, 
            photo=PAYMENT_IMAGE_URL, 
            caption=caption, 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Payment Sent", callback_data="sent")]])
        )
    except:
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"⚠️ [QR Load Failed]\n\n{caption}", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Payment Sent", callback_data="sent")]])
        )
    return WAITING_FOR_PAYMENT_PROOF

async def confirm_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption("📝 **Step 2/2:**\n\n👇 Please reply with the **12-digit UTR / Transaction ID** now:")
    return WAITING_FOR_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    item = context.user_data.get("buying_item")
    user = update.effective_user
    
    # Detailed Admin Alert
    msg = (
        f"💸 **NEW PAYMENT RECEIVED** 💸\n\n"
        f"👤 **User:** {user.full_name} (`{uid}`)\n"
        f"📦 **Item:** `{item}`\n"
        f"🔢 **UTR:** `{utr}`\n"
        f"📅 **Time:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"👇 **Action:**"
    )
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"adm_ok_{uid}_{item}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"adm_no_{uid}")
    ]])
    
    await context.bot.send_message(ADMIN_ID, msg, parse_mode="Markdown", reply_markup=kb)
    await update.message.reply_text("✅ **Verification Pending.**\nYou will receive a notification once the admin approves your request.")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    action, uid = parts[1], int(parts[2])
    
    if action == "ok":
        item_key = "_".join(parts[3:])
        await grant_access(uid, item_key, context)
        
        # Credit Referrer
        buyer_data = get_user_data(uid)
        ref_id = buyer_data.get("referred_by")
        if ref_id:
            increment_user_field(ref_id, "referral_purchases", 1)
            try: await context.bot.send_message(ref_id, "💰 **Referral Bonus!**\nA user you referred just made a purchase. +1 Sale added to your stats.")
            except: pass
            
        await query.edit_message_text(f"✅ **Approved.**\nAccess granted to User {uid}.")
    else:
        try: await context.bot.send_message(uid, "❌ **Payment Declined.**\nThe UTR provided could not be verified. Please contact support.")
        except: pass
        await query.edit_message_text(f"❌ **Rejected.**\nUser {uid} notified.")

# --- GAME FLOW & API ---

async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ WINGO 30 SEC", callback_data="game_30s")],
        [InlineKeyboardButton("🕐 WINGO 1 MIN", callback_data="game_1m")]
    ])
    await query.edit_message_text("🎮 **Select Game Mode:**\nChoose the game you are currently playing on the exchange.", reply_markup=kb)
    return SELECTING_GAME_TYPE

async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    game_type = "30s" if query.data == "game_30s" else "1m"
    context.user_data["game_type"] = game_type 
    
    await query.edit_message_text(f"🔄 **Connecting to API...**\nFetching live data for Wingo {game_type.upper()}...")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed Prediction Message."""
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        user_id = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        user_id = update.effective_user.id

    user_data = get_user_data(user_id)
    game_type = context.user_data.get("game_type", "30s")
    mode = user_data.get("prediction_mode", "V2")
    
    # API Fetch
    period, history = get_game_data(game_type)
    
    if not period or period == "None":
        await msg_func("❌ **API Connection Error.**\nRetrying in 5 seconds... Check your internet.")
        return ConversationHandler.END

    # Logic
    if mode == "V5":
        pred, pat, v5_digit = get_v5_logic(period, game_type)
        shot_num = v5_digit if user_data.get("has_number_shot") else None
        logic_expl = f"🔑 **Hash Digit:** `{v5_digit}` (Extracted via Salt)"
    else:
        pred, pat = process_prediction_request(user_id, "win", api_history=history)
        shot_num = get_number_for_outcome(pred) if user_data.get("has_number_shot") else None
        logic_expl = f"📈 **Trend:** {pat}"

    update_user_field(user_id, "current_prediction", pred)
    update_user_field(user_id, "current_pattern_name", pat)

    lvl = user_data.get("current_level", 1)
    unit = get_bet_unit(lvl)
    
    # Colors & Emojis
    color = "🔴" if pred == "Big" else "🟢" # Assuming Big=Red, Small=Green standard
    rec_text = "SAFE BET" if lvl <= 2 else "⚠️ HIGH RISK"
    
    num_display = f"\n🔢 **Lucky Number:** `{shot_num}` (9x Payout)" if shot_num is not None else ""

    msg = (
        f"🎮 **WINGO {game_type.upper()}** (Mode: {mode})\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📅 **Period:** `{period}`\n"
        f"🎲 **PREDICTION:** {color} **{pred.upper()}** {color}\n"
        f"💰 **Wager:** Level {lvl} (x{unit})\n"
        f"🛡️ **Advice:** {rec_text}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"{logic_expl}{num_display}\n\n"
        f"👇 _Did you win?_"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="feedback_win"), 
         InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss")]
    ])
    
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    outcome = query.data.split("_")[1] # 'win' or 'loss'
    
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    curr_lvl = user_data.get("current_level", 1)
    
    # Level Management
    if outcome == "win":
        new_lvl = 1
        status_txt = "🎉 **WIN REGISTERED!** Resetting to Level 1."
    else:
        new_lvl = min(curr_lvl + 1, MAX_LEVEL)
        status_txt = f"📉 **LOSS.** Martingale: Increasing to Level {new_lvl}."
        
    update_user_field(user_id, "current_level", new_lvl)
    
    await query.edit_message_text(f"{status_txt}\n🔄 **Calculating Next Period...**")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- TARGET COMMAND FLOW ---
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data.get("target_session"):
        await update.message.reply_text("⚠️ **Active Session Found.**\nResuming your progress...", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Resume ▶️", callback_data="target_resume")]]))
        return TARGET_START_MENU 

    if not user_data.get("target_access"):
        await update.message.reply_text("❌ **Access Denied.**\nYou need a Target Pack to use this feature. Visit the Shop.")
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ WINGO 30 SEC", callback_data="tgt_game_30s")],
        [InlineKeyboardButton("🕐 WINGO 1 MIN", callback_data="tgt_game_1m")]
    ])
    await update.message.reply_text("🎯 **TARGET SESSION SETUP**\nSelect the game you want to conquer:", reply_markup=kb)
    return TARGET_SELECT_GAME

async def start_target_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_type = "30s" if query.data == "tgt_game_30s" else "1m"
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    
    await query.edit_message_text(f"🔄 **Initializing Target Algorithm for {game_type.upper()}...**")
    
    session = start_target_session(user_id, user_data['target_access'], game_type)
    
    if not session:
        await query.edit_message_text("❌ **Initialization Failed.**\nCould not fetch API data. Try again later.")
        return ConversationHandler.END
        
    await display_target_step(query, session, "Started")
    return TARGET_GAME_LOOP

async def target_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_user_data(user_id).get("target_session")
    
    if not session:
        await query.edit_message_text("❌ **Error:** Session expired or invalid.")
        return ConversationHandler.END
        
    await display_target_step(query, session, "Resumed")
    return TARGET_GAME_LOOP

async def display_target_step(update_obj, session, status_text):
    """Rich Target GUI."""
    progress = generate_progress_bar(session['current_balance'], session['target_amount'])
    start_bal = session.get('start_balance', 1000) # Assuming 1000 start if missing
    profit = session['current_balance'] - start_bal
    profit_sign = "+" if profit >= 0 else ""
    
    pred = session['current_prediction']
    color = "🔴" if pred == "Big" else "🟢"
    
    msg = (
        f"🎯 **TARGET SESSION** ({status_text})\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📊 **Progress:** {progress}\n"
        f"💰 **Balance:** {session['current_balance']} / {session['target_amount']}\n"
        f"📈 **Profit:** {profit_sign}{profit}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🎰 **ROUND INFO**\n"
        f"📅 **Period:** `{session['current_period']}`\n"
        f"🎲 **BET:** {color} **{pred.upper()}** {color}\n"
        f"💵 **Amount:** {session['sequence'][session['current_level_index']]}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👇 _Update Result:_"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), 
         InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")]
    ])
    await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

async def target_game_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    outcome = query.data.replace("tgt_", "")
    
    # Process
    session, status = process_target_outcome(user_id, outcome)
    
    if status == "TargetReached":
        await query.edit_message_text(
            f"🏆 **MISSION ACCOMPLISHED!** 🏆\n\n"
            f"✅ **Final Balance:** {session['current_balance']}\n"
            f"🎯 **Target:** {session['target_amount']}\n\n"
            f"The session has ended successfully. Enjoy your profits!"
        )
        return ConversationHandler.END
    elif status == "Bankrupt":
        await query.edit_message_text("💀 **SESSION FAILED.**\n\nBalance hit 0. Better luck next time.")
        return ConversationHandler.END
    elif status == "Ended":
        await query.edit_message_text("❌ **Error.** Session data corrupted.")
        return ConversationHandler.END
        
    await display_target_step(query, session, "Active")
    return TARGET_GAME_LOOP

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 **Operation Cancelled.**\nReturning to main menu.")
    return ConversationHandler.END

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
    
    # Buy Handler
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

    # --- LAUNCH BACKGROUND SERVICES ---
    print("🚀 Starting Background Salt Cracker Service...")
    start_salt_service()

    print("✅ Bot is Online & Running...")
    app.run_polling()

if __name__ == "__main__":
    main()