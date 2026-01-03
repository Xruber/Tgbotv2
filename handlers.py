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

# --- DECORATOR ---
def check_status(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if is_user_banned(user_id):
            if update.callback_query: await update.callback_query.answer("🚫 BANNED", show_alert=True)
            else: await update.message.reply_text("🚫 **YOU ARE BANNED.**")
            return ConversationHandler.END
        if is_maintenance_mode() and user_id != ADMIN_ID:
            if update.callback_query: await update.callback_query.answer("🛠 MAINTENANCE", show_alert=True)
            else: await update.message.reply_text("🛠 **SYSTEM UNDER MAINTENANCE.**")
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- HELPERS ---
async def check_subscription(update, user_id):
    ud = get_user_data(user_id)
    # 1. Active Plan
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp", 0) > time.time():
        return True
    # 2. Free Trial (5 Mins)
    if (time.time() - ud.get("joined_at", 0)) < 300:
        return True
    
    msg = "🔒 **VIP ACCESS REQUIRED**\n\nYour free trial has ended."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Buy Plan", callback_data="nav_shop")]])
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else: await update.message.reply_text(msg, reply_markup=kb)
    return False

def get_text(user_id, key):
    ud = get_user_data(user_id)
    lang = ud.get("language", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)

# --- MENU LOGIC (Fixed Signature) ---
async def _display_menu(update_obj, user_id, context):
    """Internal helper to render the menu."""
    txt = get_text(user_id, "main_menu")
    ud = get_user_data(user_id)
    
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp") > time.time():
        days = int((ud.get("expiry_timestamp") - time.time()) / 86400)
        status = f"💎 **VIP Active:** {days} Days"
    elif (time.time() - ud.get("joined_at", 0)) < 300:
        status = f"⏳ **Trial Active:** 5 Mins"
    else:
        status = f"🔒 **Status:** Expired"
        
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
        # Try edit, if fails (e.g. photo was there), delete and send
        try:
            await update_obj.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        except:
            await update_obj.callback_query.message.delete()
            await context.bot.send_message(user_id, msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await context.bot.send_message(user_id, msg, reply_markup=kb, parse_mode="Markdown")

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
    await _display_menu(update, user_id, context)
    return MAIN_MENU

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Back buttons."""
    if update.callback_query: await update.callback_query.answer()
    await _display_menu(update, update.effective_user.id, context)
    return MAIN_MENU

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = q.data.split("_")[1]
    update_user_field(q.from_user.id, "language", lang)
    await _display_menu(update, q.from_user.id, context)
    return MAIN_MENU

# --- PREDICTION ---
@check_status
async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await check_subscription(update, q.from_user.id): return MAIN_MENU
    
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
    
    # Check for Back Button FIRST
    if q.data == "nav_home": 
        await _display_menu(update, uid, context)
        return MAIN_MENU
    
    try:
        gtype = q.data.split("_")[1] if "game_" in q.data else context.user_data.get("gtype", "30s")
        context.user_data["gtype"] = gtype
        
        period, history = get_game_data(gtype)
        if not period:
            await q.answer("⚠️ API Error: Could not fetch data.", show_alert=True)
            return PREDICTION_LOOP
            
        pred, _, logic = get_v5_logic(period, gtype, history)
        context.user_data["current_period"] = period
        
        # Shot Logic
        ud = get_user_data(uid)
        shot_txt = ""
        if ud.get("has_number_shot"):
            num = random.choice([5,6,7,8,9]) if pred == "Big" else random.choice([0,1,2,3,4])
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
        await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        
    except Exception as e:
        await q.answer(f"System Error: {str(e)}", show_alert=True)
        await _display_menu(update, uid, context)
        return MAIN_MENU
        
    return PREDICTION_LOOP

@check_status
async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    exists, _ = check_result_exists(context.user_data.get("gtype"), context.user_data.get("current_period"))
    if not exists:
        await q.answer("⏳ Result not out yet!", show_alert=True)
        return PREDICTION_LOOP
    
    if "win" in q.data: increment_user_field(q.from_user.id, "total_wins")
    else: increment_user_field(q.from_user.id, "total_losses")
    
    await q.answer("Saved!")
    await prediction_logic(update, context) # Loop
    return PREDICTION_LOOP

# --- SHOP (FIXED IMAGE) ---
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
    
    await q.edit_message_text("🛒 **VIP STORE**", reply_markup=InlineKeyboardMarkup(kb))
    return SHOP_MENU

@check_status
async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if data == "nav_home": return await back_to_menu(update, context)
    if data == "nav_shop": return await shop_menu(update, context)
        
    if data == "shop_targets":
        kb = []
        for k, v in TARGET_PACKS.items():
            kb.append([InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"buy_{k}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="nav_shop")])
        await q.edit_message_text("🎯 **TARGET PACKS**", reply_markup=InlineKeyboardMarkup(kb))
        return SHOP_MENU
    
    # BUYING LOGIC - FIXED IMAGE SENDING
    if "buy_" in data:
        item_key = data.replace("buy_", "")
        context.user_data["buying"] = item_key
        
        caption = f"💳 **INVOICE**\n\nItem: {item_key}\n\nScan the QR below to Pay via UPI.\nThen send the UTR number here."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="nav_shop")]])
        
        # Delete text menu, send photo
        try: await q.message.delete()
        except: pass
        
        await context.bot.send_photo(
            chat_id=q.from_user.id,
            photo=PAYMENT_IMAGE_URL,
            caption=caption,
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return WAITING_UTR
    
    return SHOP_MENU

@check_status
async def handle_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    item = context.user_data.get("buying", "Unknown")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data=f"adm_ok_{uid}_{item}"),
         InlineKeyboardButton("❌ No", callback_data=f"adm_no_{uid}")]
    ])
    await context.bot.send_message(ADMIN_ID, f"💳 **Order**\nUser: {uid}\nItem: {item}\nUTR: {utr}", reply_markup=kb)
    await update.message.reply_text("✅ Verification Sent. Wait for approval.")
    await _display_menu(update, uid, context)
    return MAIN_MENU

# --- TARGET & PROFILE ---
@check_status
async def target_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = get_user_data(q.from_user.id)
    if ud.get("target_session"):
        return await target_loop_handler(update, context)
        
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 30s", callback_data="tgt_start_30s"), InlineKeyboardButton("🕐 1m", callback_data="tgt_start_1m")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_home")]
    ])
    await q.edit_message_text("🎯 **TARGET SESSION**", reply_markup=kb)
    return TARGET_MENU

@check_status
async def start_target_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    ud = get_user_data(uid)
    if not ud.get("target_access"):
        await q.answer("🚫 Buy a Target Pack first!", show_alert=True)
        return TARGET_MENU
    
    gtype = "30s" if "30s" in q.data else "1m"
    sess = start_target_session(uid, ud.get("target_access"), gtype)
    if not sess:
        await q.answer("API Error", show_alert=True)
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
        f"💰 Bal: `{sess['current_balance']}`\n"
        f"🪜 Step: **{lvl}/6**\n"
        f"🔥 **BET: {color} {sess['current_prediction'].upper()}**\n"
        f"💵 Amt: **{bet}**"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WIN", callback_data="tgt_win"), InlineKeyboardButton("❌ LOSS", callback_data="tgt_loss")],
        [InlineKeyboardButton("🔙 Exit", callback_data="nav_home")]
    ])
    try: await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    except: pass

@check_status
async def target_loop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "nav_home": return await back_to_menu(update, context)
    
    if "tgt_" in q.data:
        sess, stat = process_target_outcome(q.from_user.id, q.data.replace("tgt_", ""))
        if stat == "TargetReached":
            await q.edit_message_text(f"🏆 **TARGET HIT!**\nFinal: {sess['current_balance']}")
            return MAIN_MENU
        elif stat == "Bankrupt":
            await q.edit_message_text("💀 **FAILED.**")
            return MAIN_MENU
        await display_target_ui(q, sess)
        return TARGET_LOOP
    return TARGET_LOOP

@check_status
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    uid = update.effective_user.id
    ud = get_user_data(uid)
    msg = f"👤 **PROFILE**\nID: `{uid}`\nWins: {ud.get('total_wins',0)}\nLosses: {ud.get('total_losses',0)}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_home")]])
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU

# --- ADMIN & EXTRAS ---
@check_status
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Maintenance", callback_data="adm_maint")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")]
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

async def admin_broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("📢 **Enter Message:**")
    return ADMIN_BROADCAST_MSG

async def admin_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    users = get_all_user_ids()
    for u in users:
        try: await context.bot.send_message(u['user_id'], f"📢 {msg}")
        except: pass
    await update.message.reply_text("✅ Sent.")
    return ConversationHandler.END

# Wrappers for commands
async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE): return await shop_menu(update, context)
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE): return await target_menu_entry(update, context)
async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = f"https://t.me/{context.bot.username}?start={update.effective_user.id}"
    await update.message.reply_text(f"🔗 {link}")
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE): return await back_to_menu(update, context)
async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_field(update.effective_user.id, "language", None)
    return await start_command(update, context)
async def redeem_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await (update.callback_query.message if update.callback_query else update.message).reply_text("🎁 Enter Code:")
    return REDEEM_PROCESS
async def redeem_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    success, msg = redeem_code(update.effective_user.id, code)
    if success:
        await update.message.reply_text(f"✅ Unlocked: {msg}")
        await _display_menu(update, update.effective_user.id, context)
        return MAIN_MENU
    await update.message.reply_text("❌ Invalid.")
    return REDEEM_PROCESS
