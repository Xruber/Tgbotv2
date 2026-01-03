import asyncio
import time
import random
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import *
from api_helper import get_game_data, check_result_exists
from prediction_engine import get_v5_logic, get_bet_unit
from target_engine import start_target_session, process_target_outcome

# --- DECORATOR: THE FIX FOR BAN/MAINTENANCE ---
def check_status(func):
    """Wraps every handler to check Ban/Maintenance FIRST."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # 1. Check Ban
        if is_user_banned(user_id):
            if update.callback_query: await update.callback_query.answer("🚫 BANNED", show_alert=True)
            else: await update.message.reply_text("🚫 **YOU ARE BANNED.**")
            return ConversationHandler.END
            
        # 2. Check Maintenance (Allow Admin)
        if is_maintenance_mode() and user_id != ADMIN_ID:
            if update.callback_query: await update.callback_query.answer("🛠 MAINTENANCE", show_alert=True)
            else: await update.message.reply_text("🛠 **SYSTEM UNDER MAINTENANCE.**")
            return ConversationHandler.END
            
        return await func(update, context, *args, **kwargs)
    return wrapper

def get_text(user_id, key):
    ud = get_user_data(user_id)
    lang = ud.get("language", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)

# --- START & MENU ---
@check_status
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    
    if not ud.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"), 
             InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi")]
        ])
        await update.message.reply_text(TEXTS["en"]["welcome"], reply_markup=kb)
        return LANGUAGE_SELECT
        
    await show_main_menu(update, user_id)
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
    
    # Status Line
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp") > time.time():
        status = f"💎 **VIP:** Active"
    elif (time.time() - ud.get("joined_at", 0)) < 300:
        status = f"⏳ **Trial:** Active (5m)"
    else:
        status = f"🔒 **Status:** Free/Expired"
        
    msg = f"{status}\n\n{txt}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_pred"), callback_data="nav_pred"),
         InlineKeyboardButton(get_text(user_id, "btn_target"), callback_data="nav_target_menu")], 
        [InlineKeyboardButton(get_text(user_id, "btn_shop"), callback_data="nav_shop"),
         InlineKeyboardButton(get_text(user_id, "btn_profile"), callback_data="nav_profile")],
        [InlineKeyboardButton(get_text(user_id, "btn_redeem"), callback_data="nav_redeem"),
         InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])
    
    if isinstance(update_obj, Update) and update_obj.callback_query:
        await update_obj.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update_obj.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU

# --- PROFILE & COMMANDS ---
@check_status
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows user stats."""
    if update.callback_query: await update.callback_query.answer()
    uid = update.effective_user.id
    ud = get_user_data(uid)
    
    wins = ud.get('total_wins', 0)
    losses = ud.get('total_losses', 0)
    total = wins + losses
    rate = int((wins/total)*100) if total > 0 else 0
    
    msg = (
        f"👤 **USER PROFILE**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{uid}`\n"
        f"🌍 Language: {ud.get('language')}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏆 Wins: **{wins}**\n"
        f"📉 Losses: **{losses}**\n"
        f"📊 Win Rate: **{rate}%**"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_home")]]), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")
    return MAIN_MENU

@check_status
async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = f"https://t.me/{context.bot.username}?start={update.effective_user.id}"
    await update.message.reply_text(f"🔗 **Invite Link:**\n`{link}`\n\nShare to earn rewards!")

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset language so prompt appears again
    update_user_field(update.effective_user.id, "language", None)
    return await start_command(update, context)

# --- REDEEM SYSTEM ---
@check_status
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
@check_status
async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 30s", callback_data="game_30s"), InlineKeyboardButton("🕐 1m", callback_data="game_1m")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_home")]
    ])
    await q.edit_message_text("📡 **Select Game Server:**", reply_markup=kb)
    return PREDICTION_LOOP

@check_status
async def prediction_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    
    if q.data == "nav_home": 
        await show_main_menu(update, uid)
        return MAIN_MENU
    
    gtype = q.data.split("_")[1] if "game_" in q.data else context.user_data.get("gtype", "30s")
    context.user_data["gtype"] = gtype
    
    period, history = get_game_data(gtype)
    if not period:
        await q.answer("⚠️ API Error", show_alert=True)
        return PREDICTION_LOOP
        
    pred, _, logic = get_v5_logic(period, gtype, history)
    context.user_data["current_period"] = period
    
    # NUMBER SHOT LOGIC
    ud = get_user_data(uid)
    shot_txt = ""
    if ud.get("has_number_shot"):
        if pred == "Big": num = random.choice([5,6,7,8,9])
        else: num = random.choice([0,1,2,3,4])
        shot_txt = f"\n🎯 **Shot:** `{num}`"

    color = "🔴" if pred == "Big" else "🟢"
    
    msg = (
        f"🎮 **WINGO {gtype}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 Period: `{period}`\n"
        f"🔮 Prediction: {color} **{pred.upper()}**\n"
        f"🧠 Logic: `{logic}`"
        f"{shot_txt}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚠️ Wait for result!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="res_win"), InlineKeyboardButton("❌ LOSS", callback_data="res_loss")],
        [InlineKeyboardButton("🔙 Stop", callback_data="nav_home")]
    ])
    try: await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    except: pass
    return PREDICTION_LOOP

@check_status
async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # Check if result exists
    exists, _ = check_result_exists(context.user_data.get("gtype"), context.user_data.get("current_period"))
    if not exists:
        await q.answer("⏳ Result not out yet!", show_alert=True)
        return PREDICTION_LOOP
    
    if "win" in q.data: increment_user_field(q.from_user.id, "total_wins")
    else: increment_user_field(q.from_user.id, "total_losses")
    
    await q.answer("Saved!")
    await prediction_logic(update, context)
    return PREDICTION_LOOP

# --- TARGET SYSTEM (6-Levels) ---
@check_status
async def target_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = get_user_data(q.from_user.id)
    if ud.get("target_session"):
        return await target_loop_handler(update, context) # Re-enter loop
        
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 30s", callback_data="tgt_start_30s"), InlineKeyboardButton("🕐 1m", callback_data="tgt_start_1m")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_home")]
    ])
    await q.edit_message_text("🎯 **TARGET SESSION**\nSelect Game:", reply_markup=kb)
    return TARGET_MENU

@check_status
async def start_target_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    ud = get_user_data(uid)
    
    access_key = ud.get("target_access") 
    if not access_key:
        await q.answer("🚫 Buy a Target Pack first!", show_alert=True)
        return TARGET_MENU
        
    gtype = "30s" if "30s" in q.data else "1m"
    sess = start_target_session(uid, access_key, gtype)
    
    if not sess:
        await q.answer("⚠️ API Error", show_alert=True)
        return TARGET_MENU
        
    await display_target_ui(q, sess)
    return TARGET_LOOP

async def display_target_ui(update_obj, sess):
    lvl = sess["current_level_index"] + 1
    try: bet = sess["sequence"][lvl-1]
    except: bet = sess["sequence"][-1]
    
    color = "🔴" if sess["current_prediction"] == "Big" else "🟢"
    
    msg = (
        f"🎯 **TARGET: {sess['target_amount']}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Balance: `{sess['current_balance']}`\n"
        f"🪜 Step: **{lvl}/6**\n"
        f"📅 Period: `{sess['current_period']}`\n"
        f"🔥 **BET: {color} {sess['current_prediction'].upper()}**\n"
        f"💵 **Amount: {bet}**\n"
        f"━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")],
        [InlineKeyboardButton("🔙 Exit", callback_data="nav_home")]
    ])
    await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

@check_status
async def target_loop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "nav_home": 
        await show_main_menu(update, q.from_user.id)
        return MAIN_MENU

    # If re-entering loop without clicking win/loss (e.g. from menu)
    if "tgt_" not in q.data:
         # Use stored session to display
         ud = get_user_data(q.from_user.id)
         if ud.get("target_session"):
             await display_target_ui(q, ud.get("target_session"))
             return TARGET_LOOP
         else:
             return await show_main_menu(update, q.from_user.id)

    sess, status = process_target_outcome(q.from_user.id, q.data.replace("tgt_", ""))
    
    if status == "TargetReached":
        await q.edit_message_text(f"🏆 **TARGET HIT!**\nFinal Balance: {sess['current_balance']}")
        return MAIN_MENU
    elif status == "Bankrupt":
        await q.edit_message_text("💀 **SESSION FAILED.**\nBalance too low.")
        return MAIN_MENU
        
    await display_target_ui(q, sess)
    return TARGET_LOOP

# --- SHOP & ADMIN ---
@check_status
async def shop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    kb = []
    for k, v in PREDICTION_PLANS.items():
        kb.append([InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"buy_{k}")])
    kb.append([InlineKeyboardButton("🎯 Target Packs", callback_data="shop_targets")])
    kb.append([InlineKeyboardButton(f"🎲 Number Shot ({NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="nav_home")])
    
    await q.edit_message_text("🛒 **VIP STORE**\nSelect an Item:", reply_markup=InlineKeyboardMarkup(kb))
    return SHOP_MENU

@check_status
async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if data == "nav_home": 
        await show_main_menu(update, q.from_user.id)
        return MAIN_MENU
        
    if data == "shop_targets":
        kb = []
        for k, v in TARGET_PACKS.items():
            kb.append([InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"buy_{k}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="nav_shop")])
        await q.edit_message_text("🎯 **TARGET PACKS**", reply_markup=InlineKeyboardMarkup(kb))
        return SHOP_MENU
    
    if data == "nav_shop":
        return await shop_menu(update, context)
        
    # Buy Process
    item_key = data.replace("buy_", "")
    msg = f"💳 **INVOICE**\nItem: {item_key}\n\nPay via UPI and send UTR."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="nav_shop")]])
    await q.edit_message_text(msg, reply_markup=kb)
    context.user_data["buying"] = item_key
    return WAITING_UTR

@check_status
async def handle_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    item = context.user_data.get("buying")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data=f"adm_ok_{uid}_{item}"),
         InlineKeyboardButton("❌ No", callback_data=f"adm_no_{uid}")]
    ])
    await context.bot.send_message(ADMIN_ID, f"💳 **Order**\nUser: {uid}\nItem: {item}\nUTR: {utr}", reply_markup=kb)
    await update.message.reply_text("✅ Verification Pending.")
    await show_main_menu(update, uid)
    return MAIN_MENU

# --- ADMIN ---
@check_status
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Toggle Maintenance", callback_data="adm_maint")],
        [InlineKeyboardButton("🎁 Gen Code", callback_data="adm_gen")]
    ])
    await update.message.reply_text("👮 Admin", reply_markup=kb)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if "adm_ok_" in data:
        parts = data.split("_")
        uid, item = int(parts[2]), "_".join(parts[3:])
        if item == NUMBER_SHOT_KEY: update_user_field(uid, "has_number_shot", True)
        elif item in TARGET_PACKS: update_user_field(uid, "target_access", item)
        elif item in PREDICTION_PLANS:
            expiry = time.time() + PREDICTION_PLANS[item]['duration_seconds']
            update_user_field(uid, "prediction_status", "ACTIVE")
            update_user_field(uid, "expiry_timestamp", expiry)
        await context.bot.send_message(uid, f"✅ **Activated:** {item}")
        await q.edit_message_text("✅ Approved")

    elif "adm_maint" in data:
        curr = is_maintenance_mode()
        set_maintenance_mode(not curr)
        await q.answer(f"Maintenance: {not curr}")
        
    elif "adm_gen" in data:
        # Generate 1 day code by default for quick access
        code = create_gift_code("1_day")
        await q.message.reply_text(f"🎁 Code: `{code}`")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        ban_user(int(context.args[0]), True)
        await update.message.reply_text("🚫 Banned.")
    except: pass
    
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Shortcut to target menu
    return await target_menu_entry(update, context)

async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Shortcut to shop
    return await shop_menu(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, update.effective_user.id)
    return MAIN_MENU
