import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# Import Config & DB
from config import (
    BOT_TOKEN, ADMIN_ID, SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, 
    SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
    TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP, 
    SURESHOT_MENU, SURESHOT_LOOP, ADMIN_BROADCAST_MSG, 
    ADMIN_GIFT_WAIT, LANGUAGES
)
from database import (
    get_user_data, update_user_field, is_subscription_active, 
    get_settings, redeem_gift_code
)

# Import Handlers
from handlers_users import stats_command, switch_command, set_mode, reset_command, invite_command, cancel
from handlers_game import select_game_type, start_game_flow, handle_feedback
from handlers_shop import packs_command, shop_callback, start_buy, confirm_sent, receive_utr, admin_action, target_command, target_resume, start_target_game, target_loop
from handlers_sureshot import sureshot_command, sureshot_start, sureshot_refresh, sureshot_outcome
from handlers_admin import (
    admin_command, admin_callback, admin_broadcast_entry, 
    admin_send_broadcast, cancel_broadcast, admin_referral_stats_command, 
    ban_user_command, unban_user_command, gift_generation
)

# --- LANGUAGE & STARTUP ---
async def set_language(update: Update, context):
    q = update.callback_query
    lang = q.data.split("_")[1]
    update_user_field(q.from_user.id, "language", lang)
    await q.answer(f"Language set to {lang}")
    # Edit the language message directly into the Main Menu
    await start_command(update, context, edit_mode=True)

async def start_command(update: Update, context, edit_mode=False):
    """
    The Main Dashboard. 
    edit_mode=True means we edit the existing message (smoother).
    """
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # 1. Ban Check
    if user_data.get("is_banned"):
        txt = LANGUAGES.get("EN")["banned"]
        if update.callback_query: await update.callback_query.edit_message_text(txt)
        else: await update.message.reply_text(txt)
        return ConversationHandler.END

    # 2. Maintenance Check (Bypass for Admin)
    if get_settings().get("maintenance_mode") and user_id != ADMIN_ID: 
        txt = LANGUAGES.get("EN")["maintenance"]
        if update.callback_query: await update.callback_query.edit_message_text(txt)
        else: await update.message.reply_text(txt)
        return ConversationHandler.END

    # 3. Language Check
    if not user_data.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_EN"), InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_HI")]
        ])
        txt = LANGUAGES["EN"]["select_lang"]
        if update.callback_query: await update.callback_query.edit_message_text(txt, reply_markup=kb)
        else: await update.message.reply_text(txt, reply_markup=kb)
        return ConversationHandler.END

    # --- MAIN DASHBOARD UI ---
    lang = user_data.get("language", "EN")
    txt = LANGUAGES.get(lang, LANGUAGES["EN"])
    
    # Check Subscription Status for Badge
    sub_status = "💎 VIP Active" if is_subscription_active(user_data) else "🆓 Free Plan"
    
    msg = (
        f"🤖 **WINGO V5+ PRO**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👋 **Welcome, {update.effective_user.first_name}!**\n"
        f"🆔 ID: `{user_id}`\n"
        f"🏷️ Status: **{sub_status}**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔥 **Choose an Option:**"
    )
    
    # NEW ATTRACTIVE LAYOUT
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Prediction", callback_data="select_game_type")],
        [InlineKeyboardButton("🎯 Target Mode", callback_data="shop_target")], # Direct to Target Menu
        [InlineKeyboardButton("🛒 VIP Shop", callback_data="shop_main"), InlineKeyboardButton("👤 My Profile", callback_data="my_stats")],
        [InlineKeyboardButton("🎁 Redeem Code", callback_data="btn_redeem_hint"), InlineKeyboardButton("💬 Support", url="https://t.me/your_support_handle")]
    ])
    
    if update.callback_query:
        # If triggered by "Back" button, we edit.
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
        
    return ConversationHandler.END

async def back_home_handler(update: Update, context):
    """Universal Back Button Handler."""
    await start_command(update, context, edit_mode=True)
    return ConversationHandler.END

async def redeem_hint(update: Update, context):
    """Popup to tell user how to redeem."""
    await update.callback_query.answer("💡 Type /redeem CODE to use a gift code!", show_alert=True)

async def redeem_command(update: Update, context):
    """The actual command: /redeem G-12345"""
    user_id = update.effective_user.id
    try:
        code = context.args[0]
    except IndexError:
        await update.message.reply_text("❌ **Usage:** `/redeem CODE`\nExample: `/redeem GIFT-12345`", parse_mode="Markdown")
        return

    success, plan_name = redeem_gift_code(code, user_id)
    if success:
        await update.message.reply_text(f"🎉 **SUCCESS!**\n\n💎 **Plan Activated:** {plan_name}\n🚀 You can now use the bot!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ **Invalid or Expired Code.**")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 1. SIMPLE COMMANDS
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command)) # Ensure ADMIN_ID in config.py is correct!
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("ban", ban_user_command))
    app.add_handler(CommandHandler("unban", unban_user_command))
    
    # 2. LANG & NAV
    app.add_handler(CallbackQueryHandler(set_language, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(back_home_handler, pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(redeem_hint, pattern="^btn_redeem_hint$"))

    # 3. ADMIN CONVERSATION
    admin_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_")],
        states={
            ADMIN_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_broadcast)],
            ADMIN_GIFT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_generation)]
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast)],
        per_user=True
    )
    app.add_handler(admin_h)

    # 4. GAME CONVERSATION (Prediction)
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_game_type, pattern="^select_game_type$")],
        states={
            SELECTING_GAME_TYPE: [CallbackQueryHandler(start_game_flow, pattern="^game_")],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^check_")]
        },
        fallbacks=[CallbackQueryHandler(back_home_handler, pattern="^back_home$"), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(pred_h)
    
    # 5. SHOP CONVERSATION
    buy_h = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(shop_callback, pattern="^shop_"), # Main Shop Entry
            CallbackQueryHandler(start_buy, pattern="^buy_")       # Direct Buy Trigger
        ],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(start_buy, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(confirm_sent, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]
        },
        fallbacks=[CallbackQueryHandler(back_home_handler, pattern="^back_home$"), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(buy_h)

    # 6. TARGET CONVERSATION
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command), CallbackQueryHandler(target_command, pattern="^shop_target$")],
        states={
            TARGET_START_MENU: [CallbackQueryHandler(target_resume, pattern="^target_resume$")],
            TARGET_SELECT_GAME: [CallbackQueryHandler(start_target_game, pattern="^tgt_game_")],
            TARGET_GAME_LOOP: [CallbackQueryHandler(target_loop, pattern="^tgt_")]
        },
        fallbacks=[CallbackQueryHandler(back_home_handler, pattern="^back_home$"), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(target_h)

    # 7. EXTRAS
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_(ok|no)_")) # Payment Approval
    app.add_handler(CallbackQueryHandler(stats_command, pattern="^my_stats")) # Profile

    print("🤖 Bot Online (Dashboard Fixed + Payment Fix + Admin Fix)")
    app.run_polling()

if __name__ == "__main__":
    main()
