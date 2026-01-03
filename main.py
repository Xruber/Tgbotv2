import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler
)
from config import BOT_TOKEN, LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, SHOP_MENU, WAITING_UTR, REDEEM_PROCESS
from handlers import (
    start_command, set_language, show_main_menu, start_prediction, 
    prediction_logic, handle_result, shop_menu, 
    profile_command, redeem_entry, redeem_process, 
    admin_panel, admin_callback, ban_command, 
    invite_command, packs_command, target_command, language_command, cancel
)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # --- MAIN CONVERSATION ---
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
                CallbackQueryHandler(profile_command, pattern="^nav_profile$"),
                CallbackQueryHandler(redeem_entry, pattern="^nav_redeem$"),
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$") # Universal Back
            ],
            
            PREDICTION_LOOP: [
                CallbackQueryHandler(prediction_logic, pattern="^game_"), 
                CallbackQueryHandler(handle_result, pattern="^res_"),
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$") # Fixes Stuck Logic
            ],
            
            SHOP_MENU: [
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$"),
                # Add buy logic handlers here
            ],
            
            REDEEM_PROCESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_process)
            ]
        },
        fallbacks=[CommandHandler("start", start_command), CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(conv)
    
    # --- COMMANDS ---
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("target", target_command))
    app.add_handler(CommandHandler("profile", profile_command))
    
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))

    print("🤖 V5 Pro Bot Online.")
    app.run_polling()

if __name__ == "__main__":
    main()
