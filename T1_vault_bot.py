import os
import logging
import requests
import paypalrestsdk
import pytz

from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

logging.basicConfig(level=logging.INFO)

# -- Environment Variables --
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET_KEY = os.getenv("PAYPAL_SECRET_KEY")

if not TELEGRAM_API_TOKEN:
    raise ValueError("TELEGRAM_API_TOKEN environment variable is not set.")

if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET_KEY:
    raise ValueError("PayPal API credentials are not set.")

# -- PayPal config --
paypalrestsdk.configure({
    "mode": "live",
    "client_id": PAYPAL_CLIENT_ID,
    "client_secret": PAYPAL_SECRET_KEY
})

# -- Global Variables --
goal_inventory = 1000
AUTHORIZED_USERS = set()
BOT_OWNER_ID = 6451807462
ALLOWED_TOPIC_ID = 4437
ALLOWED_CHAT_ID = -1002387080797

# Example Render domain:
WEBHOOK_URL = f"https://t1-vault-bot.onrender.com/{TELEGRAM_API_TOKEN}"

# ----------------------------------------------------------------------
# Time-of-day greeting in Eastern Time
# ----------------------------------------------------------------------
def get_eastern_greeting() -> str:
    """Return "Good morning/afternoon/evening" based on Eastern Time."""
    eastern = pytz.timezone("US/Eastern")
    now_est = datetime.now(eastern)
    hour = now_est.hour
    
    if 0 <= hour < 12:
        return "Good morning"
    elif 12 <= hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"


# ----------------------------------------------------------------------
# Example helper to retrieve PayPal balance
# ----------------------------------------------------------------------
def get_paypal_balance() -> float:
    try:
        auth_response = requests.post(
            "https://api.paypal.com/v1/oauth2/token",
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET_KEY),
            data={"grant_type": "client_credentials"},
        )
        auth_response.raise_for_status()
        access_token = auth_response.json()["access_token"]

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


# ----------------------------------------------------------------------
# Telegram Command Handlers
# ----------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greet user with time-of-day aware message in Eastern Time."""
    greeting = get_eastern_greeting()
    text = (
        f"{greeting} sir! As the T1 Vault Bot, I am at your service.\n"
        "Say /vault to see the current vault inventory.\n"
        "Say /donate to contribute to the vault."
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

        # Announce to a specific group/Thread
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


# ----------------------------------------------------------------------
# Main entry point (no Flask, using PTB's built-in web server)
# ----------------------------------------------------------------------
def main():
    # Create the Telegram Application
    application = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("setgoal", set_goal))
    application.add_handler(CommandHandler("setauthorized", set_authorized))

    # The port Render gives you
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
