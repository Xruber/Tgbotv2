import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_data, update_user_field, increment_user_field, is_subscription_active
from api_helper import get_game_data
from prediction_engine import get_v5_logic, get_bet_unit
from config import SELECTING_PLATFORM, SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, MAX_LEVEL, LANGUAGES

# --- HELPERS ---

def get_text(uid, key):
    """Fetches the correct translation for the user."""
    user_lang = get_user_data(uid).get("language", "EN")
    return LANGUAGES.get(user_lang, LANGUAGES["EN"]).get(key, LANGUAGES["EN"].get(key, key))

def draw_bar(percent, length=10, style="blocks"):
    """Generates a high-end text progress bar with emojis."""
    percent = max(0.0, min(1.0, percent))
    filled_len = int(length * percent)
    
    if style == "blocks":
        bar = "█" * filled_len + "░" * (length - filled_len)
    elif style == "risk":
        if percent < 0.4: c = "🟢"
        elif percent < 0.7: c = "🟡"
        else: c = "🔴"
        bar = c * filled_len + "⚪" * (length - filled_len)
    else:
        bar = "█" * filled_len + " " * (length - filled_len)
        
    return f"[{bar}] {int(percent * 100)}%"

# --- STEP 1: SELECT PLATFORM ---
async def select_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry Point: User selects the specific casino platform.
    """
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    ud = get_user_data(user_id)
    
    # 🔒 SUBSCRIPTION CHECK 🔒
    if not is_subscription_active(ud):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Buy Access", callback_data="shop_main")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_home")]
        ])
        await q.edit_message_text(
            "🚫 **ACCESS DENIED**\n\n"
            "This feature is available for **VIP Members** only.\n"
            "Please purchase a plan to unlock the V5+ Engine.",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Show Platform Options
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Tiranga", callback_data="plat_Tiranga"), InlineKeyboardButton("👑 RajaGames", callback_data="plat_Rajagames")],
        [InlineKeyboardButton("🛡️ TrustWin", callback_data="plat_TrustWin")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_home")]
    ])
    await q.edit_message_text("🏢 **SELECT PLATFORM**\nChoose the server you are playing on:", reply_markup=kb)
    return SELECTING_PLATFORM

# --- STEP 2: SELECT TIME ---
async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    # Check for back button from previous menu
    if q.data == "back_home": return ConversationHandler.END
    
    # Save Selected Platform
    platform = q.data.replace("plat_", "")
    context.user_data["platform"] = platform
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 30 Seconds", callback_data="game_30s"), InlineKeyboardButton("🕐 1 Minute", callback_data="game_1m")],
        [InlineKeyboardButton("🔙 Change Platform", callback_data="select_platform")]
    ])
    await q.edit_message_text(f"📡 **{platform.upper()} SERVER**\nSelect Time Mode:", reply_markup=kb)
    return SELECTING_GAME_TYPE

# --- STEP 3: INITIALIZE SESSION ---
async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    # Back Navigation
    if q.data == "select_platform":
        return await select_platform(update, context)

    # Set game type
    game_type = "30s" if q.data == "game_30s" else "1m"
    context.user_data["game_type"] = game_type
    platform = context.user_data.get("platform", "Tiranga")
    
    await q.edit_message_text(
        f"🔄 **Connecting to {platform}...**\n"
        f"⚙️ Calibrating V5+ Salt for {platform}...\n"
        f"📊 Analyzing History Trends..."
    )
    
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- STEP 4: SHOW PREDICTION ---
async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Visually Rich Prediction Screen.
    """
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        uid = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        uid = update.effective_user.id

    ud = get_user_data(uid)
    gtype = context.user_data.get("game_type", "30s")
    platform = context.user_data.get("platform", "Tiranga")
    
    # 1. Fetch Data (Specific Platform)
    period, hist = get_game_data(gtype, platform=platform)
    
    if not period:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry Connection", callback_data="select_game_type")]])
        await msg_func(f"⚠️ **API Error ({platform}).**\nCould not fetch latest period.", reply_markup=kb)
        return ConversationHandler.END

    # 2. V5+ Logic (Pass Platform for Salt)
    pred, pat, v5d = get_v5_logic(period, gtype, hist, platform=platform)
    
    # 3. Save State (CRITICAL FOR ANTI-CHEAT)
    update_user_field(uid, "current_prediction", pred)
    update_user_field(uid, "current_period", period)
    
    # 4. Generate Visuals
    
    # A. Trend Strip (Last 6 results)
    trend_viz = ""
    if hist:
        recent = hist[-6:] 
        for h in recent:
            trend_viz += "🔴" if h['o'] == "Big" else "🟢"
    else: trend_viz = "Scanning..."

    # B. Betting Info
    lvl = ud.get("current_level", 1)
    bet_amount = get_bet_unit(lvl)
    color = "🔴" if pred == "Big" else "🟢"
    
    # C. Risk Bar
    risk_pct = lvl / MAX_LEVEL
    risk_bar = draw_bar(risk_pct, length=8, style="risk")

    # 5. Build Message
    msg = (
        f"🎮 **{platform.upper()} {gtype}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 **Period:** `{period}`\n"
        f"📊 **Trend:** {trend_viz}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔮 **PICK:** {color} **{pred.upper()}**\n"
        f"🧠 **Logic:** `{pat}`\n"
        f"💰 **Bet:** Level {lvl} (x{bet_amount})\n"
        f"🔥 **Risk:**\n{risk_bar}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚡ _Verification Active_"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WON", callback_data="check_win"), InlineKeyboardButton("❌ LOSS", callback_data="check_loss")],
        [InlineKeyboardButton("🚪 Stop", callback_data="back_home")]
    ])
    
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

# --- STEP 5: VERIFY RESULT (ANTI-CHEAT) ---
async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    
    # Stop Button Logic
    if q.data == "back_home":
        await q.message.delete()
        await context.bot.send_message(uid, "⏹ **Session Stopped.**\nType /start to return.")
        return ConversationHandler.END

    ud = get_user_data(uid)
    bet_period = ud.get("current_period")
    bet_prediction = ud.get("current_prediction")
    gtype = context.user_data.get("game_type", "30s")
    platform = context.user_data.get("platform", "Tiranga")

    # Fetch History to verify result exists
    _, history = get_game_data(gtype, platform=platform)
    
    # Find the period we just bet on
    result_item = next((item for item in history if str(item['p']) == str(bet_period)), None)
    
    # 🚫 BLOCKING: If result not found yet
    if not result_item:
        txt = get_text(uid, "result_wait") 
        await q.answer(txt, show_alert=True)
        return WAITING_FOR_FEEDBACK 

    # Verify Outcome
    real_outcome = result_item['o'] 
    is_win = (real_outcome == bet_prediction)
    
    current_lvl = ud.get("current_level", 1)
    
    if is_win:
        increment_user_field(uid, "total_wins", 1)
        new_lvl = 1
        status_msg = get_text(uid, "win_msg").format(result=real_outcome)
    else:
        increment_user_field(uid, "total_losses", 1)
        new_lvl = min(current_lvl + 1, MAX_LEVEL)
        status_msg = get_text(uid, "loss_msg").format(result=real_outcome)
        
    update_user_field(uid, "current_level", new_lvl)
    
    await q.edit_message_text(f"{status_msg}\n\n🔄 **Analyzing Next Period...**")
    await asyncio.sleep(2) 
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK
