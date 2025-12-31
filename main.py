import logging
import random
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# Import Configuration & DB
from config import BOT_TOKEN, ADMIN_BROADCAST_MSG, SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP, SURESHOT_MENU, SURESHOT_LOOP
from database import get_user_data, update_user_field, is_subscription_active

# Import Handlers
from handlers_users import stats_command, switch_command, set_mode, reset_command, invite_command, cancel
from handlers_admin import admin_command, admin_callback, admin_broadcast_entry, admin_send_broadcast, cancel_broadcast, admin_referral_stats_command
from handlers_game import select_game_type, start_game_flow, handle_feedback
from handlers_shop import packs_command, shop_callback, start_buy, confirm_sent, receive_utr, admin_action, target_command, target_resume, start_target_game, target_loop
from handlers_sureshot import sureshot_command, sureshot_start, sureshot_refresh, sureshot_outcome

# --- START COMMAND (Entry Point) ---
def draw_bar(percent, length=10, style="blocks"):
    """Generates a high-end text progress bar with emojis."""
    percent = max(0.0, min(1.0, percent))
    filled_len = int(length * percent)
    if style == "blocks": bar = "" * filled_len + "" * (length - filled_len)
    elif style == "risk":
        if percent < 0.4: c = ""
        elif percent < 0.7: c = ""
        else: c = ""
        bar = c * filled_len + "" * (length - filled_len)
    else: bar = "" * filled_len + " " * (length - filled_len)
    return f"[{bar}] {int(percent * 100)}%"

async def start_command(update: Update, context):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id) 
    
    # Referral Logic
    if context.args and not user_data.get("referred_by"):
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                update_user_field(user_id, "referred_by", referrer_id)
        except: pass

    active = is_subscription_active(user_data)
    
    #   DAILY LUCK METER
    today = datetime.datetime.now().day
    random.seed(user_id + today) # Fixed luck for the day
    luck_percent = random.uniform(0.45, 0.98)
    luck_bar = draw_bar(luck_percent, length=8, style="risk")
    random.seed()
    
    # SUBSCRIPTION HEALTH BAR
    if active:
        expiry = user_data.get("expiry_timestamp", 0)
        now = datetime.datetime.now().timestamp()
        # Assume 30 days max for bar visual
        total_dur = 30 * 24 * 3600
        rem = max(0, expiry - now)
        health_pct = min(1.0, rem / total_dur)
        health_bar = draw_bar(health_pct, length=6, style="blocks")
        status_txt = f" **Plan:** Active\n{health_bar}"
        main_btn = [InlineKeyboardButton(" START PREDICTION", callback_data="select_game_type")]
    else:
        status_txt = " **Plan:** Expired / Free"
        main_btn = [InlineKeyboardButton(" UNLOCK VIP ACCESS", callback_data="start_prediction_flow")]

    buttons = [
        [InlineKeyboardButton(" Community", url="https://t.me/your_community_link")],
        [InlineKeyboardButton(" Shop", callback_data="shop_main"), InlineKeyboardButton(" Profile", callback_data="my_stats")]
    ]
    buttons.insert(1, main_btn)
    
    msg = (
        f" **WINGO AI V5 PRO**\n"
        f"\n"
        f" Hello, **{update.effective_user.first_name}**!\n"
        f"{status_txt}\n"
        f" **Daily Luck:**\n{luck_bar}\n"
        f"\n"
        f" **Features:**\n"
        f" Live API (30s & 1m)\n"
        f" V5 Argon2i Engine\n"
        f" SureShot Ladder\n\n"
        f" **Main Menu:**"
    )
    
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    return ConversationHandler.END

def main():
    # Keep timeouts to prevent httpx errors in heavy loads
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    
    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command)) 
    app.add_handler(CommandHandler("stats", stats_command)) 
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("invite", invite_command)) 
    app.add_handler(CommandHandler("refstats", admin_referral_stats_command)) 
    
    # 1. Prediction Conversation
    pred_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_game_type, pattern="^select_game_type$")],
        states={
            SELECTING_GAME_TYPE: [CallbackQueryHandler(start_game_flow, pattern="^game_")],
            WAITING_FOR_FEEDBACK: [CallbackQueryHandler(handle_feedback, pattern="^feedback_")]
        },
        fallbacks=[CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(pred_h)
    
    # 2. Shop Conversation
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

    # 3. Target Session Conversation
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

    # 4. SureShot Ladder Conversation
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

    # 5. Broadcast Conversation
    broadcast_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_entry, pattern="^adm_broadcast$")],
        states={ADMIN_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel_broadcast)]
    )
    app.add_handler(broadcast_handler)

    # Global Callbacks
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_(ok|no)_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(packs_command, pattern="^back_start")) # Simple back
    app.add_handler(CallbackQueryHandler(stats_command, pattern="^my_stats"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))

    print("  Bot Online (Pro Version).")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()