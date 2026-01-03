import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from config import BOT_TOKEN, LANGUAGE_SELECT, MAIN_MENU, PREDICTION_LOOP, SHOP_MENU, WAITING_UTR
from handlers import (
    start_command, set_language, show_main_menu, start_prediction, 
    prediction_logic, handle_result, shop_menu, process_buy, handle_utr,
    admin_panel, admin_callback_handler
)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Main Conversation Flow
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            LANGUAGE_SELECT: [CallbackQueryHandler(set_language, pattern="^lang_")],
            
            MAIN_MENU: [
                CallbackQueryHandler(start_prediction, pattern="^nav_pred$"),
                CallbackQueryHandler(shop_menu, pattern="^nav_shop$"),
                # Add Profile handler if needed
            ],
            
            PREDICTION_LOOP: [
                CallbackQueryHandler(prediction_logic, pattern="^game_"), # Select Game
                CallbackQueryHandler(prediction_logic, pattern="^game_30s$"), # Retry
                CallbackQueryHandler(handle_result, pattern="^res_"), # Win/Loss
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$") # Back
            ],
            
            SHOP_MENU: [
                CallbackQueryHandler(process_buy, pattern="^buy_"),
                CallbackQueryHandler(show_main_menu, pattern="^nav_home$")
            ],
            
            WAITING_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr)]
        },
        fallbacks=[CommandHandler("start", start_command)]
    )
    
    app.add_handler(conv)
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(gen_|adm_|toggle_)"))
    
    print("🤖 V5+ Bot Rebuilt & Online.")
    app.run_polling()

if __name__ == "__main__":
    main()
