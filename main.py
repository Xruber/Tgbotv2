import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# Import Config
from config import (
    BOT_TOKEN, SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, 
    SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
    TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP, 
    SURESHOT_MENU, SURESHOT_LOOP, ADMIN_BROADCAST_MSG, 
    ADMIN_GIFT_WAIT, LANGUAGES
)

# Import Database
from database import (
    get_user_data, update_user_field, is_subscription_active, 
    get_settings, redeem_gift_code
)

# Import Handlers
from handlers_users import stats_command, switch_command, set_mode, reset_command, invite_command, cancel
from handlers_game import select_game_type, start_game_flow, handle_feedback
from handlers_shop import packs_command, shop_callback, start_buy, confirm_sent, receive_utr, admin_action, target_command, target_resume, start_target_game, target_loop
from handlers_sureshot import sureshot_command, sureshot_start, sureshot_refresh, sureshot_outcome

# --- CORRECTED IMPORT BLOCK FOR ADMIN ---
from handlers_admin import (
    admin_command, admin_callback, admin_broadcast_entry, 
    admin_send_broadcast, cancel_broadcast, admin_referral_stats_command, 
    ban_user_command, unban_user_command, gift_generation
)

# --- LANGUAGE SELECTOR ---
async def set_language(update: Update, context):
    q = update.callback_query
    lang = q.data.split("_")[1]
    update_user_field(q.from_user.id, "language", lang)
    await q.answer(f"Language set to {lang}")
    await start_command(update, context)

# --- START ---
async def start_command(update: Update, context):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # 1. Ban Check
    if user_data.get("is_banned"):
        await update.message.reply_text(LANGUAGES.get("EN")["banned"])
        return ConversationHandler.END

    # 2. Maintenance Check (Skip for Admin)
    # REPLACE 123456789 WITH YOUR REAL ADMIN ID
    if get_settings().get("maintenance_mode") and user_id != 123456789: 
        await update.message.reply_text(LANGUAGES.get("EN")["maintenance"])
        return ConversationHandler.END

    # 3. Language Check
    if not user_data.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_EN"), InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_HI")]
        ])
        if update.callback_query:
            await update.callback_query.message.reply_text(LANGUAGES["EN"]["select_lang"], reply_markup=kb)
        else:
            await update.message.reply_text(LANGUAGES["EN"]["select_lang"], reply_markup=kb)
        return ConversationHandler.END

    # Normal Start Flow
    lang = user_data.get("language", "EN")
    # Fallback to EN if key missing
    txt = LANGUAGES.get(lang, LANGUAGES["EN"])
    
    msg = txt["welcome"].format(name=update.effective_user.first_name) + "\n\n🚀 **V5+ Engine Ready.**"
    
    buttons = [
        [InlineKeyboardButton("🚀 START PREDICTION", callback_data="select_game_type")],
        [InlineKeyboardButton("🛒 Shop", callback_data="shop_main"), InlineKeyboardButton("👤 Profile", callback_data="my_stats")]
    ]
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def redeem_command(update: Update, context):
    try:
        code = context.args[0]
        success, plan = redeem_gift_code(code, update.effective_user.id)
        if success: await update.message.reply_text(f"✅ **Code Redeemed!**\nPlan: {plan}")
        else: await update.message.reply_text("❌ Invalid Code.")
    except: await update.message.reply_text("Usage: /redeem CODE")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("ban", ban_user_command))
    app.add_handler(CommandHandler("unban", unban_user_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("refstats", admin_referral_stats_command))
    
    # Lang
    app.add_handler(CallbackQueryHandler(set_language, pattern="^lang_"))

    # Admin Conversation
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

    # Game Conversation
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_game_type, pattern="^select_game_type$")],
        states={
            SELECTING_GAME_TYPE: [CallbackQueryHandler(start_game_flow, pattern="^game_")],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^check_")]
        },
        fallbacks=[CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(pred_h)
    
    # Shop Conversation
    buy_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_buy, pattern="^start_prediction_flow$"), CallbackQueryHandler(start_buy, pattern="^buy_")],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(start_buy, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(confirm_sent, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]
        },
        fallbacks=[CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(buy_h)

    # Target Conversation
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command)],
        states={
            TARGET_START_MENU: [CallbackQueryHandler(target_resume, pattern="^target_resume$")],
            TARGET_SELECT_GAME: [CallbackQueryHandler(start_target_game, pattern="^tgt_game_")],
            TARGET_GAME_LOOP: [CallbackQueryHandler(target_loop, pattern="^tgt_")]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(target_h)

    # SureShot Conversation
    sureshot_h = ConversationHandler(
        entry_points=[CommandHandler("sureshot", sureshot_command)],
        states={
            SURESHOT_MENU: [CallbackQueryHandler(sureshot_start, pattern="^ss_start")],
            SURESHOT_LOOP: [
                CallbackQueryHandler(sureshot_refresh, pattern="^ss_refresh"),
                CallbackQueryHandler(sureshot_outcome, pattern="^ss_(win|loss)")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(sureshot_h)

    # Global Callbacks
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_(ok|no)_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(packs_command, pattern="^back_start"))
    app.add_handler(CallbackQueryHandler(stats_command, pattern="^my_stats"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))

    print("🤖 Bot Online (V5+ Pro Update)")
    app.run_polling()

if __name__ == "__main__":
    main()
