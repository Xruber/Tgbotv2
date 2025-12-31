from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_data, update_user_field, is_subscription_active, increment_user_field, get_top_referrers
from config import REGISTER_LINK, ADMIN_ID

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Universal cancel command."""
    await update.message.reply_text("❌ **Cancelled.**")
    return ConversationHandler.END

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User Profile Card."""
    await show_user_stats(update, update.effective_user.id)

async def show_user_stats(update_obj, user_id):
    """Helper to display stats via message or callback."""
    ud = get_user_data(user_id)
    wins = ud.get("total_wins", 0)
    losses = ud.get("total_losses", 0)
    total = wins + losses
    rate = (wins/total) if total > 0 else 0.0
    
    if total < 10: rank = "👶 Rookie"
    elif rate > 0.8: rank = "🎯 **Sniper**"
    elif rate > 0.6: rank = "💼 **Pro Trader**"
    else: rank = "🛠 **Grinder**"
    
    # Visual bar
    filled = int(rate * 10)
    rate_bar = "🟢" * filled + "⚪" * (10 - filled)
    
    msg = (
        f"👤 **PLAYER PROFILE**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏆 **Rank:** {rank}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 **PERFORMANCE:**\n"
        f"✅ **Wins:** {wins}\n"
        f"❌ **Losses:** {losses}\n"
        f"📉 **Win Rate:**\n{rate_bar} {int(rate*100)}%\n"
        f"━━━━━━━━━━━━━━\n"
        f"💡 _Tip: Maintain >60% for profit._"
    )
    
    if isinstance(update_obj, Update) and update_obj.callback_query:
        await update_obj.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_start")]]))
    else:
        await update_obj.message.reply_text(msg, parse_mode="Markdown")

async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user_data(update.effective_user.id)
    if not is_subscription_active(user_data):
        await update.message.reply_text("🔒 **Premium Required.**\nPlease buy a plan to use advanced engines.")
        return
        
    curr = user_data.get("prediction_mode", "V2")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅ ' if curr=='V1' else ''}V1: Pattern Matcher", callback_data="set_mode_V1")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V2' else ''}V2: Streak/Switch (Balanced)", callback_data="set_mode_V2")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V3' else ''}V3: Random AI (Unpredictable)", callback_data="set_mode_V3")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V4' else ''}V4: Trend Follower (Safe)", callback_data="set_mode_V4")],
        [InlineKeyboardButton(f"{'✅ ' if curr=='V5' else ''}V5: Argon2i Hash (Safe)", callback_data="set_mode_V5")]
    ])
    await update.message.reply_text(
        f"⚙️ **PREDICTION ENGINE SETTINGS**\n\n"
        f"🔧 **Current Engine:** `{curr}`\n\n"
        f"📝 **Description:**\n"
        f"🔹 **V1:** Follows AABB, ABAB patterns.\n"
        f"🔹 **V2:** Standard level-based switching.\n"
        f"🔹 **V5:** Uses server hash salt analysis (Most Advanced).\n\n"
        f"👇 Select Engine:",
        reply_markup=kb, parse_mode="Markdown"
    )

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = update.callback_query.data.split("_")[-1]
    update_user_field(update.callback_query.from_user.id, "prediction_mode", mode)
    await update.callback_query.answer(f"Switched to {mode}")
    await update.callback_query.edit_message_text(f"✅ **Engine: {mode}**")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_field(user_id, "current_level", 1)
    update_user_field(user_id, "history", [])
    update_user_field(user_id, "current_prediction", "Small")
    await update.message.reply_text("🔄 **Session Reset.**\nHistory cleared and Betting Level reset to 1.")

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    bot_username = context.bot.username
    
    invite_link = f"https://t.me/{bot_username}?start={user_id}"
    sales = user_data.get("referral_purchases", 0)
    income = sales * 100  # Assuming 100 INR per sale
    
    await update.message.reply_text(
        f"🤝 **AFFILIATE PROGRAM**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 **Your Link:**\n`{invite_link}`\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 **Performance (This Month):**\n"
        f"👥 Referrals: **{sales}**\n"
        f"💰 Estimated Earnings: **₹{income}**\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"ℹ️ **How it works:**\n"
        f"1. Share your link with friends.\n"
        f"2. They buy a plan.\n"
        f"3. You earn **₹100** per sale!\n\n"
        f"💡 _Payouts are processed manually. DM Support to claim._"
        f"━━━━━━━━━━━━━━\n",
        parse_mode="Markdown"
    )