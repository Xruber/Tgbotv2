import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_BROADCAST_MSG, ADMIN_GIFT_WAIT
from database import (
    get_total_users, 
    get_active_subs_count, 
    get_all_user_ids, 
    get_top_referrers,
    set_maintenance_mode,
    get_settings, 
    update_user_field, 
    create_gift_code
)

# Setup Logger
logger = logging.getLogger(__name__)

# --- MAIN ADMIN MENU ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens the Admin Control Panel with 7 exact buttons."""
    user_id = update.effective_user.id
    
    # 1. Permission Check
    if user_id != ADMIN_ID:
        await update.message.reply_text("🚫 **Access Denied.**")
        return
    
    # 2. Get Data
    total = get_total_users()
    active = get_active_subs_count()
    is_maint = get_settings().get("maintenance_mode", False)
    maint_status = "🔴 ON" if is_maint else "🟢 OFF"
    
    msg = (
        f"🔒 **ADMIN DASHBOARD**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Users: `{total}`\n"
        f"💎 VIPs: `{active}`\n"
        f"🔧 Maintenance: **{maint_status}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👇 **Select Action:**"
    )
    
    # 3. THE 7 BUTTONS LAYOUT
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Maintenance", callback_data="adm_maint_toggle"), InlineKeyboardButton("🎁 Gen Code", callback_data="adm_gift_menu")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"), InlineKeyboardButton("📊 Ref Stats", callback_data="adm_ref_stats")],
        [InlineKeyboardButton("🚫 Ban", callback_data="adm_ban_help"), InlineKeyboardButton("✅ Unban", callback_data="adm_unban_help")],
        [InlineKeyboardButton("❌ Cancel", callback_data="adm_close")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all Admin clicks."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id != ADMIN_ID: 
        await query.answer("🚫 Access Denied", show_alert=True)
        return
        
    await query.answer()
    data = query.data
    
    # --- 1. CANCEL ---
    if data == "adm_close":
        await query.message.delete()
        return ConversationHandler.END
        
    elif data == "adm_back":
        await admin_command(update, context)
        return ConversationHandler.END

    # --- 2. MAINTENANCE TOGGLE ---
    elif data == "adm_maint_toggle":
        # Check current state
        current = get_settings().get("maintenance_mode", False)
        # Flip it
        new_state = not current
        set_maintenance_mode(new_state)
        
        status_txt = "🔴 ENABLED" if new_state else "🟢 DISABLED"
        await query.edit_message_text(
            f"🛠 **MAINTENANCE UPDATED**\n"
            f"New Status: **{status_txt}**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]])
        )

    # --- 3. GEN CODE MENU ---
    elif data == "adm_gift_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Day", callback_data="adm_gen_1"), InlineKeyboardButton("3 Days", callback_data="adm_gen_3")],
            [InlineKeyboardButton("7 Days", callback_data="adm_gen_7"), InlineKeyboardButton("30 Days", callback_data="adm_gen_30")],
            [InlineKeyboardButton("🔙 Back", callback_data="adm_back")]
        ])
        await query.edit_message_text("🎁 **SELECT DURATION**\nChoose gift validity:", reply_markup=kb)

    # --- 3b. GEN CODE ACTION ---
    elif data.startswith("adm_gen_"):
        days = int(data.split("_")[2])
        seconds = days * 24 * 3600
        code = create_gift_code(f"Gift {days} Days", seconds)
        
        await query.edit_message_text(
            f"✅ **CODE CREATED!**\n"
            f"━━━━━━━━━━━━━━\n"
            f"🗝 Code: `{code}`\n"
            f"⏳ Duration: {days} Days\n"
            f"━━━━━━━━━━━━━━\n"
            f"User types: `/redeem {code}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]])
        )

    # --- 4. BROADCAST ---
    elif data == "adm_broadcast":
        await query.edit_message_text(
            "📢 **BROADCAST MODE**\n\n"
            "Reply with the message to send to ALL users.\n"
            "Type /cancel to stop."
        )
        return ADMIN_BROADCAST_MSG
        
    # --- 5. REF STATS ---
    elif data == "adm_ref_stats":
        await admin_referral_stats_command(update, context)

    # --- 6 & 7. BAN / UNBAN HELP ---
    elif data == "adm_ban_help":
        await query.edit_message_text(
            "🚫 **HOW TO BAN**\n\n"
            "Send this command in chat:\n"
            "`/ban USER_ID`\n\n"
            "Example: `/ban 123456789`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]])
        )

    elif data == "adm_unban_help":
        await query.edit_message_text(
            "✅ **HOW TO UNBAN**\n\n"
            "Send this command in chat:\n"
            "`/unban USER_ID`\n\n"
            "Example: `/unban 123456789`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]])
        )

# --- LOGIC FUNCTIONS (Broadcast, Ban, Etc) ---

async def admin_broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ADMIN_BROADCAST_MSG

async def admin_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    
    msg_text = update.message.text
    final_msg = f"📢 **ANNOUNCEMENT**\n━━━━━━━━━━━━━━\n{msg_text}"
    
    status = await update.message.reply_text("⏳ **Sending...**")
    count, blocked = 0, 0
    
    for user in get_all_user_ids():
        try:
            await context.bot.send_message(user['user_id'], final_msg, parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except: blocked += 1
            
    await status.edit_text(f"✅ **Sent:** {count}  ❌ **Blocked:** {blocked}")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# Legacy handlers to prevent import errors in main.py
async def gift_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END 

async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(context.args[0])
        update_user_field(uid, "is_banned", True)
        await update.message.reply_text(f"🚫 **Banned** User `{uid}`", parse_mode="Markdown")
    except: await update.message.reply_text("Usage: /ban ID")

async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uid = int(context.args[0])
        update_user_field(uid, "is_banned", False)
        await update.message.reply_text(f"✅ **Unbanned** User `{uid}`", parse_mode="Markdown")
    except: await update.message.reply_text("Usage: /unban ID")

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    refs = get_top_referrers(10)
    txt = "🏆 **TOP REFERRERS**\n\n"
    if not refs: txt += "No data found."
    else:
        for i, u in enumerate(refs):
            txt += f"{i+1}. `{u['user_id']}` - {u.get('referral_purchases',0)} Sales\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))
    else:
        await update.message.reply_text(txt, parse_mode="Markdown")
