import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import *
from api_helper import get_game_data, check_result_exists
from prediction_engine import get_v5_logic, get_bet_unit
from target_engine import start_target_session, process_target_outcome

# --- UTILS ---
def get_text(user_id, key):
    ud = get_user_data(user_id)
    lang = ud.get("language", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)

async def check_access(update, user_id):
    if is_user_banned(user_id):
        await update.message.reply_text(get_text(user_id, "banned"))
        return False
    if is_maintenance_mode() and user_id != ADMIN_ID:
        await update.message.reply_text(get_text(user_id, "maintenance"))
        return False
    return True

# --- MENU HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ud = get_user_data(user.id)
    
    if not ud.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"), 
             InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi")]
        ])
        await update.message.reply_text(TEXTS["en"]["welcome"], reply_markup=kb)
        return LANGUAGE_SELECT
        
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
    txt = get_text(user_id, "main_menu")
    ud = get_user_data(user_id)
    
    # Status Logic
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp") > time.time():
        status = f"{get_text(user_id, 'plan_active')}V5 Pro ({get_remaining_time_str(ud)})"
    elif (time.time() - ud.get("joined_at", 0)) < 300:
        status = get_text(user_id, "trial_active")
    else:
        status = get_text(user_id, "trial_ended")
        
    msg = f"{status}\n\n{txt}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_pred"), callback_data="nav_pred")],
        [InlineKeyboardButton(get_text(user_id, "btn_shop"), callback_data="nav_shop"),
         InlineKeyboardButton(get_text(user_id, "btn_profile"), callback_data="nav_profile")],
        [InlineKeyboardButton(get_text(user_id, "btn_redeem"), callback_data="nav_redeem")],
        [InlineKeyboardButton(get_text(user_id, "btn_support"), url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])
    
    if isinstance(update_obj, Update) and update_obj.callback_query:
        await update_obj.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update_obj.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU

# --- FEATURES & COMMANDS ---
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /profile and button click."""
    if update.callback_query: await update.callback_query.answer()
    uid = update.effective_user.id
    ud = get_user_data(uid)
    msg = (
        f"👤 **USER PROFILE**\n"
        f"🆔 ID: `{uid}`\n"
        f"🌍 Lang: {ud.get('language')}\n"
        f"🏆 Wins: {ud.get('total_wins')}\n"
        f"📉 Losses: {ud.get('total_losses')}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_home")]]), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")
    return MAIN_MENU

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = f"https://t.me/{context.bot.username}?start={update.effective_user.id}"
    await update.message.reply_text(f"🔗 **Invite Link:**\n`{link}`\n\nShare to earn rewards!")

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset language so prompt appears again
    update_user_field(update.effective_user.id, "language", None)
    return await start_command(update, context)

# --- REDEEM SYSTEM ---
async def redeem_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await (update.callback_query.message if update.callback_query else update.message).reply_text(
        "🎁 **REDEEM CODE**\n\nEnter your Gift Code below:\nType /cancel to stop."
    )
    return REDEEM_PROCESS

async def redeem_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    success, msg = redeem_code(update.effective_user.id, code)
    if success:
        await update.message.reply_text(f"✅ **Success!** {msg} Unlocked.")
        await show_main_menu(update, update.effective_user.id)
        return MAIN_MENU
    else:
        await update.message.reply_text(f"❌ {msg}. Try again or /cancel.")
        return REDEEM_PROCESS

# --- PREDICTION ENGINE ---
async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await check_access(update, q.from_user.id): return MAIN_MENU
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 30s", callback_data="game_30s"), InlineKeyboardButton("🕐 1m", callback_data="game_1m")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_home")]
    ])
    await q.edit_message_text("📡 **Select Game:**", reply_markup=kb)
    return PREDICTION_LOOP

async def prediction_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "nav_home": 
        await show_main_menu(update, q.from_user.id)
        return MAIN_MENU
        
    gtype = q.data.split("_")[1] if "game_" in q.data else context.user_data.get("gtype", "30s")
    context.user_data["gtype"] = gtype
    
    period, history = get_game_data(gtype)
    if not period:
        await q.answer("⚠️ API Error", show_alert=True)
        return PREDICTION_LOOP

    pred, _, logic = get_v5_logic(period, gtype) # Simplified call
    context.user_data["current_period"] = period
    
    msg = (
        f"🎮 **WINGO {gtype}**\n"
        f"📅 Period: `{period}`\n"
        f"🔮 Prediction: **{pred}**\n"
        f"🧠 Logic: `{logic}`\n"
        f"⚠️ Wait for result!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="res_win"), InlineKeyboardButton("❌ LOSS", callback_data="res_loss")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_home")]
    ])
    try: await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    except: pass
    return PREDICTION_LOOP

async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "nav_home": return await show_main_menu(update, q.from_user.id)
    
    gtype = context.user_data.get("gtype")
    period = context.user_data.get("current_period")
    
    # Verify Result
    exists, _ = check_result_exists(gtype, period)
    if not exists:
        await q.answer(get_text(q.from_user.id, "wait_result"), show_alert=True)
        return PREDICTION_LOOP
        
    # Logic Outcome
    if "win" in q.data: increment_user_field(q.from_user.id, "total_wins")
    else: increment_user_field(q.from_user.id, "total_losses")
    
    await q.answer("Result Recorded!")
    await prediction_logic(update, context) # Next round
    return PREDICTION_LOOP

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Gen Code (1 Day)", callback_data="adm_gen_1_day")],
        [InlineKeyboardButton("🛠 Toggle Maint.", callback_data="adm_toggle_maint")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_menu")]
    ])
    await update.message.reply_text("👮 **ADMIN PANEL**", reply_markup=kb)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if "adm_gen_" in data:
        plan = data.replace("adm_gen_", "")
        code = create_gift_code(plan)
        await q.message.reply_text(f"🎁 Code: `{code}`", parse_mode="Markdown")
        
    elif "adm_toggle_maint" in data:
        curr = is_maintenance_mode()
        set_maintenance_mode(not curr)
        await q.answer(f"Maintenance: {'ON' if not curr else 'OFF'}")
        
    elif "adm_ban_menu" in data:
        await q.message.reply_text("Send: `/ban 12345678`")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        ban_user(target_id, True)
        await update.message.reply_text(f"🚫 User {target_id} Banned.")
    except:
        await update.message.reply_text("Usage: /ban <user_id>")

# --- TARGET & PACKS ---
async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows Shop."""
    if update.callback_query: await update.callback_query.answer()
    return await shop_menu(update, context)

async def shop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"buy_{k}")] for k,v in PREDICTION_PLANS.items()]
    kb.append([InlineKeyboardButton("🎯 Target Packs", callback_data="shop_target")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="nav_home")])
    
    msg = "🛒 **VIP STORE**\nUnlock full access:"
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return SHOP_MENU

async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows Target Menu."""
    # Add target logic here (omitted for brevity, similar to prediction)
    await update.message.reply_text("🎯 Target System Active") 

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, update.effective_user.id)
    return MAIN_MENU
