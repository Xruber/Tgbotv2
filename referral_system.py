import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from pymongo.collection import Collection

# Set up logging for this module
logger = logging.getLogger(__name__)

# --- Referral Constants ---
REFERRAL_POINTS_AWARD = 100  # Points awarded to the referrer
PACKAGE_POINT_COST = 500     # Example cost for a prediction package (e.g., 500 points)

# --- Referral Functions ---

def get_referral_link(user_id: int, bot_username: str) -> str:
    """Generates a deep-linking start URL for the user's referral."""
    # Format: t.me/<bot_username>?start=<referrer_id>
    return f"https://t.me/{bot_username}?start={user_id}"

async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the user their unique referral link and current points balance."""
    user_id = update.effective_user.id
    bot_info = await context.bot.get_me()
    bot_username = bot_info.username

    # Assume we have access to the get_user_data and is_subscription_active functions
    user_data = context.user_data.get('db_data') or context.application.user_data_accessors.get_user_data(user_id)
    current_points = user_data.get("referral_points", 0)

    referral_link = get_referral_link(user_id, bot_username)

    message = (
        f"🔗 **Your Referral System**\n\n"
        f"💰 **Your Current Points:** `{current_points}`\n"
        f"🎁 **Reward per Refer:** `{REFERRAL_POINTS_AWARD}` points\n\n"
        f"**Share this unique link to earn points:**\n"
        f"```{referral_link}```\n\n"
        "When a new user starts the bot using your link, you instantly receive points!"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Redeem Prediction Package", callback_data="redeem_points")],
    ])

    await update.message.reply_text(
        message,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def check_and_award_referral(
    context: ContextTypes.DEFAULT_TYPE, 
    new_user_id: int, 
    start_payload: str,
    users_collection: Collection,
    update_user_field
) -> bool:
    """
    Checks the /start payload for a referral ID and awards points to the referrer.
    
    Returns True if a referral was processed, False otherwise.
    """
    try:
        # Check if the payload is a potential referrer ID (must be numeric string)
        referrer_id = int(start_payload)
        
        # A user cannot refer themselves
        if referrer_id == new_user_id:
            return False
            
        # 1. Check if the referrer exists and is a valid user
        referrer_data = users_collection.find_one({"user_id": referrer_id})

        if referrer_data:
            # 2. Check if the new user already has a referrer (preventing multiple awards)
            new_user_data = users_collection.find_one({"user_id": new_user_id})
            
            # The 'referrer_id' field is initialized as None on first user creation in the main file.
            if new_user_data and new_user_data.get("referrer_id") is None:
                
                # 3. Award points to the referrer
                # Use $inc to safely increment the points atomically
                users_collection.update_one(
                    {"user_id": referrer_id},
                    {"$inc": {"referral_points": REFERRAL_POINTS_AWARD}}
                )
                
                # 4. Record the referral for the new user
                update_user_field(new_user_id, "referrer_id", referrer_id)
                
                # 5. Notify the referrer
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎁 **Referral Bonus!**\n\n"
                         f"User `{new_user_id}` started the bot using your link. You have earned **{REFERRAL_POINTS_AWARD}** points! "
                         f"Your new balance is now **{referrer_data.get('referral_points', 0) + REFERRAL_POINTS_AWARD}** points."
                )
                
                return True
                
    except ValueError:
        # Payload was not a numeric referral ID (e.g., just /start or another command payload)
        pass 
    except Exception as e:
        logger.error(f"Error processing referral for user {new_user_id} with payload {start_payload}: {e}")
        
    return False

# --- Point Redemption Functions ---

async def redeem_points_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt for point redemption and confirm status."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Assume we have access to the get_user_data function
    user_data = context.user_data.get('db_data') or context.application.user_data_accessors.get_user_data(user_id)
    current_points = user_data.get("referral_points", 0)

    if current_points < PACKAGE_POINT_COST:
        message = (
            f"❌ **Redemption Failed!**\n\n"
            f"You need **{PACKAGE_POINT_COST}** points to redeem a package, but you only have **{current_points}** points.\n"
            "Keep referring users to earn more points! Use `/refer` to get your link."
        )
        keyboard = None
    else:
        message = (
            f"✅ **Ready to Redeem!**\n\n"
            f"You have **{current_points}** points. Redeeming a package costs **{PACKAGE_POINT_COST}** points.\n\n"
            "This will grant you a 7-Day Prediction Access package."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Confirm Redemption ({PACKAGE_POINT_COST} points)", callback_data="confirm_redeem")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_redeem")],
        ])

    await query.edit_message_text(
        message,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def confirm_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Performs the point deduction and grants the prediction access."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Assume access to update_user_field and is_subscription_active, and the PREDICTION_PLANS constant
    
    # 1. Re-check points and status
    user_data = context.user_data.get('db_data') or context.application.user_data_accessors.get_user_data(user_id)
    current_points = user_data.get("referral_points", 0)
    
    if current_points < PACKAGE_POINT_COST:
        await query.edit_message_text("❌ Redemption failed: Not enough points. Please check your balance with /refer.")
        return

    # 2. Perform point deduction
    # Use $inc with a negative value for deduction
    users_collection = context.application.user_data_accessors.users_collection
    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"referral_points": -PACKAGE_POINT_COST}}
    )

    new_points = current_points - PACKAGE_POINT_COST
    
    # 3. Grant the '7_day' access (assuming '7_day' is the redeemable plan)
    # This requires constants and logic from prediction_bot.py, which we assume is accessible
    
    # Note: In a real, separated scenario, you'd need a cleaner way to access these, 
    # but for a simple split, we'll rely on the update function existing in main file.
    # We will use a dummy function here and ensure the main file provides the real one.
    
    try:
        grant_access_func = context.application.user_data_accessors.grant_prediction_access
        plan_key = "7_day"
        await grant_access_func(user_id, plan_key, 'Redeemed via Points')
        
        await query.edit_message_text(
            f"🎉 **Redemption Successful!** 🎉\n\n"
            f"**{PACKAGE_POINT_COST}** points deducted. New balance: **{new_points}** points.\n"
            "You have been granted **7-Day Prediction Access!**\n\n"
            "Use `/start` to see your updated status and get your first prediction."
        )
    except Exception as e:
        logger.error(f"Failed to grant access on redemption for user {user_id}: {e}")
        # Rollback points if access grant failed
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"referral_points": PACKAGE_POINT_COST}}
        )
        await query.edit_message_text("🚨 An error occurred while activating your package. Points have been refunded. Please try again later.")
        
async def cancel_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancels the redemption flow."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Redemption cancelled. Use `/refer` to check your status or `/start` to return to the main menu.")

# Helper function placeholder to be provided by the main bot file
async def grant_prediction_access(user_id: int, plan_key: str, reason: str):
    """Placeholder for the function to be passed from the main file."""
    raise NotImplementedError("This function should be provided by the main bot application.")