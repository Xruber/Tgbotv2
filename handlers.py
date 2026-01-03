import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import *
from api_helper import get_game_data, check_result_exists
from prediction_engine import get_v5_plus_prediction, get_bet_unit

# --- UTILS ---
def get_text(user_id, key):
    ud = get_user_data(user_id)
    lang = ud.get("language", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)

async def check_access(update, user_id):
    """Checks Ban, Maintenance, and Subscription/Trial."""
    if is_user_banned(user_id):
        await update.message.reply_text(get_text(user_id, "banned"))
        return False
    
    if is_maintenance_mode() and user_id != ADMIN_ID:
        await update.message.reply_text(get_text(user_id, "maintenance"))
        return False
        
    ud = get_user_data(user_id)
    
    # Check Subscription
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp") > time.time():
        return True
        
    # Check Free Trial (5 Mins)
    joined = ud.get("joined_at", 0)
    if (time.time() - joined) < 300: # 300 seconds = 5 mins
        return True
        
    return "EXPIRED"

# --- ENTRY POINTS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ud = get_user_data(user.id)
    
    # 1. If Language not set, ask for it
    if not ud.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"), 
             InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi")]
        ])
        await update.message.reply_text(TEXTS["en"]["welcome"], reply_markup=kb)
        return LANGUAGE_SELECT
        
    # 2. Go to Main Menu
    await show_main_menu(update, user.id)
    return MAIN_MENU

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = q.data.split("_")[1]
    update_user_field(q.from_user.id, "language", lang)
    await show_main_menu(update, q.from_user.id)
    return MAIN_MENU

async def show_main_menu(update_obj, user_id):
    txt = get_text(user_id, "menu_main")
    
    # Determine Status Display
    access = await check_access(update_obj, user_id)
    ud = get_user_data(user_id)
    
    if access == "EXPIRED":
        status_msg = get_text(user_id, "trial_ended")
    elif access == True:
        if ud.get("prediction_status") == "ACTIVE":
            status_msg = get_text(user_id, "plan_active") + "V5+"
        else:
            status_msg = get_text(user_id, "trial_active")
    else:
        return # Banned/Maintenance
        
    msg = f"{status_msg}\n\n{txt}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_pred"), callback_data="nav_pred")],
        [InlineKeyboardButton(get_text(user_id, "btn_shop"), callback_data="nav_shop"),
         InlineKeyboardButton(get_text(user_id, "btn_profile"), callback_data="nav_profile")],
        [InlineKeyboardButton(get_text(user_id, "btn_support"), url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])
    
    if isinstance(update_obj, Update):
        if update_obj.callback_query:
            await update_obj.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        else:
            await update_obj.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    
# --- PREDICTION LOOP ---
async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    acc = await check_access(update, uid)
    if acc == "EXPIRED":
        await q.edit_message_text("🔒 **Access Expired.**\nPlease buy a plan.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Buy Now", callback_data="nav_shop")]]))
        return MAIN_MENU
    elif acc is False: return ConversationHandler.END
    
    # Select Game Type
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 Wingo 30s", callback_data="game_30s"),
         InlineKeyboardButton("🕐 Wingo 1m", callback_data="game_1m")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_home")]
    ])
    await q.edit_message_text("📡 **Select Game Server:**", reply_markup=kb)
    return PREDICTION_LOOP

async def prediction_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    
    # Handle Back
    if q.data == "nav_home":
        await show_main_menu(update, uid)
        return MAIN_MENU
        
    # Handle Game Selection or Loop
    if "game_" in q.data:
        gtype = q.data.split("_")[1]
        context.user_data["gtype"] = gtype
    else:
        gtype = context.user_data.get("gtype", "30s")
        
    await q.answer("Analysing V5+ Confluence...")
    
    # 1. API Fetch
    period, history = get_game_data(gtype)
    if not period:
        await q.edit_message_text("⚠️ **API Connection Error.** Retrying...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data=f"game_{gtype}")]]))
        return PREDICTION_LOOP
        
    # 2. Generate Prediction
    pred, logic = get_v5_plus_prediction(period, history)
    
    # 3. Bet Amount
    ud = get_user_data(uid)
    lvl = ud.get("current_level", 1)
    amt = get_bet_unit(lvl)
    
    # 4. Display
    color = "🔴" if pred == "Big" else "🟢"
    context.user_data["current_period"] = period # Save for verification
    
    msg = (
        f"🎮 **WINGO {gtype.upper()}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 Period: `{period}`\n"
        f"🧠 Logic: `{logic}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔮 Prediction: {color} **{pred.upper()}**\n"
        f"💰 Bet: **Level {lvl} ({amt}x)**\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚠️ _Do not refresh until result is out._"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="res_win"), InlineKeyboardButton("❌ LOSS", callback_data="res_loss")],
        [InlineKeyboardButton("🔙 Stop", callback_data="nav_home")]
    ])
    
    try:
        await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    except:
        await q.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return PREDICTION_LOOP

async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    action = q.data.split("_")[1]
    gtype = context.user_data.get("gtype", "30s")
    target_period = context.user_data.get("current_period")
    
    # --- CRITICAL FIX: CHECK RESULT ---
    exists, real_outcome = check_result_exists(gtype, target_period)
    
    if not exists:
        await q.answer(get_text(uid, "wait_result"), show_alert=True)
        return PREDICTION_LOOP # Stay on same message
    
    # Result is out, process logic
    ud = get_user_data(uid)
    curr_lvl = ud.get("current_level", 1)
    
    if action == "win":
        increment_user_field(uid, "total_wins")
        update_user_field(uid, "current_level", 1) # Reset
        txt = "🎉 **WIN!** Balance Protected."
    else:
        increment_user_field(uid, "total_losses")
        new_lvl = min(curr_lvl + 1, MAX_LEVEL)
        update_user_field(uid, "current_level", new_lvl)
        txt = f"📉 **LOSS.** Martingale Level {new_lvl}."
        
    await q.answer(txt)
    # Recursively call prediction for NEXT period
    await prediction_logic(update, context)
    return PREDICTION_LOOP

# --- SHOP & ADMIN (Condensed) ---
async def shop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    kb = []
    for k, v in PREDICTION_PLANS.items():
        kb.append([InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"buy_{k}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="nav_home")])
    
    await q.edit_message_text("🛒 **VIP STORE**\nSelect a plan to unlock V5+ Engine:", reply_markup=InlineKeyboardMarkup(kb))
    return SHOP_MENU

async def process_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    plan_key = q.data.split("_")[1]
    plan = PREDICTION_PLANS[plan_key]
    
    msg = (
        f"🧾 **INVOICE**\n"
        f"📦 Plan: {plan['name']}\n"
        f"💵 Price: {plan['price']}\n\n"
        f"📲 **Pay via UPI:**\n`your-upi@okaxis`\n"
        f"(Or click button below to get QR)\n\n"
        f"⚠️ After paying, send the **UTR/Ref No.** here."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Show QR Code", callback_data="show_qr")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="nav_home")]
    ])
    await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    context.user_data["plan"] = plan_key
    return WAITING_UTR

async def handle_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    plan_key = context.user_data.get("plan")
    
    # Notify Admin
    msg = f"💳 **NEW ORDER**\n👤 User: `{uid}`\n📦 Plan: `{plan_key}`\n🔢 UTR: `{utr}`"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"adm_ok_{uid}_{plan_key}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"adm_no_{uid}")]
    ])
    await context.bot.send_message(ADMIN_ID, msg, reply_markup=kb, parse_mode="Markdown")
    
    await update.message.reply_text("✅ **Verification Pending.**\nYou will be notified shortly.")
    return ConversationHandler.END

# --- ADMIN COMMANDS ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Gen Code (1 Day)", callback_data="gen_1_day")],
        [InlineKeyboardButton("🔒 Toggle Maintenance", callback_data="toggle_maint")],
        [InlineKeyboardButton("👥 Stats", callback_data="adm_stats")]
    ])
    await update.message.reply_text("👮 **ADMIN PANEL**", reply_markup=kb)

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if data == "gen_1_day":
        code = create_gift_code("1_day")
        await q.message.reply_text(f"🎁 Code: `{code}`", parse_mode="Markdown")
        
    elif "adm_ok_" in data:
        parts = data.split("_")
        uid, plan_key = int(parts[2]), "_".join(parts[3:])
        plan = PREDICTION_PLANS[plan_key]
        expiry = time.time() + plan["duration_seconds"]
        update_user_field(uid, "prediction_status", "ACTIVE")
        update_user_field(uid, "expiry_timestamp", expiry)
        await context.bot.send_message(uid, f"🎉 **Plan Activated:** {plan['name']}")
        await q.edit_message_text("✅ Activated.")
