import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_data, update_user_field, increment_user_field
from api_helper import get_game_data
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome, get_v5_logic
from config import SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, MAX_LEVEL, LANGUAGES

# Helper for text
def get_text(uid, key):
    lang = get_user_data(uid).get("language", "EN")
    return LANGUAGES.get(lang, LANGUAGES["EN"]).get(key, key)

async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 Wingo 30s", callback_data="game_30s"), InlineKeyboardButton("🕐 Wingo 1m", callback_data="game_1m")]
    ])
    await q.edit_message_text("📡 **SELECT GAME SOURCE**", reply_markup=kb)
    return SELECTING_GAME_TYPE

async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["game_type"] = "30s" if q.data == "game_30s" else "1m"
    await q.edit_message_text("🔄 **Syncing with API...**")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        uid = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        uid = update.effective_user.id

    ud = get_user_data(uid)
    gtype = context.user_data.get("game_type", "30s")
    
    # 1. Fetch Data
    period, hist = get_game_data(gtype)
    if not period:
        await msg_func("⚠️ **API Error.** Retrying...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data="select_game_type")]]))
        return ConversationHandler.END

    # 2. V5+ Logic
    pred, pat, v5d = get_v5_logic(period, gtype, hist)
    
    # Save State for Verification
    update_user_field(uid, "current_prediction", pred)
    update_user_field(uid, "current_period", period) # Critical for Anti-Cheat
    
    lvl = ud.get("current_level", 1)
    color = "🔴" if pred == "Big" else "🟢"
    
    # 3. Display
    msg = (
        f"🎮 **WINGO {gtype.upper()}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 **Period:** `{period}`\n"
        f"🔮 **PICK:** {color} **{pred.upper()}**\n"
        f"🧠 **Logic:** `{pat}`\n"
        f"💰 **Bet:** Level {lvl} (x{get_bet_unit(lvl)})\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚡ _Wait for result before clicking!_"
    )
    
    # Button Logic: These buttons now trigger verification
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ WON", callback_data="check_win"), InlineKeyboardButton("❌ LOSS", callback_data="check_loss")]
    ])
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ANTI-CHEAT VERIFICATION LOGIC
    """
    q = update.callback_query
    uid = q.from_user.id
    ud = get_user_data(uid)
    gtype = context.user_data.get("game_type", "30s")
    
    # 1. What did we predict?
    bet_period = ud.get("current_period")
    bet_prediction = ud.get("current_prediction")
    
    # 2. Fetch Live History to Verify
    _, history = get_game_data(gtype)
    
    # 3. Find our period in history
    result_item = next((item for item in history if str(item['p']) == str(bet_period)), None)
    
    if not result_item:
        # Result not yet on server
        await q.answer(get_text(uid, "result_wait"), show_alert=True)
        return WAITING_FOR_FEEDBACK # Stay on same screen
        
    # 4. Result Found! Verify.
    real_outcome = result_item['o'] # "Big" or "Small"
    is_win = (real_outcome == bet_prediction)
    
    # Auto-Correct the user (Anti-Cheat)
    # Even if they clicked "check_loss" but they won, we give them the win.
    
    curr = ud.get("current_level", 1)
    
    if is_win:
        increment_user_field(uid, "total_wins", 1)
        new_lvl = 1
        txt = get_text(uid, "win_msg").format(result=real_outcome)
    else:
        increment_user_field(uid, "total_losses", 1)
        new_lvl = min(curr + 1, MAX_LEVEL)
        txt = get_text(uid, "loss_msg").format(result=real_outcome)
        
    update_user_field(uid, "current_level", new_lvl)
    
    await q.edit_message_text(f"{txt}\n🔄 **Analyzing Next...**")
    await asyncio.sleep(2) # Small delay for UX
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK
