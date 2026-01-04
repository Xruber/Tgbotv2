import asyncio
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import *
from handlers_utils import check_status, get_text, display_main_menu, draw_bar

# --- START & NAVIGATION ---
@check_status
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    
    # Referral Tracking
    if context.args and not ud.get("referred_by"):
        try:
            ref_id = int(context.args[0])
            if ref_id != user_id: update_user_field(user_id, "referred_by", ref_id)
        except: pass

    if not ud.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"), 
             InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi")]
        ])
        await update.message.reply_text(TEXTS["en"]["welcome"], reply_markup=kb)
        return LANGUAGE_SELECT
    await display_main_menu(update, user_id, context)
    return MAIN_MENU

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await display_main_menu(update, update.effective_user.id, context)
    return MAIN_MENU

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = q.data.split("_")[1]
    update_user_field(q.from_user.id, "language", lang)
    await display_main_menu(update, q.from_user.id, context)
    return MAIN_MENU

# --- USER FEATURES ---
@check_status
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed Profile Stats."""
    if update.callback_query: await update.callback_query.answer()
    uid = update.effective_user.id
    ud = get_user_data(uid)
    
    wins = ud.get("total_wins", 0)
    losses = ud.get("total_losses", 0)
    total = wins + losses
    rate = (wins/total) if total > 0 else 0.0
    
    if total < 10: rank = "👶 Rookie"
    elif rate > 0.8: rank = "🎯 **Sniper**"
    elif rate > 0.6: rank = "💼 **Pro Trader**"
    else: rank = "🛠 **Grinder**"
    
    rate_bar = draw_bar(rate, 10, "blocks")
    
    msg = (
        f"👤 **PLAYER PROFILE**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏆 **Rank:** {rank}\n"
        f"🆔 ID: `{uid}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 **PERFORMANCE:**\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"📉 Win Rate: {int(rate*100)}%\n{rate_bar}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_home")]])
    
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU

@check_status
async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ud = get_user_data(uid)
    link = f"https://t.me/{context.bot.username}?start={uid}"
    sales = ud.get("referral_purchases", 0)
    
    msg = (
        f"🤝 **AFFILIATE PROGRAM**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 **Your Link:**\n`{link}`\n\n"
        f"💰 **Stats:**\n"
        f"👥 Sales: {sales}\n"
        f"💵 Earned: ₹{sales*100}\n"
        f"━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    update_user_field(uid, "total_wins", 0)
    update_user_field(uid, "total_losses", 0)
    await update.message.reply_text("🔄 **Stats Reset.**")

# --- REDEEM ---
@check_status
async def redeem_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await (update.callback_query.message if update.callback_query else update.message).reply_text("🎁 **Enter Code:**")
    return REDEEM_PROCESS

async def redeem_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    success, msg = redeem_code(update.effective_user.id, code)
    if success:
        await update.message.reply_text(f"✅ **Success!** {msg}")
        await display_main_menu(update, update.effective_user.id, context)
        return MAIN_MENU
    await update.message.reply_text("❌ Invalid.")
    return REDEEM_PROCESS

# --- ADMIN FUNCTIONS ---
@check_status
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Maintenance", callback_data="adm_maint")],
        [InlineKeyboardButton("🎁 Gen Code", callback_data="adm_gen")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")]
    ])
    await update.message.reply_text("👮 **ADMIN PANEL**", reply_markup=kb)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if "adm_ok_" in data:
        # PAYMENT APPROVAL + REF CREDIT
        parts = data.split("_")
        uid, item = int(parts[2]), "_".join(parts[3:])
        if item == NUMBER_SHOT_KEY: update_user_field(uid, "has_number_shot", True)
        elif item in TARGET_PACKS: update_user_field(uid, "target_access", item)
        elif item in PREDICTION_PLANS:
            expiry = time.time() + PREDICTION_PLANS[item]['duration_seconds']
            update_user_field(uid, "prediction_status", "ACTIVE")
            update_user_field(uid, "expiry_timestamp", expiry)
        
        # Credit Referrer
        ref = get_user_data(uid).get("referred_by")
        if ref: increment_user_field(ref, "referral_purchases", 1)
            
        await context.bot.send_message(uid, f"✅ **Activated:** {item}")
        await q.edit_message_text("✅ Approved")

    elif "adm_maint" in data:
        curr = is_maintenance_mode()
        set_maintenance_mode(not curr)
        await q.answer(f"Maintenance: {not curr}")
        
    elif "adm_gen" in data:
        code = create_gift_code("1_day")
        await q.message.reply_text(f"🎁 Code: `{code}`")

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    top = get_top_referrers(15)
    msg = "🏆 **TOP REFERRERS**\n\n" + "\n".join([f"#{i+1} `{u['user_id']}`: {u.get('referral_purchases',0)} Sales" for i, u in enumerate(top)])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        ban_user(int(context.args[0]), True)
        await update.message.reply_text("🚫 Banned.")
    except: pass

# --- BROADCAST ---
async def admin_broadcast_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("📢 **Send Message:**\n(Type /cancel to stop)")
    return ADMIN_BROADCAST_MSG

async def admin_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    users = get_all_user_ids()
    count = 0
    status = await update.message.reply_text("⏳ Sending...")
    for u in users:
        try: 
            await context.bot.send_message(u['user_id'], f"📢 **ANNOUNCEMENT**\n\n{msg}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await status.edit_text(f"✅ Sent to {count} users.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await display_main_menu(update, update.effective_user.id, context)
    return MAIN_MENU

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled")
    return ConversationHandler.END
