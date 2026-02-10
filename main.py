import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# Import Config & DB
from config import (
    BOT_TOKEN, ADMIN_ID, SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, 
    SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
    TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP, 
    SURESHOT_MENU, SURESHOT_LOOP, ADMIN_BROADCAST_MSG, 
    ADMIN_GIFT_WAIT, LANGUAGES, SELECTING_PLATFORM
)
from database import (
    get_user_data, update_user_field, is_subscription_active, 
    get_settings, redeem_gift_code
)

# Import Handlers
from handlers_users import stats_command, switch_command, set_mode, reset_command, invite_command, cancel
from handlers_game import select_platform, select_game_type, start_game_flow, handle_feedback
from handlers_shop import packs_command, shop_callback, start_buy, confirm_sent, receive_utr, admin_action, target_command, target_resume, start_target_game, target_loop
from handlers_sureshot import sureshot_command, sureshot_start, sureshot_refresh, sureshot_outcome
from handlers_admin import (
    admin_command, admin_callback, admin_broadcast_entry, 
    admin_send_broadcast, cancel_broadcast, admin_referral_stats_command, 
    ban_user_command, unban_user_command, gift_generation
)

# NEW WALLET HANDLERS (renamed to avoid collision with Shop)
from handlers_wallet import (
    wallet_command, tokens_command, buy_token_confirm, view_token_chart,
    sell_menu, sell_token_confirm, admin_payment_handler,
    start_deposit, select_deposit_amount, show_qr_code, ask_utr, receive_utr as receive_dep_utr,
    start_withdraw, select_withdraw_method, ask_withdraw_details, process_withdrawal,
    DEP_AMOUNT, DEP_METHOD, DEP_UTR, WD_AMOUNT, WD_METHOD, WD_DETAILS,
    token_rig_command, token_roi_list_command
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- LANGUAGE & STARTUP ---
async def set_language(update: Update, context):
    q = update.callback_query
    lang = q.data.split("_")[1]
    update_user_field(q.from_user.id, "language", lang)
    await q.answer(f"Language set to {lang}")
    await start_command(update, context, edit_mode=True)

async def start_command(update: Update, context, edit_mode=False):
    uid = update.effective_user.id
    ud = get_user_data(uid)
    
    # 1. Ban Check
    if ud.get("is_banned"):
        await update.message.reply_text("🚫 **Access Denied.**\nYou are banned.")
        return ConversationHandler.END

    # 2. Maintenance Check
    if get_settings().get("maintenance_mode") and uid != ADMIN_ID: 
        await update.message.reply_text("🛠 **Maintenance Mode**\nBot is currently under update.")
        return ConversationHandler.END

    # 3. Language Check
    if not ud.get("language"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_EN"), InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_HI")]
        ])
        await update.message.reply_text("🌐 **Select Language:**", reply_markup=kb)
        return ConversationHandler.END

    # --- DASHBOARD ---
    sub_status = "💎 VIP Active" if is_subscription_active(ud) else "🆓 Free Plan"
    
    msg = (
        f"🤖 **WINGO V5+ PRO**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👋 **Welcome, {update.effective_user.first_name}!**\n"
        f"🆔 ID: `{uid}`\n"
        f"🏷️ Status: **{sub_status}**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔥 **Main Menu:**"
    )
    
    # Updated Wallet Callback to 'wallet_main'
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Prediction", callback_data="select_platform")],
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet_main"), InlineKeyboardButton("🛒 Shop", callback_data="shop_main")],
        [InlineKeyboardButton("🎯 Target Mode", callback_data="shop_target"), InlineKeyboardButton("👤 Profile", callback_data="my_stats")],
        [InlineKeyboardButton("🎁 Redeem Code", callback_data="btn_redeem_hint")]
    ])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
        
    return ConversationHandler.END

async def back_home_handler(update: Update, context):
    await start_command(update, context, edit_mode=True)
    return ConversationHandler.END

async def redeem_hint(update: Update, context):
    await update.callback_query.answer("💡 Type /redeem CODE to use a gift code!", show_alert=True)

async def redeem_command(update: Update, context):
    try:
        success, name = redeem_gift_code(context.args[0], update.effective_user.id)
        if success: await update.message.reply_text(f"✅ **Success!** Plan: {name}")
        else: await update.message.reply_text("❌ Invalid Code")
    except: await update.message.reply_text("Usage: /redeem CODE")

# --- CUSTOMER CARE STUB ---
async def cc_command(update: Update, context):
    await update.message.reply_text(f"💬 **Support:**\nContact @{ADMIN_ID} (Admin)")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 1. COMMANDS
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command)) 
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("ban", ban_user_command))
    app.add_handler(CommandHandler("unban", unban_user_command))
    app.add_handler(CommandHandler("stats", stats_command)) 
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("sureshot", sureshot_command))
    
    # Wallet Commands (FIXED UNDERSCORES)
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("token_rig", token_rig_command))
    app.add_handler(CommandHandler("token_roi_list", token_roi_list_command))
    
    # 2. GLOBAL HANDLERS
    app.add_handler(CallbackQueryHandler(set_language, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(back_home_handler, pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(redeem_hint, pattern="^btn_redeem_hint$"))
    
    # Admin Callbacks (Shop & Wallet)
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_(ok|no)_")) 
    app.add_handler(CallbackQueryHandler(admin_payment_handler, pattern="^adm_(dep|wd)_"))

    # 3. CONVERSATION HANDLERS
    
    common_fallbacks = [
        CallbackQueryHandler(back_home_handler, pattern="^back_home$"),
        CommandHandler("start", start_command),
        CommandHandler("admin", admin_command),
        CommandHandler("cancel", cancel)
    ]

    # A. ADMIN DASHBOARD
    admin_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_")],
        states={
            ADMIN_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_broadcast)],
            ADMIN_GIFT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_generation)]
        },
        fallbacks=common_fallbacks,
        per_user=True
    )
    app.add_handler(admin_h)

    # B. PREDICTION (Platform -> Game -> Feedback)
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_platform, pattern="^select_platform$")],
        states={
            SELECTING_PLATFORM: [CallbackQueryHandler(select_game_type, pattern="^plat_")],
            SELECTING_GAME_TYPE: [CallbackQueryHandler(start_game_flow, pattern="^game_")],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^check_")]
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    app.add_handler(pred_h)
    
    # C. SHOP (Buying Plans)
    buy_h = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(shop_callback, pattern="^shop_"),
            CallbackQueryHandler(start_buy, pattern="^buy_") 
        ],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(start_buy, pattern="^buy_")],
            WAITING_FOR_PAYMENT_PROOF: [CallbackQueryHandler(confirm_sent, pattern="^sent$")],
            WAITING_FOR_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    app.add_handler(buy_h)

    # D. WALLET DEPOSIT (Amount -> Method -> UTR)
    dep_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_deposit, pattern="^start_deposit$")],
        states={
            DEP_AMOUNT: [CallbackQueryHandler(select_deposit_amount, pattern="^dep_amt_")],
            DEP_METHOD: [CallbackQueryHandler(show_qr_code, pattern="^dep_method_")],
            DEP_UTR: [
                CallbackQueryHandler(ask_utr, pattern="^dep_paid$"), 
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dep_utr)
            ]
        },
        fallbacks=[CallbackQueryHandler(wallet_command, pattern="^wallet_main$")],
        per_user=True
    )
    app.add_handler(dep_conv)

    # E. WALLET WITHDRAW (Pct -> Method -> Details)
    wd_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern="^start_withdraw$")],
        states={
            WD_AMOUNT: [CallbackQueryHandler(select_withdraw_method, pattern="^wd_amt_")],
            WD_METHOD: [CallbackQueryHandler(ask_withdraw_details, pattern="^wd_method_")],
            WD_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_withdrawal)]
        },
        fallbacks=[CallbackQueryHandler(wallet_command, pattern="^wallet_main$")],
        per_user=True
    )
    app.add_handler(wd_conv)

    # F. TARGET MODE
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command), CallbackQueryHandler(target_command, pattern="^shop_target$")],
        states={
            TARGET_START_MENU: [CallbackQueryHandler(target_resume, pattern="^target_resume$")],
            TARGET_SELECT_GAME: [CallbackQueryHandler(start_target_game, pattern="^tgt_game_")],
            TARGET_GAME_LOOP: [CallbackQueryHandler(target_loop, pattern="^tgt_")]
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    app.add_handler(target_h)

    # G. SURESHOT MODE
    sureshot_h = ConversationHandler(
        entry_points=[CommandHandler("sureshot", sureshot_command)],
        states={
            SURESHOT_MENU: [CallbackQueryHandler(sureshot_start, pattern="^ss_start")],
            SURESHOT_LOOP: [
                CallbackQueryHandler(sureshot_refresh, pattern="^ss_refresh"),
                CallbackQueryHandler(sureshot_outcome, pattern="^ss_(win|loss)")
            ]
        },
        fallbacks=common_fallbacks,
        allow_reentry=True
    )
    app.add_handler(sureshot_h)

    # 4. OTHER CALLBACKS
    app.add_handler(CallbackQueryHandler(stats_command, pattern="^my_stats")) 
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))
    
    # Wallet Standalone Callbacks (Registered with NEW patterns)
    app.add_handler(CallbackQueryHandler(wallet_command, pattern="^wallet_main$"))
    app.add_handler(CallbackQueryHandler(tokens_command, pattern="^wallet_tokens$"))
    app.add_handler(CallbackQueryHandler(view_token_chart, pattern="^view_chart_"))
    app.add_handler(CallbackQueryHandler(buy_token_confirm, pattern="^trade_buy_"))
    app.add_handler(CallbackQueryHandler(sell_menu, pattern="^wallet_sell$"))
    app.add_handler(CallbackQueryHandler(sell_token_confirm, pattern="^trade_sell_"))

    print("--------------------------------------------------")
    print(f"✅ Bot Online (Wallet Fixed + Charts Active)")
    print(f"🔑 ADMIN_ID loaded as: {ADMIN_ID}")
    print("--------------------------------------------------")
    
    app.run_polling()

if __name__ == "__main__":
    main()