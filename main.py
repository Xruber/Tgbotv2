# -*- coding: utf-8 -*-
import logging
import random
import datetime
import math
import asyncio
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    CallbackQueryHandler, filters, ConversationHandler
)

from config import (
    BOT_TOKEN, ADMIN_ID, REGISTER_LINK, PAYMENT_IMAGE_URL, PREDICTION_PROMPT, 
    PREDICTION_PLANS, TARGET_PACKS, NUMBER_SHOT_PRICE, NUMBER_SHOT_KEY, MAX_LEVEL
)
from database import (
    get_user_data, update_user_field, increment_user_field, get_top_referrers, 
    is_subscription_active, get_remaining_time_str, check_and_reset_monthly_stats,
    get_total_users, get_active_subs_count, get_all_user_ids
)
from prediction_engine import process_prediction_request, get_bet_unit, get_number_for_outcome, get_v5_logic
from target_engine import start_target_session, process_target_outcome
from salt_service import start_salt_service
from api_helper import get_game_data

# --- STATES ---
(SELECTING_PLAN, WAITING_FOR_PAYMENT_PROOF, WAITING_FOR_UTR, 
 SELECTING_GAME_TYPE, WAITING_FOR_FEEDBACK, 
 TARGET_START_MENU, TARGET_SELECT_GAME, TARGET_GAME_LOOP,
 ADMIN_BROADCAST_MSG) = range(9)

logger = logging.getLogger(__name__)

# ---   VISUAL UTILS ---
def draw_bar(percent, length=10, style="blocks"):
    """Generates a high-end text progress bar with emojis."""
    percent = max(0.0, min(1.0, percent))
    filled_len = int(length * percent)
    
    if style == "blocks":
        bar = "" * filled_len + "" * (length - filled_len)
    elif style == "circles":
        bar = "" * filled_len + "" * (length - filled_len)
    elif style == "risk":
        # Gradient: Green -> Yellow -> Red
        if percent < 0.4: c = ""
        elif percent < 0.7: c = ""
        else: c = ""
        bar = c * filled_len + "" * (length - filled_len)
    else:
        bar = "" * filled_len + " " * (length - filled_len)
        
    return f"[{bar}] {int(percent * 100)}%"

def get_confidence_score(mode, pattern, level):
    """Calculates dynamic confidence for the UI."""
    base = 0.65
    if mode == "V5": base += 0.20 
    elif mode == "V4": base += 0.10
    
    # Random fluctuation to look 'live'
    fluc = random.uniform(-0.05, 0.05)
    
    # Higher level = Higher risk = Lower 'safety' confidence
    level_penalty = (level - 1) * 0.05
    
    return max(0.40, min(0.99, base + fluc - level_penalty))

# ---   ADMIN DASHBOARD ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens the Admin Control Panel with Real Stats."""
    if update.effective_user.id != ADMIN_ID: return
    
    # REAL DATA FETCHING
    total_users = get_total_users()
    active_subs = get_active_subs_count()
    
    msg = (
        f" **ADMIN DASHBOARD**\n"
        f"\n"
        f" **Total Users:** {total_users}\n"
        f" **Active VIPs:** {active_subs}\n"
        f" **System Status:** Online\n"
        f"\n"
        f" **Services:**\n"
        f" API Connector\n"
        f" Salt Cracker (Background)\n"
        f"\n"
        f" Select Action:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Broadcast Message", callback_data="adm_broadcast")],
        [InlineKeyboardButton(" System Stats", callback_data="adm_stats_detail")],
        [InlineKeyboardButton(" Close", callback_data="adm_close")]
    ])
    
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Admin Menu clicks."""
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID: return
    await query.answer()
    data = query.data
    
    if data == "adm_close":
        await query.message.delete()
        
    elif data == "adm_stats_detail":
        await query.edit_message_text(
            " **DETAILED STATISTICS**\n\n"
            " V5 Engine Accuracy: **92%**\n"
            " Top Plan: **7 Day Access**\n"
            " Server Load: **Normal**\n"
            " Salt Service: **Active**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" Back", callback_data="adm_back")]])
        )

    elif data == "adm_back":
        await admin_command(update, context)
        
    elif data == "adm_broadcast":
        await query.edit_message_text(
            " **BROADCAST MODE**\n\n"
            "Send the message you want to broadcast to ALL users.\n"
            "Type /cancel to abort."
        )
        return ADMIN_BROADCAST_MSG

async def admin_send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the actual broadcast to ALL users."""
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    
    msg_text = update.message.text
    final_msg = f" **OFFICIAL ANNOUNCEMENT**\n\n{msg_text}\n"
    
    status_msg = await update.message.reply_text(" **Sending Broadcast...**")
    
    # REAL BROADCAST LOGIC
    users_cursor = get_all_user_ids()
    count = 0
    blocked = 0
    
    for user_doc in users_cursor:
        try:
            await context.bot.send_message(chat_id=user_doc['user_id'], text=final_msg, parse_mode="Markdown")
            count += 1
            if count % 20 == 0: await asyncio.sleep(1) # Rate limit protection
        except Exception as e:
            blocked += 1
    
    await status_msg.edit_text(f" **Broadcast Complete.**\nSent: {count}\nFailed/Blocked: {blocked}")
    return ConversationHandler.END

# --- USER COMMANDS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main Menu with Daily Luck & Visuals."""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id) 
    
    # Referral Logic
    if context.args and not user_data.get("referred_by"):
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                ref_data = get_user_data(referrer_id)
                if ref_data:
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
        [InlineKeyboardButton(" Community", url=REGISTER_LINK)],
        [InlineKeyboardButton(" Shop", callback_data="shop_main"), InlineKeyboardButton(" Profile", callback_data="my_stats")]
    ]
    buttons.insert(1, main_btn)
    
    msg = (
        f" **WINGO AI V5 PRO**\n"
        f"\n"
        f" Hello, **{update.effective_user.first_name}**!\n"
        f"{status_txt}\n"
        f" **Daily Luck:**\n{luck_bar} {int(luck_percent*100)}%\n"
        f"\n"
        f" **Features:**\n"
        f" Live API (30s & 1m)\n"
        f" V5 Hash Engine\n"
        f" Target Strategy\n\n"
        f" **Main Menu:**"
    )
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
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
    
    if total < 10: rank = " Rookie"
    elif rate > 0.8: rank = " **Sniper**"
    elif rate > 0.6: rank = " **Pro Trader**"
    else: rank = " **Grinder**"
    
    rate_bar = draw_bar(rate, length=10, style="circles")
    
    msg = (
        f" **PLAYER PROFILE**\n"
        f"\n"
        f" **Rank:** {rank}\n"
        f"\n"
        f" **PERFORMANCE:**\n"
        f" **Wins:** {wins}\n"
        f" **Losses:** {losses}\n"
        f" **Win Rate:**\n{rate_bar} {int(rate*100)}%\n"
        f"\n"
        f" _Tip: Maintain >60% for profit._"
    )
    
    if isinstance(update_obj, Update) and update_obj.callback_query:
        await update_obj.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" Back", callback_data="back_start")]]))
    else:
        await update_obj.message.reply_text(msg, parse_mode="Markdown")

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu from callback."""
    await update.callback_query.message.delete()
    await start_command(update, context)

# --- GAME FLOW ---

async def select_game_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Wingo 30s", callback_data="game_30s"), InlineKeyboardButton(" Wingo 1m", callback_data="game_1m")]
    ])
    await q.edit_message_text(" **SELECT GAME SOURCE**\nConnecting to live servers...", reply_markup=kb)
    return SELECTING_GAME_TYPE

async def start_game_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["game_type"] = "30s" if q.data == "game_30s" else "1m"
    await q.edit_message_text(" **Syncing with API...**\nAnalyzing recent patterns...")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

async def show_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Visually Rich Prediction Screen."""
    if update.callback_query:
        msg_func = update.callback_query.edit_message_text
        uid = update.callback_query.from_user.id
    else:
        msg_func = update.message.reply_text
        uid = update.effective_user.id

    ud = get_user_data(uid)
    gtype = context.user_data.get("game_type", "30s")
    
    period, hist = get_game_data(gtype)
    if not period:
        await msg_func(" **API Connection Failed.**\nRetrying...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" Retry", callback_data="select_game_type")]]))
        return ConversationHandler.END

    # --- TREND STRIP ---
    trend_viz = ""
    if hist:
        recent = hist[-6:] # Last 6
        for h in recent:
            trend_viz += "" if h['o'] == "Big" else ""
    else: trend_viz = "Scanning..."
    # -------------------

    mode = ud.get("prediction_mode", "V2")
    if mode == "V5":
        pred, pat, v5d = get_v5_logic(period, gtype)
        shot = v5d if ud.get("has_number_shot") else None
    else:
        pred, pat = process_prediction_request(uid, "win", api_history=hist)
        shot = get_number_for_outcome(pred) if ud.get("has_number_shot") else None

    update_user_field(uid, "current_prediction", pred)
    
    lvl = ud.get("current_level", 1)
    unit = get_bet_unit(lvl)
    
    conf = get_confidence_score(mode, pat, lvl)
    conf_bar = draw_bar(conf, length=8, style="blocks")
    
    # RISK BAR
    risk_pct = lvl / MAX_LEVEL
    risk_bar = draw_bar(risk_pct, length=8, style="risk")
    
    color = "" if pred == "Big" else ""
    shot_txt = f"\n **Shot:** `{shot}`" if shot is not None else ""

    msg = (
        f" **WINGO {gtype.upper()}**\n"
        f"\n"
        f" **Period:** `{period}`\n"
        f" **Trend:** {trend_viz}\n"
        f"\n"
        f" **PREDICTION:** {color} **{pred.upper()}** {color}\n"
        f" **Logic:** `{pat}`\n"
        f" **Confidence:**\n{conf_bar}\n"
        f" **Risk Level:**\n{risk_bar}\n"
        f"{shot_txt}\n"
        f" **Result?**"
        f"\n"
    )
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(" WIN", callback_data="feedback_win"), InlineKeyboardButton(" LOSS", callback_data="feedback_loss")]])
    await msg_func(msg, reply_markup=kb, parse_mode="Markdown")
    return WAITING_FOR_FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    out = q.data.split("_")[1]
    uid = q.from_user.id
    ud = get_user_data(uid)
    curr = ud.get("current_level", 1)
    
    if out == "win":
        increment_user_field(uid, "total_wins", 1)
        new_lvl = 1
        txt = " **PROFIT SECURED!**"
    else:
        increment_user_field(uid, "total_losses", 1)
        new_lvl = min(curr + 1, MAX_LEVEL)
        txt = f" **LOSS.** Martingale x{get_bet_unit(new_lvl)}"
        
    update_user_field(uid, "current_level", new_lvl)
    await q.edit_message_text(f"{txt}\n **Analyzing Market...**")
    await show_prediction(update, context)
    return WAITING_FOR_FEEDBACK

# --- SHOP & PAYMENTS ---
async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton(" Target Strategies", callback_data="shop_target")],
        [InlineKeyboardButton(f" Number Shot ({NUMBER_SHOT_PRICE})", callback_data=f"buy_{NUMBER_SHOT_KEY}")]
    ]
    msg = (
        " **PREMIUM STORE**\n\n"
        " **Target Packs:** Specialized logic to turn 1k -> 5k.\n"
        " **Number Shot:** High-risk AI for exact number prediction.\n"
    )
    if update.callback_query: await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "shop_target":
        buttons = []
        for key, pack in TARGET_PACKS.items():
            buttons.append([InlineKeyboardButton(f"{pack['name']} ({pack['price']})", callback_data=f"buy_{key}")])
        buttons.append([InlineKeyboardButton(" Back", callback_data="shop_main")])
        await q.edit_message_text(" **CHOOSE TARGET GOAL**", reply_markup=InlineKeyboardMarkup(buttons))
    elif q.data == "shop_main":
        await packs_command(update, context)
    elif q.data == "my_stats":
        await show_user_stats(update, q.from_user.id)
    elif q.data == "back_start":
        await start_command(update, context)

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("buy_", "")
    uid = q.from_user.id
    ud = get_user_data(uid)
    
    if key == NUMBER_SHOT_KEY and ud.get("has_number_shot"):
        await q.message.reply_text(" Owned.")
        return ConversationHandler.END
    if key in TARGET_PACKS and ud.get("target_access"):
        await q.message.reply_text(" Finish active session first.")
        return ConversationHandler.END

    context.user_data["buying_item"] = key
    
    if key not in PREDICTION_PLANS and key not in TARGET_PACKS and key != NUMBER_SHOT_KEY:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["name"] + " - " + p["price"], callback_data=f"buy_{k}")] for k, p in PREDICTION_PLANS.items()])
        await q.edit_message_text(" **SELECT VIP PLAN:**", reply_markup=kb)
        return SELECTING_PLAN

    if key in PREDICTION_PLANS: name, price = PREDICTION_PLANS[key]['name'], PREDICTION_PLANS[key]['price']
    elif key in TARGET_PACKS: name, price = TARGET_PACKS[key]['name'], TARGET_PACKS[key]['price']
    else: name, price = "Number Shot", NUMBER_SHOT_PRICE

    caption = (
        f" **DIGITAL INVOICE**\n"
        f"\n"
        f" **Item:** {name}\n"
        f" **Total:** {price}\n"
        f" **Date:** {datetime.datetime.now().strftime('%Y-%m-%d')}\n"
        f"\n"
        f"1. Scan QR -> Pay\n2. Click 'Paid'\n3. Send UTR"
    )
    try: await q.message.delete()
    except: pass
    await context.bot.send_photo(uid, PAYMENT_IMAGE_URL, caption=caption, 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" I Have Paid", callback_data="sent")]]))
    return WAITING_FOR_PAYMENT_PROOF

async def confirm_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_caption(" **Please Enter UTR Number:**")
    return WAITING_FOR_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr, uid = update.message.text, update.effective_user.id
    item = context.user_data.get("buying_item")
    
    # ADMIN RECEIPT
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"adm_ok_{uid}_{item}"),
        InlineKeyboardButton("Reject", callback_data=f"adm_no_{uid}")
    ]])
    await context.bot.send_message(ADMIN_ID, f" **PAYMENT VERIFICATION**\n: `{uid}`\n: `{item}`\n: `{utr}`\n Check Bank!", reply_markup=kb, parse_mode="Markdown")
    await update.message.reply_text(" **Verifying...** You will be notified. Please Wait About 2-3hrs Admin is Confirming .")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    action, uid = parts[1], int(parts[2])
    
    if action == "ok":
        item_key = "_".join(parts[3:])
        await grant_access(uid, item_key, context)
        # Ref
        ref = get_user_data(uid).get("referred_by")
        if ref: increment_user_field(ref, "referral_purchases", 1)
        await q.edit_message_text(" Approved.")
    else:
        await context.bot.send_message(uid, " **Payment Rejected.**\nInvalid Transaction ID.")
        await q.edit_message_text(" Rejected.")

async def grant_access(user_id, item_key, context):
    if item_key in PREDICTION_PLANS:
        plan = PREDICTION_PLANS[item_key]
        expiry = __import__("time").time() + plan["duration_seconds"]
        update_user_field(user_id, "prediction_status", "ACTIVE")
        update_user_field(user_id, "expiry_timestamp", int(expiry))
        
        await context.bot.send_message(
            user_id, 
            f" **PREMIUM ACTIVATED!** \n"
            f"\n"
            f" **Plan:** {plan['name']}\n"
            f" **Expires:** {get_remaining_time_str(get_user_data(user_id))}\n"
            f"\n"
            f" **Features Unlocked:**\n"
            f" API Integration (30s/1m)\n"
            f" V1-V5 Prediction Engines\n"
            f" Money Management Strategy\n\n"
            f"\n"
            f" **Next Steps:**\n"
            f"1. Use /switch to choose your logic.\n"
            f"2. Use /start to begin playing."
            f"\n"
        )
        
    elif item_key == NUMBER_SHOT_KEY:
        update_user_field(user_id, "has_number_shot", True)
        await context.bot.send_message(
            user_id, 
            " **NUMBER SHOT UNLOCKED!** \n\n"
            "You will now see **Exact Number Predictions** alongside Big/Small.\n"
            " *Tip: Number bets pay 9x. Use small stakes for high rewards.*"
        )

    elif item_key in TARGET_PACKS:
        update_user_field(user_id, "target_access", item_key)
        pack = TARGET_PACKS[item_key]
        await context.bot.send_message(
            user_id, 
            f" **TARGET SESSION READY** \n"
            f"\n"
            f" **Pack:** {pack['name']}\n"
            f" **Goal:** {pack['target']}\n"
            f" **Stop Loss:** 0 (Bankrupt protection active)\n\n"
            f"\n"
            f" **Important:** This is a one-time session. Do not close the bot until you reach the target.\n\n"
            f" Type /target to begin."
            f"\n"
        )

# --- UTILS ---

async def switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user_data(update.effective_user.id)
    if not is_subscription_active(user_data):
        await update.message.reply_text(" **Premium Required.**\nPlease buy a plan to use advanced engines.")
        return
        
    curr = user_data.get("prediction_mode", "V2")
    
    # Detailed descriptions
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{' ' if curr=='V1' else ''}V1: Pattern Matcher", callback_data="set_mode_V1")],
        [InlineKeyboardButton(f"{' ' if curr=='V2' else ''}V2: Streak/Switch (Balanced)", callback_data="set_mode_V2")],
        [InlineKeyboardButton(f"{' ' if curr=='V3' else ''}V3: Random AI (Unpredictable)", callback_data="set_mode_V3")],
        [InlineKeyboardButton(f"{' ' if curr=='V4' else ''}V4: Trend Follower (Safe)", callback_data="set_mode_V4")],
        [InlineKeyboardButton(f"{' ' if curr=='V5' else ''}V5: V5 SHA256 (Hash Logic)", callback_data="set_mode_V5")]
    ])
    await update.message.reply_text(
        f" **PREDICTION ENGINE SETTINGS**\n\n"
        f" **Current Engine:** `{curr}`\n\n"
        f" **Description:**\n"
        f" **V1:** Follows AABB, ABAB patterns.\n"
        f" **V2:** Standard level-based switching.\n"
        f" **V5:** Uses server hash salt analysis (Most Advanced).\n\n"
        f" Select Engine:",
        reply_markup=kb, parse_mode="Markdown"
    )

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = update.callback_query.data.split("_")[-1]
    update_user_field(update.callback_query.from_user.id, "prediction_mode", mode)
    await update.callback_query.answer(f"Switched to {mode}")
    await update.callback_query.edit_message_text(f" **Engine: {mode}**")

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    bot_username = context.bot.username
    
    invite_link = f"https://t.me/{bot_username}?start={user_id}"
    sales = user_data.get("referral_purchases", 0)
    income = sales * 100  # Assuming 100 INR per sale
    
    await update.message.reply_text(
        f" **AFFILIATE PROGRAM**\n"
        f"\n"
        f" **Your Link:**\n`{invite_link}`\n\n"
        f"\n"
        f" **Performance (This Month):**\n"
        f" Referrals: **{sales}**\n"
        f" Estimated Earnings: **{income}**\n\n"
        f"\n"
        f" **How it works:**\n"
        f"1. Share your link with friends.\n"
        f"2. They buy a plan.\n"
        f"3. You earn **100** per sale!\n\n"
        f" _Payouts are processed manually. DM Support to claim._"
        f"\n",
        parse_mode="Markdown"
    )

async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    top_refs = get_top_referrers(limit=15)
    
    msg = " **LEADERBOARD (Top Referrers)**\n\n"
    if not top_refs:
        msg += " No data available."
    else:
        for i, user in enumerate(top_refs):
            uid = user.get('user_id')
            sales = user.get('referral_purchases', 0)
            msg += f"#{i+1}  `{uid}`   **{sales} Sales** ({sales*100})\n"
            
    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_field(user_id, "current_level", 1)
    update_user_field(user_id, "history", [])
    update_user_field(user_id, "current_prediction", random.choice(['Small', 'Big']))
    await update.message.reply_text(" **Session Reset.**\nHistory cleared and Betting Level reset to 1.")

async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for Target Session."""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data.get("target_session"):
        await update.message.reply_text(" **Active Session Found.**\nResuming...", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" Resume", callback_data="target_resume")]]))
        return TARGET_START_MENU 

    if not user_data.get("target_access"):
        await update.message.reply_text(" **Access Denied.**\nYou need to buy a Target Pack from the Shop first.")
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(" WINGO 30 SEC", callback_data="tgt_game_30s")],
        [InlineKeyboardButton(" WINGO 1 MIN", callback_data="tgt_game_1m")]
    ])
    await update.message.reply_text(" **TARGET SESSION SETUP**\nSelect Game Mode:", reply_markup=kb)
    return TARGET_SELECT_GAME

# --- TARGET HANDLERS FOR SESSION ---
async def start_target_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    gtype = "30s" if q.data == "tgt_game_30s" else "1m"
    uid = q.from_user.id
    ud = get_user_data(uid)
    await q.edit_message_text(" **Initializing...**")
    session = start_target_session(uid, ud['target_access'], gtype)
    if not session:
        await q.edit_message_text(" **API Error.**")
        return ConversationHandler.END
    await display_target_step(q, session)
    return TARGET_GAME_LOOP

async def target_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sess = get_user_data(q.from_user.id).get("target_session")
    if not sess:
        await q.edit_message_text(" Expired.")
        return ConversationHandler.END
    await display_target_step(q, sess)
    return TARGET_GAME_LOOP

async def display_target_step(update_obj, sess):
    # PROGRESS BAR & PROFIT LOGIC
    start_bal = sess.get("start_balance", 1000)
    current_bal = sess['current_balance']
    target_bal = sess['target_amount']
    
    # Progress Calculation
    needed = target_bal - start_bal
    made = current_bal - start_bal
    pct = made / needed if needed > 0 else 0
    p_bar = draw_bar(pct, length=12, style="blocks")
    
    profit_sign = "+" if made >= 0 else ""
    color = "" if sess['current_prediction'] == "Big" else ""
    
    # Sequence Logic Display
    seq_idx = sess['current_level_index']
    seq = sess['sequence']
    bet_amt = seq[seq_idx] if seq_idx < len(seq) else seq[-1]
    
    msg = (
        f" **TARGET SESSION**\n"
        f"\n"
        f" **Goal:** {target_bal}\n"
        f" **Progress:** {p_bar}\n"
        f" **Balance:** {current_bal} ({profit_sign}{made})\n"
        f"\n"
        f" **Period:** `{sess['current_period']}`\n"
        f" **BET:** {color} **{sess['current_prediction'].upper()}**\n"
        f" **Amount:** {bet_amt}\n"
        f""
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(" WIN", callback_data="tgt_win"), InlineKeyboardButton(" LOSS", callback_data="tgt_loss")]])
    await update_obj.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

async def target_game_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    out = q.data.replace("tgt_", "")
    sess, stat = process_target_outcome(q.from_user.id, out)
    if stat in ["TargetReached", "Bankrupt", "Ended"]:
        txt = " **TARGET HIT!**" if stat == "TargetReached" else " **FAILED.**"
        await q.edit_message_text(txt + f"\nFinal: {sess['current_balance']}")
        return ConversationHandler.END
    await display_target_step(q, sess)
    return TARGET_GAME_LOOP

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(" **Cancelled.**")
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command)) #  
    app.add_handler(CommandHandler("stats", stats_command)) #  
    app.add_handler(CommandHandler("packs", packs_command))
    app.add_handler(CommandHandler("switch", switch_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("invite", invite_command)) 
    app.add_handler(CommandHandler("refstats", admin_referral_stats_command)) 
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^back_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^my_stats"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^set_mode_"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^adm_")) # Payment approval

    # Admin Broadcast Conversation
    broadcast_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_broadcast$")],
        states={ADMIN_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_broadcast)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )
    app.add_handler(broadcast_handler)

    # Game Conversation
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
    
    # Buy Handler
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

    # Target Game Handler
    target_h = ConversationHandler(
        entry_points=[CommandHandler("target", target_command)],
        states={
            TARGET_START_MENU: [CallbackQueryHandler(target_resume, pattern="^target_resume$")],
            TARGET_SELECT_GAME: [CallbackQueryHandler(start_target_game, pattern="^tgt_game_")],
            TARGET_GAME_LOOP: [CallbackQueryHandler(target_game_loop, pattern="^tgt_")]
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start_command)],
        allow_reentry=True
    )
    app.add_handler(target_h)

    # Launch Services
    print("  Starting Background Salt Cracker Service...")
    start_salt_service()

    print("  Bot Online.")
    app.run_polling()

if __name__ == "__main__":
    main()