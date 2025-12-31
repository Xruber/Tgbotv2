from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_data, update_user_field, increment_user_field
from api_helper import get_game_data
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome, get_v5_logic
from config import SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, MAX_LEVEL

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

async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 Wingo 30s", callback_data="game_30s"), InlineKeyboardButton("🕐 Wingo 1m", callback_data="game_1m")]
    ])
    await q.edit_message_text("📡 **SELECT GAME SOURCE**\nConnecting to live servers...", reply_markup=kb)
    return SELECTING_GAME_TYPE

async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["game_type"] = "30s" if q.data == "game_30s" else "1m"
    await q.edit_message_text("🔄 **Syncing with API...**\nAnalyzing recent patterns...")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Visually Rich Prediction Screen."""
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        uid = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        uid = update.effective_user.id

    ud = get_user_data(uid)
    gtype = context.user_data.get("game_type", "30s")
    
    period, hist = get_game_data(gtype)
    if not period:
        await msg_func("⚠️ **API Connection Failed.**\nRetrying...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data="select_game_type")]]))
        return ConversationHandler.END

    # --- TREND STRIP ---
    trend_viz = ""
    if hist:
        recent = hist[-6:] # Last 6
        for h in recent:
            trend_viz += "🔴" if h['o'] == "Big" else "🟢"
    else: trend_viz = "Scanning..."
    # -------------------

    mode = ud.get("prediction_mode", "V2")
    if mode == "V5":
        pred, pat, v5d = get_v5_logic(period, gtype)
        shot = v5d if ud.get("has_number_shot") else None
    else:
        pred, pat = process_prediction_request(uid, "win", api_history=hist)
        shot = get_number_for_outcome(pred) if ud.get("has_number_shot") else None

    update_user_field(uid, "current_prediction", pred)
    
    lvl = ud.get("current_level", 1)
    unit = get_bet_unit(lvl)
    
    # RISK BAR
    risk_pct = lvl / MAX_LEVEL
    risk_bar = draw_bar(risk_pct, length=8, style="risk")
    
    color = "🔴" if pred == "Big" else "🟢"
    shot_txt = f"\n🎯 **Shot:** `{shot}`" if shot is not None else ""

    msg = (
        f"🎮 **WINGO {gtype.upper()}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 **Period:** `{period}`\n"
        f"📊 **Trend:** {trend_viz}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔮 **PREDICTION:** {color} **{pred.upper()}** {color}\n"
        f"🧠 **Logic:** `{pat}`\n"
        f"🔥 **Risk Level:**\n{risk_bar}\n"
        f"{shot_txt}\n"
        f"⚖️ **Result?**"
        f"━━━━━━━━━━━━━━\n"
    )
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ WIN", callback_data="feedback_win"), InlineKeyboardButton("❌ LOSS", callback_data="feedback_loss")]])
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    out = q.data.split("_")[1]
    uid = q.from_user.id
    ud = get_user_data(uid)
    curr = ud.get("current_level", 1)
    
    if out == "win":
        increment_user_field(uid, "total_wins", 1)
        new_lvl = 1
        txt = "💰 **PROFIT SECURED!**"
    else:
        increment_user_field(uid, "total_losses", 1)
        new_lvl = min(curr + 1, MAX_LEVEL)
        txt = f"📉 **LOSS.** Martingale x{get_bet_unit(new_lvl)}"
        
    update_user_field(uid, "current_level", new_lvl)
    await q.edit_message_text(f"{txt}\n🔄 **Analyzing Market...**")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK