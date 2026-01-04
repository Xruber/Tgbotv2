import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import get_user_data, is_user_banned, is_maintenance_mode

# --- DECORATOR: ACCESS CONTROL ---
def check_status(func):
    """Wraps handlers to check BAN and MAINTENANCE status first."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # 1. Check Ban
        if is_user_banned(user_id):
            if update.callback_query: await update.callback_query.answer("🚫 BANNED", show_alert=True)
            else: await update.message.reply_text("🚫 **YOU ARE BANNED.**")
            return ConversationHandler.END
            
        # 2. Check Maintenance (Bypass for Admin)
        if is_maintenance_mode() and user_id != ADMIN_ID:
            if update.callback_query: await update.callback_query.answer("🛠 MAINTENANCE", show_alert=True)
            else: await update.message.reply_text("🛠 **SYSTEM UNDER MAINTENANCE.**")
            return ConversationHandler.END
            
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- HELPERS ---
async def check_subscription(update, user_id):
    """Checks if user has active VIP or valid Free Trial."""
    ud = get_user_data(user_id)
    
    # 1. Active Plan
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp", 0) > time.time():
        return True
    
    # 2. Free Trial (5 Mins)
    if (time.time() - ud.get("joined_at", 0)) < 300:
        return True
    
    msg = "🔒 **VIP ACCESS REQUIRED**\n\nYour free trial has ended."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Buy Plan", callback_data="nav_shop")]])
    
    if update.callback_query: await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else: await update.message.reply_text(msg, reply_markup=kb)
    return False

def get_text(user_id, key):
    ud = get_user_data(user_id)
    lang = ud.get("language", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)

def draw_bar(percent, length=10, style="blocks"):
    """Visual Progress Bar."""
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

# --- MAIN MENU DISPLAY ---
async def display_main_menu(update_obj, user_id, context):
    txt = get_text(user_id, "main_menu")
    ud = get_user_data(user_id)
    
    if ud.get("prediction_status") == "ACTIVE" and ud.get("expiry_timestamp") > time.time():
        days = int((ud.get("expiry_timestamp") - time.time()) / 86400)
        status = f"💎 **VIP Active:** {days} Days"
    elif (time.time() - ud.get("joined_at", 0)) < 300:
        status = f"⏳ **Trial Active:** 5 Mins"
    else:
        status = f"🔒 **Status:** Expired"
        
    msg = f"{status}\n\n{txt}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_pred"), callback_data="nav_pred"),
         InlineKeyboardButton(get_text(user_id, "btn_target"), callback_data="nav_target_menu")], 
        [InlineKeyboardButton(get_text(user_id, "btn_shop"), callback_data="nav_shop"),
         InlineKeyboardButton(get_text(user_id, "btn_profile"), callback_data="nav_profile")],
        [InlineKeyboardButton(get_text(user_id, "btn_redeem"), callback_data="nav_redeem"),
         InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])
    
    if isinstance(update_obj, Update) and update_obj.callback_query:
        try: await update_obj.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        except: 
            await update_obj.callback_query.message.delete()
            await context.bot.send_message(user_id, msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await context.bot.send_message(user_id, msg, reply_markup=kb, parse_mode="Markdown")
