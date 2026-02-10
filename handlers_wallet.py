import matplotlib
matplotlib.use('Agg') # Safe mode for servers
import matplotlib.pyplot as plt
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes, ConversationHandler
from database import (
    get_user_wallet, get_all_tokens, update_wallet_balance, 
    trade_token, create_transaction, get_user_transactions, 
    update_transaction_status, get_transaction, get_user_data,
    update_token_price, users_collection, get_all_user_ids,
    update_token_holding, get_token_details
)
from config import ADMIN_ID, PAYMENT_IMAGE_URL

# --- CONVERSATION STATES ---
# Deposit/Withdraw
DEP_AMOUNT, DEP_METHOD, DEP_UTR = range(10, 13)
WD_AMOUNT, WD_METHOD, WD_DETAILS = range(20, 23)
# Trading (New)
TRADE_AMOUNT = 30

# --- CHART GENERATOR ---
def generate_chart_image(symbol, history):
    """Generates a price chart image buffer."""
    try:
        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
        # Color: Green if up, Red if down
        color = '#00ff00' if len(history) > 1 and history[-1] >= history[0] else '#ff0000'
        
        ax.plot(history, marker='o', linestyle='-', color=color, linewidth=2, markersize=4)
        ax.set_title(f"{symbol} Price History")
        ax.set_ylabel("Price (INR)")
        ax.grid(True, linestyle='--', alpha=0.3)
        
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close(fig) 
        return buf
    except Exception as e:
        print(f"Chart Error: {e}")
        return None

# ==========================================
# 1. MAIN WALLET MENU
# ==========================================
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    wallet = get_user_wallet(uid)
    bal = wallet['balance']
    
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
        [InlineKeyboardButton("📈 Invest / Trade", callback_data="wallet_tokens")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
    ]
    
    if update.callback_query:
        if update.callback_query.message.photo:
            await update.callback_query.message.delete()
            await context.bot.send_message(uid, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ==========================================
# 2. TOKEN MARKET & CHARTS
# ==========================================
async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tokens = get_all_tokens()
    
    msg = "📈 **TOKEN MARKET**\nSelect a token to view Chart & Buy:\n━━━━━━━━━━━━━━\n"
    kb = []
    
    for t in tokens:
        kb.append([InlineKeyboardButton(f"{t['name']} ({t['symbol']}) - ₹{t['price']}", callback_data=f"view_chart_{t['symbol']}")])
    
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="wallet_main")])
    
    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(q.from_user.id, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

async def view_token_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the chart and purchase options."""
    q = update.callback_query
    await q.answer("Loading Chart...")
    
    sym = q.data.split("_")[2]
    token = get_token_details(sym)
    
    if not token:
        await q.message.reply_text("❌ Token not found.")
        return

    # Generate Chart
    history = token.get("history", [token['price']])
    if len(history) < 2: history = [token['price']] * 5 
    
    chart_buf = generate_chart_image(sym, history)
    
    caption = (
        f"📊 **{token['name']} ({sym})**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 **Current Price:** ₹{token['price']}\n"
        f"📉 **Low (24h):** ₹{min(history)}\n"
        f"📈 **High (24h):** ₹{max(history)}\n"
    )
    
    # NEW TRADING BUTTONS (Start Conversation)
    kb = [
        [InlineKeyboardButton("🟢 BUY", callback_data=f"ask_buy_{sym}"), InlineKeyboardButton("🔴 SELL", callback_data=f"ask_sell_{sym}")],
        [InlineKeyboardButton("🔙 Back to Market", callback_data="wallet_tokens")]
    ]
    
    # Cleanup previous message to prevent flickers/errors
    await q.message.delete()
    
    if chart_buf:
        await context.bot.send_photo(q.from_user.id, photo=chart_buf, caption=caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await context.bot.send_message(q.from_user.id, caption + "\n(Chart unavailable)", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ==========================================
# 3. FLEXIBLE BUYING / SELLING LOGIC
# ==========================================

async def ask_trade_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks user for quantity to buy/sell."""
    q = update.callback_query
    await q.answer()
    
    data = q.data.split("_")
    action = data[1] # "buy" or "sell"
    sym = data[2]
    
    context.user_data['trade_action'] = action
    context.user_data['trade_symbol'] = sym
    
    token = get_token_details(sym)
    price = token['price']
    uid = q.from_user.id
    wallet = get_user_wallet(uid)
    
    if action == "buy":
        bal = wallet['balance']
        max_can_buy = int(bal // price)
        msg = (
            f"🟢 **BUY {sym}**\n"
            f"💰 Price: ₹{price}\n"
            f"💵 Balance: ₹{bal:.2f}\n"
            f"🛒 Max you can buy: **{max_can_buy}**\n\n"
            f"🔢 **Type the amount to BUY:**"
        )
    else: # Sell
        holdings = wallet.get('holdings', {}).get(sym, 0)
        msg = (
            f"🔴 **SELL {sym}**\n"
            f"💰 Price: ₹{price}\n"
            f"🎒 You own: **{holdings}**\n\n"
            f"🔢 **Type the amount to SELL:**"
        )

    # Use edit_message_caption if coming from photo, else edit text
    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(uid, msg, parse_mode="Markdown")
    else:
        await q.edit_message_text(msg, parse_mode="Markdown")
        
    return TRADE_AMOUNT

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes the text input for amount."""
    text = update.message.text
    uid = update.effective_user.id
    
    try:
        qty = int(text)
        if qty <= 0: raise ValueError
    except:
        await update.message.reply_text("❌ Invalid number. Please type a valid quantity (e.g., 5).")
        return TRADE_AMOUNT # Ask again

    action = context.user_data.get('trade_action')
    sym = context.user_data.get('trade_symbol')
    token = get_token_details(sym)
    price = token['price']
    wallet = get_user_wallet(uid)
    
    if action == "buy":
        cost = qty * price
        if wallet['balance'] >= cost:
            trade_token(uid, sym, qty, price, is_buy=True)
            await update.message.reply_text(f"✅ **BOUGHT!**\n\n➕ {qty} {sym}\n➖ ₹{cost:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📉 View Chart", callback_data=f"view_chart_{sym}")]]))
        else:
            await update.message.reply_text(f"❌ **Insufficient Funds.**\nCost: ₹{cost}\nBalance: ₹{wallet['balance']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"view_chart_{sym}")]]))
            return ConversationHandler.END

    elif action == "sell":
        owned = wallet.get('holdings', {}).get(sym, 0)
        if owned >= qty:
            earnings = qty * price
            trade_token(uid, sym, qty, price, is_buy=False)
            await update.message.reply_text(f"✅ **SOLD!**\n\n➖ {qty} {sym}\n➕ ₹{earnings:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📉 View Chart", callback_data=f"view_chart_{sym}")]]))
        else:
            await update.message.reply_text(f"❌ **Insufficient Tokens.**\nYou have: {owned}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"view_chart_{sym}")]]))
            return ConversationHandler.END

    return ConversationHandler.END

# --- DEPOSIT FLOW ---
async def start_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    kb = [
        [InlineKeyboardButton("₹100", callback_data="dep_amt_100"), InlineKeyboardButton("₹200", callback_data="dep_amt_200")],
        [InlineKeyboardButton("₹500", callback_data="dep_amt_500"), InlineKeyboardButton("₹1000", callback_data="dep_amt_1000")],
        [InlineKeyboardButton("₹5000", callback_data="dep_amt_5000"), InlineKeyboardButton("🔙 Cancel", callback_data="wallet_main")]
    ]
    if q.message.photo: 
        await q.message.delete()
        await context.bot.send_message(q.from_user.id, "➕ **DEPOSIT FUNDS**\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    else: 
        await q.edit_message_text("➕ **DEPOSIT FUNDS**\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    return DEP_AMOUNT

async def select_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if q.data == "wallet_main": return await wallet_command(update, context)

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
        await context.bot.send_message(q.from_user.id, f"⚠️ **QR Error**\n\n{caption}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        
    return DEP_UTR

async def ask_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    msg = "🔢 **ENTER UTR NUMBER:**\n\nPlease type and send the 12-digit UTR number now."
    
    # Safe edit check
    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(q.from_user.id, msg, parse_mode="Markdown")
    else:
        await q.edit_message_text(msg, parse_mode="Markdown")
        
    return DEP_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text
    uid = update.effective_user.id
    amt = context.user_data.get('dep_amount')
    
    tx_id = create_transaction(uid, "deposit", amt, "UPI", utr)
    
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

# --- WITHDRAW FLOW ---
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    uid = q.from_user.id
    wallet = get_user_wallet(uid)
    bal = wallet['balance']
    
    if bal < 100:
        msg = "❌ **Minimum withdrawal is ₹100.**"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="wallet_main")]])
        if q.message.photo: await q.message.delete(); await context.bot.send_message(uid, msg, reply_markup=kb)
        else: await q.edit_message_text(msg, reply_markup=kb)
        return ConversationHandler.END
        
    amt_25 = int(bal * 0.25)
    amt_50 = int(bal * 0.50)
    amt_100 = int(bal)
    
    kb = [
        [InlineKeyboardButton(f"25% (₹{amt_25})", callback_data=f"wd_amt_{amt_25}")],
        [InlineKeyboardButton(f"50% (₹{amt_50})", callback_data=f"wd_amt_{amt_50}")],
        [InlineKeyboardButton(f"100% (₹{amt_100})", callback_data=f"wd_amt_{amt_100}")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="wallet_main")]
    ]
    if q.message.photo: 
        await q.message.delete()
        await context.bot.send_message(uid, f"📤 **WITHDRAWAL**\nBalance: ₹{bal}\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await q.edit_message_text(f"📤 **WITHDRAWAL**\nBalance: ₹{bal}\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    return WD_AMOUNT

async def select_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if q.data == "wallet_main": return await wallet_command(update, context)

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
    
    await q.edit_message_text(f"📝 **Selected: {method}**\n\nEnter Payment Details now:")
    return WD_DETAILS

async def process_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details = update.message.text
    uid = update.effective_user.id
    amt = context.user_data['wd_amount']
    method = context.user_data['wd_method']
    
    wallet = get_user_wallet(uid)
    if wallet['balance'] < amt:
        await update.message.reply_text("❌ **Insufficient Balance.**")
        return ConversationHandler.END
        
    update_wallet_balance(uid, -amt)
    tx_id = create_transaction(uid, "withdraw", amt, method, details)
    
    kb_admin = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"adm_wd_ok_{tx_id}"), 
         InlineKeyboardButton("❌ Reject", callback_data=f"adm_wd_no_{tx_id}")]
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
    
    if action == "dep": 
        if decision == "ok":
            update_wallet_balance(uid, amt)
            update_transaction_status(tx_id, "completed")
            await context.bot.send_message(uid, f"✅ **Deposit Approved!**\nAdded: ₹{amt}")
            await q.edit_message_text(f"✅ Approved Deposit ₹{amt} for {uid}")
        else:
            update_transaction_status(tx_id, "rejected")
            await context.bot.send_message(uid, f"❌ **Deposit Rejected.**\nAmount: ₹{amt}")
            await q.edit_message_text(f"❌ Rejected Deposit for {uid}")
            
    elif action == "wd":
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
# 🛠️ ADMIN COMMANDS
# ==========================================

async def token_rig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        sym = context.args[0].upper()
        price = float(context.args[1])
        update_token_price(sym, price)
        await update.message.reply_text(f"✅ **Rigged:** {sym} set to ₹{price}")
    except:
        await update.message.reply_text("❌ Usage: `/token_rig SYMBOL PRICE`")

async def token_roi_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("⏳ **Calculating ROI...**")
    
    tokens = get_all_tokens()
    price_map = {t['symbol']: t['price'] for t in tokens}
    roi_data = []
    
    all_users = users_collection.find()
    
    for u in all_users:
        wallet = u.get('wallet', {})
        holdings = wallet.get('holdings', {})
        invested = wallet.get('invested_amt', {})
        total_current_val = 0
        total_invested_val = 0
        
        for sym, qty in holdings.items():
            if qty > 0:
                curr_p = price_map.get(sym, 0)
                total_current_val += qty * curr_p
                total_invested_val += invested.get(sym, 0)
                
        if total_invested_val > 0:
            roi_pct = ((total_current_val - total_invested_val) / total_invested_val) * 100
            roi_data.append({"uid": u['user_id'], "roi": roi_pct})
            
    roi_data.sort(key=lambda x: x['roi'], reverse=True)
    msg = "🏆 **TOKEN ROI LEADERBOARD**\n━━━━━━━━━━━━━━\n"
    for i, d in enumerate(roi_data[:10]):
        msg += f"{i+1}. User `{d['uid']}`: **{d['roi']:.1f}%**\n"
        
    await update.message.reply_text(msg, parse_mode="Markdown")
