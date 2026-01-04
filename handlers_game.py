import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import *
from api_helper import get_game_data, check_result_exists
from prediction_engine import get_v5_logic
from target_engine import start_target_session, process_target_outcome
from handlers_utils import check_status, check_subscription, display_main_menu, draw_bar

# --- PREDICTION GAME ---
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
    if q.data == "nav_home": 
        await display_main_menu(update, uid, context)
        return MAIN_MENU
    
    try:
        gtype = q.data.split("_")[1] if "game_" in q.data else context.user_data.get("gtype", "30s")
        context.user_data["gtype"] = gtype
        
        period, history = get_game_data(gtype)
        if not period:
            await q.answer("⚠️ API Error", show_alert=True)
            return PREDICTION_LOOP
            
        # Default V5 Engine
        pred, logic, _ = get_v5_logic(period, gtype, history)
        context.user_data["current_period"] = period
        
        # Number Shot Logic
        ud = get_user_data(uid)
        shot_txt = ""
        if ud.get("has_number_shot"):
            num = random.choice([5,6,7,8,9]) if pred == "Big" else random.choice([0,1,2,3,4])
            shot_txt = f"\n🎯 **Shot:** `{num}`"

        # Trend Visuals
        trend_viz = ""
        if history:
            for h in history[-6:]: trend_viz += "🔴" if h['o'] == "Big" else "🟢"

        risk_bar = draw_bar(0.2, 8, "risk")
        color = "🔴" if pred == "Big" else "🟢"
        
        msg = (
            f"🎮 **WINGO {gtype}**\n"
            f"━━━━━━━━━━━━━━\n"
            f"📅 Period: `{period}`\n"
            f"📊 Trend: {trend_viz}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🔮 Prediction: {color} **{pred.upper()}**\n"
            f"🧠 Logic: `{logic}`\n"
            f"🔥 Risk: {risk_bar}"
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
        await q.answer(f"Error: {e}", show_alert=True)
        return PREDICTION_LOOP
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
    await prediction_logic(update, context)
    return PREDICTION_LOOP

# --- TARGET SESSION ---
@check_status
async def target_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = get_user_data(q.from_user.id)
    if ud.get("target_session"): return await target_loop_handler(update, context)
    
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
    p_bar = draw_bar(sess['current_balance']/sess['target_amount'], 10)
    
    msg = (
        f"🎯 **TARGET: {sess['target_amount']}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Bal: `{sess['current_balance']}`\n"
        f"📊 Prog: {p_bar}\n"
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
    if q.data == "nav_home": return await display_main_menu(update, q.from_user.id, context)
    
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

# --- SHOP ---
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
    
    if data == "nav_home": return await display_main_menu(update, q.from_user.id, context)
    if data == "nav_shop": return await shop_menu(update, context)
    
    if data == "shop_targets":
        kb = [[InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"buy_{k}")] for k,v in TARGET_PACKS.items()]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="nav_shop")])
        await q.edit_message_text("🎯 **TARGET PACKS**", reply_markup=InlineKeyboardMarkup(kb))
        return SHOP_MENU
    
    if "buy_" in data:
        item_key = data.replace("buy_", "")
        context.user_data["buying"] = item_key
        caption = f"💳 **INVOICE**\n\nItem: {item_key}\n\nPay via UPI (Scan QR).\nSend UTR below."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="nav_shop")]])
        
        try: await q.message.delete()
        except: pass
        
        try: await context.bot.send_photo(chat_id=q.from_user.id, photo=PAYMENT_IMAGE_URL, caption=caption, reply_markup=kb, parse_mode="Markdown")
        except: await context.bot.send_message(chat_id=q.from_user.id, text=caption + "\n\n⚠️ Image failed.", reply_markup=kb, parse_mode="Markdown")
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
    await update.message.reply_text("✅ Verification Sent.")
    await display_main_menu(update, uid, context)
    return MAIN_MENU

# Command Wrappers
async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE): return await shop_menu(update, context)
async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE): return await target_menu_entry(update, context)
