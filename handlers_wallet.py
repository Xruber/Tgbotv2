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
DEP_AMOUNT, DEP_METHOD, DEP_UTR = range(10, 13)
WD_AMOUNT, WD_METHOD, WD_DETAILS = range(20, 23)

# --- CHART GENERATOR (NEW FEATURE) ---
def generate_chart_image(symbol, history):
    """Generates a price chart image buffer."""
    try:
        plt.figure(figsize=(6, 3), dpi=100)
        # Determine color: Green if up, Red if down
        color = '#00ff00' if len(history) > 1 and history[-1] >= history[0] else '#ff0000'
        
        plt.plot(history, marker='o', linestyle='-', color=color, linewidth=2, markersize=4)
        plt.title(f"{symbol} Price History")
        plt.ylabel("Price (INR)")
        plt.grid(True, linestyle='--', alpha=0.3)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
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
    
    # RENAMED CALLBACKS to fix "Item Not Found" bug (shop_wallet -> wallet_main)
    kb = [
        [InlineKeyboardButton("➕ Deposit", callback_data="start_deposit"), InlineKeyboardButton("➖ Withdraw", callback_data="start_withdraw")],
        [InlineKeyboardButton("📈 Invest", callback_data="wallet_tokens"), InlineKeyboardButton("📉 Sell", callback_data="wallet_sell")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
    ]
    
    if update.callback_query:
        # If a chart image was previously shown, delete it and send text
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
    tokens = get_all_tokens()
    
    msg = "📈 **TOKEN MARKET**\nSelect a token to view Chart & Buy:\n━━━━━━━━━━━━━━\n"
    kb = []
    
    for t in tokens:
        # Changed callback to view chart first
        kb.append([InlineKeyboardButton(f"{t['name']} ({t['symbol']}) - ₹{t['price']}", callback_data=f"view_chart_{t['symbol']}")])
    
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="wallet_main")])
    
    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(q.from_user.id, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def view_token_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the chart and purchase options."""
    q = update.callback_query
    await q.answer("Generating Chart...")
    
    sym = q.data.split("_")[2]
    token = get_token_details(sym)
    
    if not token:
        await q.message.reply_text("❌ Token not found.")
        return

    # Generate Chart
    history = token.get("history", [token['price']])
    # Add some fake history for new tokens so chart isn't empty
    if len(history) < 2: history = [token['price']] * 5 
    
    chart_buf = generate_chart_image(sym, history)
    
    caption = (
        f"📊 **{token['name']} ({sym})**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 **Current Price:** ₹{token['price']}\n"
        f"📉 **Low (24h):** ₹{min(history)}\n"
        f"📈 **High (24h):** ₹{max(history)}\n"
    )
    
    # RENAMED CALLBACK to trade_buy_ to avoid Shop conflict
    kb = [
        [InlineKeyboardButton("✅ Buy 1 Unit", callback_data=f"trade_buy_{sym}")],
        [InlineKeyboardButton("🔙 Back to Market", callback_data="wallet_tokens")]
    ]
    
    await q.message.delete()
    if chart_buf:
        await context.bot.send_photo(q.from_user.id, photo=chart_buf, caption=caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await context.bot.send_message(q.from_user.id, caption + "\n(Chart unavailable)", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def buy_token_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the actual purchase."""
    q = update.callback_query
    sym = q.data.split("_")[2]
    uid = q.from_user.id
    
    token = get_token_details(sym)
    if not token: 
        await q.answer("Token error", show_alert=True)
        return
    
    w = get_user_wallet(uid)
    if w['balance'] >= token['price']:
        trade_token(uid, sym, 1, token['price'], is_buy=True)
        await q.answer(f"✅ Success! Bought 1 {sym}", show_alert=True)
        # Refresh the chart view to show updated status/price
        await view_token_chart(update, context)
    else:
        await q.answer("❌ Insufficient Funds. Please Deposit.", show_alert=True)

# ==========================================
# 3. SELL & DEPOSIT/WITHDRAW
# ==========================================

async def sell_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    w = get_user_wallet(uid)
    kb = []
    tokens = get_all_tokens()
    
    for sym, qty in w.get('holdings', {}).items():
        if qty > 0:
            t = next((x for x in tokens if x['symbol'] == sym), None)
            # RENAMED CALLBACK to trade_sell_
            if t: kb.append([InlineKeyboardButton(f"Sell 1 {sym} (+₹{t['price']})", callback_data=f"trade_sell_{sym}")])
            
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="wallet_main")])
    
    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(uid, "📉 **SELL TOKENS**", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await q.edit_message_text("📉 **SELL TOKENS**", reply_markup=InlineKeyboardMarkup(kb))

async def sell_token_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sym = q.data.split("_")[2]
    uid = q.from_user.id
    token = get_token_details(sym)
    
    if token:
        trade_token(uid, sym, 1, token['price'], is_buy=False)
        await q.answer(f"✅ Sold 1 {sym}", show_alert=True)
        await sell_menu(update, context)

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
            roi_data.append({
                "uid": u['user_id'],
                "roi": roi_pct,
                "profit": total_current_val - total_invested_val
            })
            
    roi_data.sort(key=lambda x: x['roi'], reverse=True)
    
    msg = "🏆 **TOKEN ROI LEADERBOARD**\n━━━━━━━━━━━━━━\n"
    for i, d in enumerate(roi_data[:10]):
        msg += f"{i+1}. User `{d['uid']}`: **{d['roi']:.1f}%** (Profit: ₹{int(d['profit'])})\n"
        
    if not roi_data: msg += "No investments found."
    await update.message.reply_text(msg, parse_mode="Markdown")