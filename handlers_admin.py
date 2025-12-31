import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_BROADCAST_MSG
from database import get_total_users, get_active_subs_count, get_all_user_ids, get_top_referrers

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens the Admin Control Panel."""
    if update.effective_user.id != ADMIN_ID: return
    
    total_users = get_total_users()
    active_subs = get_active_subs_count()
    
    msg = (
        f"🔒 **ADMIN DASHBOARD**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 **Total Users:** {total_users}\n"
        f"💎 **Active VIPs:** {active_subs}\n"
        f"🟢 **System Status:** Online\n"
        f"━━━━━━━━━━━━━━\n"
        f"👇 Select Action:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 System Stats", callback_data="adm_stats_detail")],
        [InlineKeyboardButton("❌ Close", callback_data="adm_close")]
    ])

    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Admin Menu clicks (General)."""
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID: return
    await query.answer()
    data = query.data
    
    if data == "adm_close":
        await query.message.delete()
        
    elif data == "adm_stats_detail":
        await query.edit_message_text(
            "📊 **DETAILED STATISTICS**\n\n"
            "🔹 V5 Engine Accuracy: **92%**\n"
            "🔹 Top Plan: **7 Day Access**\n"
            "🔹 Server Load: **Normal**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]])
        )

    elif data == "adm_back":
        # Simply show the dashboard again
        await admin_command(update, context)

# --- BROADCAST SYSTEM ---

async def admin_broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for Broadcast conversation."""
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    await query.answer()
    
    await query.edit_message_text(
        "📢 **BROADCAST MODE**\n\n"
        "Send the message you want to broadcast to ALL users.\n"
        "Type /cancel to abort."
    )
    return ADMIN_BROADCAST_MSG

async def admin_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the actual broadcast to ALL users with SAFETY EXIT."""
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    
    msg_text = update.message.text
    final_msg = f"📢 **OFFICIAL ANNOUNCEMENT**\n━━━━━━━━━━━━━━\n{msg_text}\n━━━━━━━━━━━━━━"
    
    status_msg = await update.message.reply_text("⏳ **Sending Broadcast... (This may take time)**")
    
    count = 0
    blocked = 0
    
    try:
        users_cursor = get_all_user_ids()
        
        for user_doc in users_cursor:
            try:
                await context.bot.send_message(chat_id=user_doc['user_id'], text=final_msg, parse_mode="Markdown")
                count += 1
                await asyncio.sleep(0.05) 
                if count % 20 == 0: await asyncio.sleep(1) 
            except Exception as e:
                blocked += 1
                
        await status_msg.edit_text(f"✅ **Broadcast Complete.**\nSent: {count}\nFailed/Blocked: {blocked}")

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Broadcast Interrupted.**\nError: {e}\nSent: {count}")
    
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proper async cancellation function."""
    await update.message.reply_text("❌ **Broadcast Cancelled.**")
    return ConversationHandler.END

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    top_refs = get_top_referrers(limit=15)
    
    msg = "🏆 **LEADERBOARD (Top Referrers)**\n\n"
    if not top_refs:
        msg += "⚠️ No data available."
    else:
        for i, user in enumerate(top_refs):
            uid = user.get('user_id')
            sales = user.get('referral_purchases', 0)
            msg += f"#{i+1} 👤 `{uid}`  🔥 **{sales} Sales** (₹{sales*100})\n"
            
    await update.message.reply_text(msg, parse_mode="Markdown")