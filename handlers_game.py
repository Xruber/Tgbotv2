import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_data, update_user_field, increment_user_field, is_subscription_active
from api_helper import get_game_data
from prediction_engine import get_v5_logic, get_bet_unit
from config import SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, MAX_LEVEL, LANGUAGES

# --- HELPER: GET TEXT BY LANGUAGE ---
def get_text(uid, key):
    """Fetches the correct translation for the user."""
    user_lang = get_user_data(uid).get("language", "EN")
    # Fallback to English if key is missing in target lang
    return LANGUAGES.get(user_lang, LANGUAGES["EN"]).get(key, LANGUAGES["EN"].get(key, key))

# --- STEP 1: SELECT GAME ---
async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point for the Prediction Flow.
    CRITICAL: Checks if user has an active subscription.
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

    # If Active: Show Game Options
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 Wingo 30s", callback_data="game_30s"), InlineKeyboardButton("🕐 Wingo 1m", callback_data="game_1m")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_home")]
    ])
    await q.edit_message_text("📡 **SELECT GAME SERVER**", reply_markup=kb)
    return SELECTING_GAME_TYPE

# --- STEP 2: INITIALIZE SESSION ---
async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    # Set game type in context
    game_type = "30s" if q.data == "game_30s" else "1m"
    context.user_data["game_type"] = game_type
    
    await q.edit_message_text(f"🔄 **Connecting to {game_type.upper()} API...**\nAnalyzing Hash & History Patterns...")
    
    # Proceed to first prediction
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- STEP 3: SHOW PREDICTION ---
async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generates the prediction interface.
    """
    # Determine message function (Edit vs Reply)
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        uid = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        uid = update.effective_user.id

    ud = get_user_data(uid)
    gtype = context.user_data.get("game_type", "30s")
    
    # 1. Fetch Live Data
    period, hist = get_game_data(gtype)
    if not period:
        # API Fail Retry
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry Connection", callback_data="select_game_type")]])
        await msg_func("⚠️ **API Error.**\nCould not fetch latest period.", reply_markup=kb)
        return ConversationHandler.END

    # 2. Generate Logic (V5+)
    # Note: V5 Logic uses SHA256 of the *next* period usually, or analyzes current to predict next.
    # Assuming get_v5_logic returns prediction for the 'period' passed to it.
    pred, pat, v5d = get_v5_logic(period, gtype, hist)
    
    # 3. Save State (CRITICAL FOR ANTI-CHEAT)
    update_user_field(uid, "current_prediction", pred)
    update_user_field(uid, "current_period", period)
    
    # 4. Betting Info
    lvl = ud.get("current_level", 1)
    bet_amount = get_bet_unit(lvl)
    color = "🔴" if pred == "Big" else "🟢"
    
    # 5. Build Message
    msg = (
        f"🎮 **WINGO {gtype.upper()}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 **Period:** `{period}`\n"
        f"🔮 **PICK:** {color} **{pred.upper()}**\n"
        f"🧠 **Logic:** `{pat}`\n"
        f"💰 **Bet:** Level {lvl} (x{bet_amount})\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚡ _Result Verification Active_"
    )
    
    # Buttons: "Check" buttons trigger the anti-cheat logic
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Check Win", callback_data="check_win"), InlineKeyboardButton("❌ Check Loss", callback_data="check_loss")],
        [InlineKeyboardButton("🚪 Stop & Return", callback_data="back_home")]
    ])
    
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

# --- STEP 4: VERIFY RESULT (ANTI-CHEAT) ---
async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Verifies if the result is actually out on the API.
    Auto-corrects user if they lie (or click wrong button).
    """
    q = update.callback_query
    uid = q.from_user.id
    
    # 1. Handle "Back/Stop"
    if q.data == "back_home":
        # We can't jump directly to start_command here easily without passing context properly, 
        # so we usually delete and let them type /start or send a fresh menu.
        # But per main.py logic, we can return END and main.py handles the "back_home" callback if we were in a Fallback.
        # Since we are inside a State, we need to manually trigger the back logic or just end.
        await q.message.delete()
        await context.bot.send_message(uid, "⏹ **Session Stopped.**\nType /start to return.")
        return ConversationHandler.END

    # 2. Get User State
    ud = get_user_data(uid)
    bet_period = ud.get("current_period")
    bet_prediction = ud.get("current_prediction")
    gtype = context.user_data.get("game_type", "30s")

    # 3. Fetch Live History (To check if result exists)
    _, history = get_game_data(gtype)
    
    # Look for the period we bet on in the history
    # API history items usually look like: {'p': '2024010101', 'r': 5, 'o': 'Big'}
    result_item = next((item for item in history if str(item['p']) == str(bet_period)), None)
    
    # 🚫 BLOCKING LOGIC: If result is not found yet
    if not result_item:
        txt = get_text(uid, "result_wait") # "⏳ Result not yet released..."
        await q.answer(txt, show_alert=True)
        return WAITING_FOR_FEEDBACK # Do not advance, stay on screen

    # 4. Result Found - Verify Outcome
    real_outcome = result_item['o'] # "Big" or "Small"
    is_win = (real_outcome == bet_prediction)
    
    # 5. Update Stats & Level
    current_lvl = ud.get("current_level", 1)
    
    if is_win:
        increment_user_field(uid, "total_wins", 1)
        new_lvl = 1
        # Msg: "💰 WIN CONFIRMED! Result: Big"
        status_msg = get_text(uid, "win_msg").format(result=real_outcome)
    else:
        increment_user_field(uid, "total_losses", 1)
        new_lvl = min(current_lvl + 1, MAX_LEVEL)
        # Msg: "📉 LOSS CONFIRMED. Result: Small"
        status_msg = get_text(uid, "loss_msg").format(result=real_outcome)
        
    update_user_field(uid, "current_level", new_lvl)
    
    # 6. Show Result & Auto-Advance
    await q.edit_message_text(f"{status_msg}\n\n🔄 **Analyzing Next Period...**")
    
    # Small delay for user to read result
    await asyncio.sleep(2) 
    
    # 7. Loop to Next Prediction
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK
