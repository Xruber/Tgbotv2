import asyncio
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_BROADCAST_MSG, ADMIN_GIFT_WAIT
from database import (
    get_total_users, 
    get_active_subs_count, 
    get_all_user_ids, 
    get_top_referrers,
    set_maintenance_mode, 
    update_user_field, 
    create_gift_code
)

# --- MAIN ADMIN MENU ---
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
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"), InlineKeyboardButton("🎁 Create Gift", callback_data="adm_gift")],
        [InlineKeyboardButton("🛑 Maint. ON", callback_data="adm_maint_on"), InlineKeyboardButton("🟢 Maint. OFF", callback_data="adm_maint_off")],
        [InlineKeyboardButton("📊 Ref Stats", callback_data="adm_ref_stats"), InlineKeyboardButton("🚫 Ban Help", callback_data="adm_ban_help")],
        [InlineKeyboardButton("❌ Close", callback_data="adm_close")]
    ])

    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Admin Menu clicks."""
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID: return
    await query.answer()
    data = query.data
    
    if data == "adm_close":
        await query.message.delete()
        
    elif data == "adm_broadcast":
        await query.edit_message_text(
            "📢 **BROADCAST MODE**\n\n"
            "Send the message you want to broadcast to ALL users.\n"
            "Type /cancel to abort."
        )
        return ADMIN_BROADCAST_MSG
        
    elif data == "adm_gift":
        await query.edit_message_text("🎁 **Send Gift Duration (Days):**\nExample: `7` or `30`")
        return ADMIN_GIFT_WAIT
        
    elif data == "adm_maint_on":
        set_maintenance_mode(True)
        await query.edit_message_text("🛑 **Maintenance Mode ENABLED.**\nUsers cannot start new sessions.")
        
    elif data == "adm_maint_off":
        set_maintenance_mode(False)
        await query.edit_message_text("🟢 **Maintenance Mode DISABLED.**")
        
    elif data == "adm_ban_help":
        await query.edit_message_text(
            "🚫 **BAN COMMANDS**\n\n"
            "To Ban: `/ban 123456789`\n"
            "To Unban: `/unban 123456789`",
            parse_mode="Markdown"
        )
        
    elif data == "adm_ref_stats":
        await admin_referral_stats_command(update, context)

# --- BROADCAST LOGIC (Restored) ---
async def admin_broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This is handled via callback return above, but kept for direct entry safety
    return ADMIN_BROADCAST_MSG

async def admin_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the actual broadcast to ALL users."""
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    
    msg_text = update.message.text
    final_msg = f"📢 **OFFICIAL ANNOUNCEMENT**\n━━━━━━━━━━━━━━\n{msg_text}\n━━━━━━━━━━━━━━"
    
    status_msg = await update.message.reply_text("⏳ **Sending Broadcast...**")
    
    count = 0
    blocked = 0
    users_cursor = get_all_user_ids()
    
    for user_doc in users_cursor:
        try:
            await context.bot.send_message(chat_id=user_doc['user_id'], text=final_msg, parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05) 
        except:
            blocked += 1
            
    await status_msg.edit_text(f"✅ **Broadcast Complete.**\nSent: {count}\nFailed: {blocked}")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ **Action Cancelled.**")
    return ConversationHandler.END

# --- NEW TOOLS (Gift, Ban, Stats) ---
async def gift_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    try:
        days = int(update.message.text)
        seconds = days * 24 * 3600
        code = create_gift_code("Gift Access", seconds)
        await update.message.reply_text(f"🎁 **Code Generated:**\n`{code}`\n\nUser can redeem with `/redeem {code}`")
    except:
        await update.message.reply_text("❌ Invalid number. Try again or /cancel.")
        return ADMIN_GIFT_WAIT
    return ConversationHandler.END

async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        update_user_field(target_id, "is_banned", True)
        await update.message.reply_text(f"🚫 User {target_id} **BANNED**.")
    except:
        await update.message.reply_text("Usage: /ban 123456789")

async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        update_user_field(target_id, "is_banned", False)
        await update.message.reply_text(f"✅ User {target_id} **UNBANNED**.")
    except:
        await update.message.reply_text("Usage: /unban 123456789")

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    top_refs = get_top_referrers(limit=15)
    msg = "🏆 **LEADERBOARD (Top Referrers)**\n\n"
    if not top_refs: msg += "⚠️ No data available."
    else:
        for i, user in enumerate(top_refs):
            uid = user.get('user_id')
            sales = user.get('referral_purchases', 0)
            msg += f"#{i+1} 👤 `{uid}`  🔥 **{sales} Sales**\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")
