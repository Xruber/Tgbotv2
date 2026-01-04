from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from target_engine import start_sureshot_session, process_sureshot_loop
from config import SURESHOT_MENU, SURESHOT_LOOP

async def sureshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🧗 Start 30s Ladder", callback_data="ss_start_30s")],
        [InlineKeyboardButton("🧗 Start 1m Ladder", callback_data="ss_start_1m")]
    ]
    msg = (
        "🧗 **SURESHOT LADDER**\n"
        "━━━━━━━━━━━━━━\n"
        "🔥 **Goal:** 100 ➡️ 1000 (5 Steps)\n"
        "🧱 **Strategy:** Compounding (All-in)\n"
        "🔫 **Mode:** Sniper (Bets ONLY when V5 + Trend match)\n\n"
        "⚠️ _High Risk. If V5 and Trend disagree, we SKIP._"
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return SURESHOT_MENU

async def sureshot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    gtype = "30s" if "30s" in q.data else "1m"
    
    session = start_sureshot_session(q.from_user.id, gtype)
    if not session:
        await q.edit_message_text("❌ **API Error.** Please try again.")
        return ConversationHandler.END
        
    await show_sureshot_ui(q, session)
    return SURESHOT_LOOP

async def sureshot_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refreshes the scanner (Called when user clicks 'Scan Again')."""
    q = update.callback_query
    await q.answer("Scanning...")
    
    # Process with NO outcome (Just checking for new signal)
    session, status = process_sureshot_loop(q.from_user.id, outcome=None)
    await show_sureshot_ui(q, session)
    return SURESHOT_LOOP

async def sureshot_outcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Win/Loss buttons."""
    q = update.callback_query
    await q.answer()
    outcome = "win" if "win" in q.data else "loss"
    
    session, status = process_sureshot_loop(q.from_user.id, outcome=outcome)
    
    if status == "Completed":
        await q.edit_message_text("🏆 **LADDER COMPLETED!** 🏆\n\n✅ Turned 100 ➡️ 1000!\n🎉 Take a break.")
        return ConversationHandler.END
    elif status == "Failed":
        await q.edit_message_text("💀 **LADDER BROKEN.**\n\nLevel Failed. Try again.")
        return ConversationHandler.END
        
    await show_sureshot_ui(q, session)
    return SURESHOT_LOOP

async def show_sureshot_ui(update_obj, session):
    """Dynamic UI: Shows 'Scanning' or 'Bet Now'."""
    lvl = session['current_level']
    amt = session['current_bet_amount']
    period = session['current_period']
    
    # VISUALS
    progress = "🧗 " + ("✅" * (lvl-1)) + "⬜" * (6-lvl)
    
    if session['is_waiting_signal']:
        # SCANNING MODE
        msg = (
            f"{progress}\n"
            f"📡 **SCANNING MARKET...**\n"
            f"━━━━━━━━━━━━━━\n"
            f"🕒 Period: `{period}`\n"
            f"🔍 Status: **Waiting for Confluence...**\n"
            f"🤖 Logic: V5 ≠ Trend (Mismatch)\n\n"
            f"💤 _Bot is sleeping until 100% confirmation._"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Scan Next Period", callback_data="ss_refresh")]])
    else:
        # SIGNAL MODE
        pred = session['current_prediction']
        color = "🔴" if pred == "Big" else "🟢"
        msg = (
            f"{progress}\n"
            f"🚨 **SURESHOT SIGNAL!**\n"
            f"━━━━━━━━━━━━━━\n"
            f"🕒 Period: `{period}`\n"
            f"🔥 **BET:** {color} **{pred.upper()}**\n"
            f"💰 **AMOUNT:** {amt}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🤖 **Confluence:**\n"
            f"✅ V5 Argon2i: **{pred}**\n"
            f"✅ Trend Analysis: **{pred}**\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ WON", callback_data="ss_win"), InlineKeyboardButton("❌ LOST", callback_data="ss_loss")],
            [InlineKeyboardButton("⏭ Skip", callback_data="ss_refresh")]
        ])

    await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")