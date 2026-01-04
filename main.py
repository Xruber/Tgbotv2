import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler
)
from config import (
    BOT_TOKEN, LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, 
    SHOP_MENU, WAITING_UTR, REDEEM_PROCESS, TARGET_MENU, TARGET_LOOP,
    ADMIN_BROADCAST_MSG
)
# IMPORT FROM SPLIT FILES
from handlers_user import (
    start_command, set_language, back_to_menu, stats_command,
    invite_command, reset_command, redeem_entry, redeem_process,
    admin_panel, admin_callback, admin_referral_stats_command, ban_command,
    admin_broadcast_entry, admin_send_broadcast, cancel_broadcast, cancel,
    language_command
)
from handlers_game import (
    start_prediction, prediction_logic, handle_result,
    target_menu_entry, start_target_game, target_loop_handler,
    shop_menu, shop_callback, handle_utr, packs_command, target_command
)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    main_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("language", language_command),
            CommandHandler("redeem", redeem_entry)
        ],
        states={
            LANGUAGE_SELECT: [CallbackQueryHandler(set_language, pattern="^lang_")],
            
            MAIN_MENU: [
                CallbackQueryHandler(start_prediction, pattern="^nav_pred$"),
                CallbackQueryHandler(shop_menu, pattern="^nav_shop$"),
                CallbackQueryHandler(target_menu_entry, pattern="^nav_target_menu$"),
                CallbackQueryHandler(stats_command, pattern="^nav_profile$"),
                CallbackQueryHandler(redeem_entry, pattern="^nav_redeem$"),
                CallbackQueryHandler(back_to_menu, pattern="^nav_home$") 
            ],
            
            PREDICTION_LOOP: [
                CallbackQueryHandler(prediction_logic, pattern="^game_"), 
                CallbackQueryHandler(handle_result, pattern="^res_"),
                CallbackQueryHandler(back_to_menu, pattern="^nav_home$") 
            ],
            
            TARGET_MENU: [
                CallbackQueryHandler(start_target_game, pattern="^tgt_start_"),
                CallbackQueryHandler(back_to_menu, pattern="^nav_home$")
            ],
            
            TARGET_LOOP: [
                CallbackQueryHandler(target_loop_handler, pattern="^tgt_"),
                CallbackQueryHandler(back_to_menu, pattern="^nav_home$")
            ],
            
            SHOP_MENU: [
                CallbackQueryHandler(shop_callback, pattern="^buy_"),
                CallbackQueryHandler(shop_callback, pattern="^shop_"),
                CallbackQueryHandler(shop_callback, pattern="^nav_"),
            ],
            
            WAITING_UTR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr)
            ],
            
            REDEEM_PROCESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_process)
            ]
        },
        # 🔥 CRITICAL FIX: All commands in fallbacks work INSTANTLY in any menu
        fallbacks=[
            CommandHandler("start", start_command), 
            CommandHandler("cancel", cancel),
            CommandHandler("packs", packs_command),
            CommandHandler("target", target_command),
            CommandHandler("language", language_command),
            CommandHandler("stats", stats_command),
            CommandHandler("invite", invite_command),
            CommandHandler("admin", admin_panel)
        ]
    )
    
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_entry, pattern="^adm_broadcast$")],
        states={
            ADMIN_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_broadcast)]
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast)]
    )
    
    app.add_handler(broadcast_conv)
    app.add_handler(main_conv)
    
    # Global Command Registration (for when not in conversation)
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("target", target_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("refs", admin_referral_stats_command))
    app.add_handler(CommandHandler("ban", ban_command))
    
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_(ok|no|maint|gen)"))

    print("🤖 V5 Pro Bot Online.")
    app.run_polling()

if __name__ == "__main__":
    main()
