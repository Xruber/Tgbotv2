import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler
)
# 1. IMPORT CONFIG STATES
from config import (
    BOT_TOKEN, LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, 
    SHOP_MENU, WAITING_UTR, REDEEM_PROCESS, TARGET_MENU, TARGET_LOOP,
    ADMIN_BROADCAST_MSG
)

# 2. IMPORT ALL HANDLERS
from handlers import (
    start_command, set_language, show_main_menu, start_prediction, 
    prediction_logic, handle_result, shop_menu, shop_callback,
    profile_command, redeem_entry, redeem_process, 
    admin_panel, admin_callback, ban_command, 
    invite_command, packs_command, target_command, language_command, cancel,
    target_menu_entry, start_target_game, target_loop_handler, handle_utr,
    admin_broadcast_entry, admin_send_broadcast, cancel_broadcast
)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # CENTRAL CONVERSATION HANDLER
    conv = ConversationHandler(
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
                CallbackQueryHandler(profile_command, pattern="^nav_profile$"),
                CallbackQueryHandler(redeem_entry, pattern="^nav_redeem$"),
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$") 
            ],
            
            PREDICTION_LOOP: [
                CallbackQueryHandler(prediction_logic, pattern="^game_"), 
                CallbackQueryHandler(handle_result, pattern="^res_"),
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$") 
            ],
            
            TARGET_MENU: [
                CallbackQueryHandler(start_target_game, pattern="^tgt_start_"),
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$")
            ],
            
            TARGET_LOOP: [
                CallbackQueryHandler(target_loop_handler, pattern="^tgt_"), # Win/Loss
                CallbackQueryHandler(target_loop_handler, pattern="^nav_home$") # Back
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
            ],
            
            # BROADCAST STATE
            ADMIN_BROADCAST_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_broadcast)
            ]
        },
        fallbacks=[
            CommandHandler("start", start_command), 
            CommandHandler("cancel", cancel),
            CommandHandler("admin", admin_panel)
        ]
    )
    
    app.add_handler(conv)
    
    # Global Commands
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("target", target_command))
    app.add_handler(CommandHandler("profile", profile_command))
    
    # Global Callbacks for Admin (Broadcast Entry is here)
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_(ok|no|maint|gen)"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_entry, pattern="^adm_broadcast$"))

    print("🤖 V5 Pro Bot Online.")
    app.run_polling()

if __name__ == "__main__":
    main()
