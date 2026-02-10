from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import (
    get_user_wallet, get_all_tokens, update_wallet_balance, 
    trade_token, create_transaction, get_user_transactions, 
    update_transaction_status, get_transaction, get_user_data,
    update_token_price, users_collection, get_all_user_ids,
    update_token_holding
)
from config import ADMIN_ID, PAYMENT_IMAGE_URL

# --- CONVERSATION STATES ---
# Deposit
DEP_AMOUNT, DEP_METHOD, DEP_UTR = range(10, 13)
# Withdraw
WD_AMOUNT, WD_METHOD, WD_DETAILS = range(20, 23)

# ==========================================
# 1. MAIN WALLET MENU
# ==========================================
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    wallet = get_user_wallet(uid)
    bal = wallet['balance']
    
    # Calculate Assets
    tokens = get_all_tokens()
    assets_val = 0
    holdings = wallet.get('holdings', {})
    holdings_txt = ""
    
    for t in tokens:
        sym = t['symbol']
        qty = holdings.get(sym, 0)
        if qty > 0:
            val = qty * t['price']
            assets_val += val
            holdings_txt += f"🔹 **{t['name']}:** {qty} (≈₹{int(val)})\n"

    # Pending Transactions
    txs = get_user_transactions(uid, limit=3)
    pending_txt = ""
    for tx in txs:
        if tx['status'] == 'pending':
            icon = "📥" if tx['type'] == 'deposit' else "📤"
            pending_txt += f"{icon} **{tx['type'].title()}:** ₹{tx['amount']} (Pending)\n"

    msg = (
        f"👛 **YOUR WALLET**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Fiat Balance: **₹{bal:.2f}**\n"
        f"💎 Asset Value: **₹{assets_val:.2f}**\n"
        f"📊 **Net Worth: ₹{bal + assets_val:.2f}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"**⏳ PENDING:**\n{pending_txt if pending_txt else 'No pending transactions.'}\n"
        f"━━━━━━━━━━━━━━\n"
        f"**📂 PORTFOLIO:**\n{holdings_txt if holdings_txt else 'No tokens owned.'}"
    )
    
    kb = [
        [InlineKeyboardButton("➕ Deposit", callback_data="start_deposit"), InlineKeyboardButton("➖ Withdraw", callback_data="start_withdraw")],
        [InlineKeyboardButton("📈 Invest", callback_data="wallet_invest"), InlineKeyboardButton("📉 Sell", callback_data="wallet_sell")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ==========================================
# 🚀 DEPOSIT CONVERSATION
# ==========================================

async def start_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    kb = [
        [InlineKeyboardButton("₹100", callback_data="dep_amt_100"), InlineKeyboardButton("₹200", callback_data="dep_amt_200")],
        [InlineKeyboardButton("₹500", callback_data="dep_amt_500"), InlineKeyboardButton("₹1000", callback_data="dep_amt_1000")],
        [InlineKeyboardButton("₹5000", callback_data="dep_amt_5000"), InlineKeyboardButton("🔙 Cancel", callback_data="shop_wallet")]
    ]
    await q.edit_message_text("➕ **DEPOSIT FUNDS**\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    return DEP_AMOUNT

async def select_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if q.data == "shop_wallet": return await wallet_command(update, context)

    amt = int(q.data.split("_")[2])
    context.user_data['dep_amount'] = amt
    
    kb = [[InlineKeyboardButton("📲 UPI", callback_data="dep_method_upi")]]
    await q.edit_message_text(f"💳 **Amount: ₹{amt}**\nSelect Payment Method:", reply_markup=InlineKeyboardMarkup(kb))
    return DEP_METHOD

async def show_qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    amt = context.user_data['dep_amount']
    caption = (
        f"✅ **PAYMENT REQUEST**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Pay Amount: **₹{amt}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"1. Scan the QR Code.\n"
        f"2. Pay exactly ₹{amt}.\n"
        f"3. Copy the **UTR / Ref No**.\n"
        f"4. Click button below."
    )
    
    kb = [[InlineKeyboardButton("✅ I Have Paid", callback_data="dep_paid")]]
    
    # Delete text message to send photo
    await q.message.delete()
    try:
        await context.bot.send_photo(
            chat_id=q.from_user.id,
            photo=PAYMENT_IMAGE_URL,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    except:
        await context.bot.send_message(q.from_user.id, "⚠️ **Error loading QR.**\nPay to Admin UPI and enter UTR.", reply_markup=InlineKeyboardMarkup(kb))
        
    return DEP_UTR

async def ask_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_caption("🔢 **ENTER UTR NUMBER:**\n\nPlease type and send the 12-digit UTR number now.")
    return DEP_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    amt = context.user_data.get('dep_amount')
    
    tx_id = create_transaction(uid, "deposit", amt, "UPI", utr)
    
    # Notify Admin
    kb_admin = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept", callback_data=f"adm_dep_ok_{tx_id}"), 
         InlineKeyboardButton("❌ Reject", callback_data=f"adm_dep_no_{tx_id}")]
    ])
    await context.bot.send_message(
        ADMIN_ID,
        f"📥 **NEW DEPOSIT**\n👤 User: `{uid}`\n💰 Amount: ₹{amt}\n🔢 UTR: `{utr}`\n🆔 TxID: `{tx_id}`",
        reply_markup=kb_admin,
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(
        "✅ **Submitted!**\nYour deposit is Pending Approval.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_home")]])
    )
    return ConversationHandler.END

# ==========================================
# 📤 WITHDRAWAL CONVERSATION
# ==========================================

async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    uid = q.from_user.id
    wallet = get_user_wallet(uid)
    bal = wallet['balance']
    
    if bal < 100:
        await q.edit_message_text("❌ **Minimum withdrawal is ₹100.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="shop_wallet")]]))
        return ConversationHandler.END
        
    # Calculate Percentages
    amt_25 = int(bal * 0.25)
    amt_50 = int(bal * 0.50)
    amt_100 = int(bal)
    
    kb = [
        [InlineKeyboardButton(f"25% (₹{amt_25})", callback_data=f"wd_amt_{amt_25}")],
        [InlineKeyboardButton(f"50% (₹{amt_50})", callback_data=f"wd_amt_{amt_50}")],
        [InlineKeyboardButton(f"100% (₹{amt_100})", callback_data=f"wd_amt_{amt_100}")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="shop_wallet")]
    ]
    await q.edit_message_text(f"📤 **WITHDRAWAL**\nBalance: ₹{bal}\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    return WD_AMOUNT

async def select_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if q.data == "shop_wallet": return await wallet_command(update, context)

    amt = int(q.data.split("_")[2])
    context.user_data['wd_amount'] = amt
    
    kb = [
        [InlineKeyboardButton("UPI", callback_data="wd_method_UPI"), InlineKeyboardButton("BANK", callback_data="wd_method_BANK")],
        [InlineKeyboardButton("USDT (TRC20)", callback_data="wd_method_USDT")]
    ]
    await q.edit_message_text(f"💸 **Withdraw: ₹{amt}**\nSelect Receiving Method:", reply_markup=InlineKeyboardMarkup(kb))
    return WD_METHOD

async def ask_withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    method = q.data.split("_")[2]
    context.user_data['wd_method'] = method
    
    prompt = ""
    if method == "UPI": prompt = "Enter your **UPI ID** (e.g., name@okaxis):"
    elif method == "BANK": prompt = "Enter **Account No & IFSC**:"
    elif method == "USDT": prompt = "Enter **TRC20 Wallet Address**:"
    
    await q.edit_message_text(f"📝 **Selected: {method}**\n\n{prompt}")
    return WD_DETAILS

async def process_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details = update.message.text
    uid = update.effective_user.id
    amt = context.user_data['wd_amount']
    method = context.user_data['wd_method']
    
    # Lock Funds
    wallet = get_user_wallet(uid)
    if wallet['balance'] < amt:
        await update.message.reply_text("❌ **Insufficient Balance.**")
        return ConversationHandler.END
        
    update_wallet_balance(uid, -amt)
    tx_id = create_transaction(uid, "withdraw", amt, method, details)
    
    # Notify Admin
    kb_admin = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve (Sent)", callback_data=f"adm_wd_ok_{tx_id}"), 
         InlineKeyboardButton("❌ Reject (Refund)", callback_data=f"adm_wd_no_{tx_id}")]
    ])
    await context.bot.send_message(
        ADMIN_ID,
        f"📤 **WITHDRAW REQUEST**\n👤 User: `{uid}`\n💰 Amount: ₹{amt}\n🏦 Method: `{method}`\n📝 Details: `{details}`\n🆔 TxID: `{tx_id}`",
        reply_markup=kb_admin,
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(
        f"✅ **Withdrawal Requested!**\nAmount: ₹{amt}\nStatus: **Pending**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_home")]])
    )
    return ConversationHandler.END

# ==========================================
# 👮 ADMIN PAYMENT HANDLER
# ==========================================

async def admin_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # Format: adm_dep_ok_TXID
    parts = q.data.split("_")
    action = parts[1] # 'dep' or 'wd'
    decision = parts[2] # 'ok' or 'no'
    tx_id = parts[3]
    
    tx = get_transaction(tx_id)
    if not tx or tx['status'] != 'pending':
        await q.answer("❌ Already processed.", show_alert=True)
        return

    uid = tx['user_id']
    amt = tx['amount']
    
    if action == "dep": # DEPOSIT
        if decision == "ok":
            update_wallet_balance(uid, amt)
            update_transaction_status(tx_id, "completed")
            await context.bot.send_message(uid, f"✅ **Deposit Approved!**\nAdded: ₹{amt}")
            await q.edit_message_text(f"✅ Approved Deposit ₹{amt} for {uid}")
        else:
            update_transaction_status(tx_id, "rejected")
            await context.bot.send_message(uid, f"❌ **Deposit Rejected.**\nAmount: ₹{amt}")
            await q.edit_message_text(f"❌ Rejected Deposit for {uid}")
            
    elif action == "wd": # WITHDRAW
        if decision == "ok":
            update_transaction_status(tx_id, "completed")
            await context.bot.send_message(uid, f"✅ **Withdrawal Sent!**\nAmount: ₹{amt}")
            await q.edit_message_text(f"✅ Marked Withdraw ₹{amt} as SENT.")
        else:
            update_wallet_balance(uid, amt) # Refund
            update_transaction_status(tx_id, "rejected")
            await context.bot.send_message(uid, f"❌ **Withdrawal Rejected.**\nRefunded: ₹{amt}")
            await q.edit_message_text(f"❌ Rejected Withdraw. Refunded {uid}.")

# ==========================================
# 📊 TOKEN HANDLERS (Standard)
# ==========================================

async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tokens = get_all_tokens()
    msg = "📈 **TOKEN MARKET**\n━━━━━━━━━━━━━━\n"
    kb = []
    for t in tokens:
        msg += f"**{t['name']} ({t['symbol']})**: ₹{t['price']}\n"
        kb.append([InlineKeyboardButton(f"Buy {t['symbol']}", callback_data=f"buy_token_{t['symbol']}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="shop_wallet")])
    if q: await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def buy_token_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sym = q.data.split("_")[2]
    uid = q.from_user.id
    tokens = get_all_tokens()
    t = next((x for x in tokens if x['symbol'] == sym), None)
    
    if t:
        w = get_user_wallet(uid)
        if w['balance'] >= t['price']:
            trade_token(uid, sym, 1, t['price'], is_buy=True)
            await q.answer(f"✅ Bought 1 {sym}!", show_alert=True)
        else:
            await q.answer("❌ Insufficient Balance", show_alert=True)

async def sell_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    w = get_user_wallet(uid)
    kb = []
    tokens = get_all_tokens()
    for sym, qty in w.get('holdings', {}).items():
        if qty > 0:
            t = next((x for x in tokens if x['symbol'] == sym), None)
            if t: kb.append([InlineKeyboardButton(f"Sell 1 {sym} (+₹{t['price']})", callback_data=f"sell_token_{sym}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="shop_wallet")])
    await q.edit_message_text("📉 **SELL TOKENS**", reply_markup=InlineKeyboardMarkup(kb))

async def sell_token_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sym = q.data.split("_")[2]
    uid = q.from_user.id
    tokens = get_all_tokens()
    t = next((x for x in tokens if x['symbol'] == sym), None)
    if t:
        trade_token(uid, sym, 1, t['price'], is_buy=False)
        await q.answer(f"✅ Sold 1 {sym}!", show_alert=True)
        await sell_menu(update, context)

# ==========================================
# 🛠️ ADMIN TOKEN CMDS (Rigging & ROI)
# ==========================================

async def token_rig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /token-rig SYMBOL NEW_PRICE
    """
    if update.effective_user.id != ADMIN_ID: return
    
    try:
        sym = context.args[0].upper()
        price = float(context.args[1])
        update_token_price(sym, price)
        await update.message.reply_text(f"✅ **Rigged:** {sym} set to ₹{price}")
    except:
        await update.message.reply_text("❌ Usage: `/token-rig SYMBOL PRICE`")

async def token_roi_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows users with best ROI.
    """
    if update.effective_user.id != ADMIN_ID: return
    
    await update.message.reply_text("⏳ **Calculating ROI List...**")
    
    tokens = get_all_tokens()
    price_map = {t['symbol']: t['price'] for t in tokens}
    
    roi_data = []
    
    # Check if we can access the collection directly or need to iterate
    # Using raw pymongo iteration for speed on this specific admin command
    all_users = users_collection.find()
    
    for u in all_users:
        wallet = u.get('wallet', {})
        holdings = wallet.get('holdings', {})
        invested = wallet.get('invested_amt', {})
        
        total_current_val = 0
        total_invested_val = 0
        
        for sym, qty in holdings.items():
            if qty > 0:
                # Current Value
                curr_p = price_map.get(sym, 0)
                total_current_val += qty * curr_p
                
                # Invested Value
                total_invested_val += invested.get(sym, 0)
                
        if total_invested_val > 0:
            roi_pct = ((total_current_val - total_invested_val) / total_invested_val) * 100
            roi_data.append({
                "uid": u['user_id'],
                "roi": roi_pct,
                "profit": total_current_val - total_invested_val
            })
            
    # Sort by ROI Descending
    roi_data.sort(key=lambda x: x['roi'], reverse=True)
    
    msg = "🏆 **TOKEN ROI LEADERBOARD**\n━━━━━━━━━━━━━━\n"
    for i, d in enumerate(roi_data[:10]): # Top 10
        msg += f"{i+1}. User `{d['uid']}`: **{d['roi']:.1f}%** (Profit: ₹{int(d['profit'])})\n"
        
    if not roi_data: msg += "No investments found."
    
    await update.message.reply_text(msg, parse_mode="Markdown")
