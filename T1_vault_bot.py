import os
import logging
import requests
import pytz

from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue
)
import paypalrestsdk

logging.basicConfig(level=logging.INFO)

# -------------------------
#  Environment Variables
# -------------------------
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET_KEY = os.getenv("PAYPAL_SECRET_KEY")

if not TELEGRAM_API_TOKEN:
    raise ValueError("TELEGRAM_API_TOKEN environment variable is not set.")

if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET_KEY:
    raise ValueError("PayPal API credentials are not set.")

# -------------------------
#  PayPal Configuration
# -------------------------
paypalrestsdk.configure({
    "mode": "live",  # or "sandbox"
    "client_id": PAYPAL_CLIENT_ID,
    "client_secret": PAYPAL_SECRET_KEY
})

# -------------------------
#  Global Variables
# -------------------------
goal_inventory = 1000.0
AUTHORIZED_USERS = set()
BOT_OWNER_ID = 6451807462
ALLOWED_TOPIC_ID = 4437
ALLOWED_CHAT_ID = -1002387080797

# Your Render domain
WEBHOOK_URL = f"https://t1-vault-bot.onrender.com/{TELEGRAM_API_TOKEN}"

# PayPal donation link
PAYPAL_DONATION_LINK = "https://www.paypal.com/ncp/payment/URH8ZBQYMY9KY"

# We'll store the last-known PayPal balance to detect new donations
last_balance = 0.0

# -------------------------
#  Time-based Greeting
# -------------------------
def get_eastern_greeting() -> str:
    eastern = pytz.timezone("US/Eastern")
    now_est = datetime.now(eastern)
    hour = now_est.hour
    
    if 0 <= hour < 12:
        return "Good morning"
    elif 12 <= hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"

# -------------------------
#  PayPal helpers
# -------------------------
def get_paypal_balance() -> float:
    """
    Returns the current PayPal balance in USD, or 0.0 if something goes wrong.
    """
    try:
        # First, get OAuth2 token
        auth_response = requests.post(
            "https://api.paypal.com/v1/oauth2/token",
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET_KEY),
            data={"grant_type": "client_credentials"},
        )
        auth_response.raise_for_status()
        access_token = auth_response.json().get("access_token")

        # Next, retrieve the balance
        balance_response = requests.get(
            "https://api.paypal.com/v1/reporting/balances",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        balance_response.raise_for_status()

        balances = balance_response.json().get("balances", [])
        for balance in balances:
            if balance.get("currency_code") == "USD":
                return float(balance["total_balance"]["value"])
        return 0.0
    except Exception as e:
        logging.error(f"Error retrieving PayPal balance: {e}")
        return 0.0

async def check_paypal_donations(context: ContextTypes.DEFAULT_TYPE):
    """
    Periodic task to check if the PayPal balance has increased.
    If it has, we announce a donation in the chat.
    """
    global last_balance
    new_balance = get_paypal_balance()
    if new_balance > last_balance:
        diff = new_balance - last_balance
        # Announce the donation to your chat
        message = (
            f"Someone just donated ${diff:.2f} to the vault!\n"
            f"Vault balance is now: ${new_balance:.2f}"
        )
        # If you want to post in a specific thread:
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            message_thread_id=ALLOWED_TOPIC_ID,
            text=message
        )
        last_balance = new_balance
    else:
        # Update last_balance even if it decreased or stayed the same,
        # to avoid repeated announcements
        last_balance = new_balance

# -------------------------
#  Telegram Command Handlers
# -------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Greet user with time-of-day aware message in Eastern Time,
    mention how to use /vault, /donate, etc.
    """
    greeting = get_eastern_greeting()
    text = (
        f"{greeting} sir! As the T1 Vault Bot, I am at your service.\n"
        "Say /vault to see the current vault inventory.\n"
        "Say /donate to contribute to the vault."
    )
    await update.message.reply_text(text)

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows the current PayPal-based vault balance, compares to the `goal_inventory`,
    and displays an ASCII progress bar.
    """
    vault_balance = get_paypal_balance()
    progress = 0.0
    if goal_inventory > 0:
        progress = (vault_balance / goal_inventory) * 100
        progress = min(progress, 100.0)  # cap at 100 if over goal

    bar_length = 20
    filled = int(progress / 100 * bar_length)
    bar_str = "[" + "=" * filled + " " * (bar_length - filled) + "]"

    message = (
        f"Vault balance: ${vault_balance:.2f}\n"
        f"Goal: ${goal_inventory:.2f}\n"
        f"Progress: {bar_str} {progress:.1f}%\n\n"
        f"Click here to donate: {PAYPAL_DONATION_LINK}"
    )
    await update.message.reply_text(message)

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide direct link to the PayPal donation page."""
    text = (
        "Thank you for your interest in contributing to the vault!\n"
        f"Please proceed to this donation link: {PAYPAL_DONATION_LINK}"
    )
    await update.message.reply_text(text)

async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global goal_inventory
    username = f"@{update.effective_user.username}".lower() if update.effective_user.username else None
    if username not in AUTHORIZED_USERS:
        await update.message.reply_text("You are not authorized to set the vault goal.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setgoal <amount> [reason]")
        return
    
    try:
        goal_inventory = float(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
        await update.message.reply_text(f"Vault goal updated to ${goal_inventory:.2f}.")

        # Announce in a group/thread
        announcement = f"Gentlemen, the Vault goal has been set to ${goal_inventory:.2f}."
        if reason:
            announcement += f" Reason: {reason}"
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            message_thread_id=ALLOWED_TOPIC_ID,
            text=announcement
        )
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a valid number.")

async def set_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTHORIZED_USERS
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Only the bot owner can set authorized users.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setauthorized @username")
        return
    
    new_users = []
    for username in context.args:
        if username.startswith("@"):
            lower_user = username.lower()
            AUTHORIZED_USERS.add(lower_user)
            new_users.append(lower_user)

    if new_users:
        await update.message.reply_text(
            f"Authorized users updated: {', '.join(new_users)}"
        )
    else:
        await update.message.reply_text("No valid @usernames given.")

# -------------------------
#  Main entry point
# -------------------------
def main():
    from telegram.ext import Application
    application = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("donate", donate_command))
    application.add_handler(CommandHandler("setgoal", set_goal))
    application.add_handler(CommandHandler("setauthorized", set_authorized))

    # Initialize last_balance
    global last_balance
    last_balance = get_paypal_balance()

    # Schedule the donation-check job
    # Checks every 60 seconds for new PayPal donations
    application.job_queue.run_repeating(
        check_paypal_donations, 
        interval=60,    # poll every 60 seconds
        first=10        # wait 10s before first run
    )

    # The port that Render provides
    port = int(os.getenv("PORT", "5000"))
    
    logging.info("Starting T1 Vault Bot in webhook mode...")

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TELEGRAM_API_TOKEN,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
