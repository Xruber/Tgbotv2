import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_BROADCAST_MSG, ADMIN_GIFT_WAIT
from database import get_total_users, get_active_subs_count, get_all_user_ids, set_maintenance_mode, update_user_field, create_gift_code

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    msg = f"🔒 **ADMIN PANEL**\nStatus: Online"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"), InlineKeyboardButton("🎁 Create Gift", callback_data="adm_gift")],
        [InlineKeyboardButton("🛑 Maintenance ON", callback_data="adm_maint_on"), InlineKeyboardButton("🟢 Maintenance OFF", callback_data="adm_maint_off")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_help")]
    ])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID: return
    await q.answer()
    d = q.data
    
    if d == "adm_maint_on":
        set_maintenance_mode(True)
        await q.edit_message_text("🛑 **Maintenance Mode ENABLED.** Users cannot start new sessions.")
    elif d == "adm_maint_off":
        set_maintenance_mode(False)
        await q.edit_message_text("🟢 **Maintenance Mode DISABLED.**")
    elif d == "adm_gift":
        await q.edit_message_text("🎁 **Send Gift Duration (Days):**\nExample: `7` or `30`")
        return ADMIN_GIFT_WAIT
    elif d == "adm_ban_help":
        await q.edit_message_text("🚫 **To Ban:** Type `/ban user_id`\n✅ **To Unban:** Type `/unban user_id`")

async def gift_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        seconds = days * 24 * 3600
        code = create_gift_code("Gift Access", seconds)
        await update.message.reply_text(f"🎁 **Code Generated:**\n`{code}`\n\nUser can redeem with `/redeem {code}`")
    except:
        await update.message.reply_text("❌ Invalid number.")
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
