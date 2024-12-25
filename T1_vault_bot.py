import asyncio
import os
import requests
from flask import Flask, request
from threading import Thread
import paypalrestsdk
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Flask app for Render port binding
app = Flask(__name__)

# Environment Variables
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET_KEY = os.getenv("PAYPAL_SECRET_KEY")

if not TELEGRAM_API_TOKEN:
    raise ValueError("The TELEGRAM_API_TOKEN environment variable is not set.")

if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET_KEY:
    raise ValueError("PayPal API credentials are not set.")

# PayPal Configuration
paypalrestsdk.configure({
    "mode": "live",
    "client_id": PAYPAL_CLIENT_ID,
    "client_secret": PAYPAL_SECRET_KEY
})

# Global Variables
goal_inventory = 1000
AUTHORIZED_USERS = set()
BOT_OWNER_ID = 6451807462
ALLOWED_TOPIC_ID = 4437
ALLOWED_CHAT_ID = -1002387080797
WEBHOOK_URL = f"https://t1-vault-bot.onrender.com/{TELEGRAM_API_TOKEN}"

# Instantiate the Bot and the Application (no .run_webhook!)
bot = Bot(token=TELEGRAM_API_TOKEN)
appbuilder = ApplicationBuilder().token(TELEGRAM_API_TOKEN)
bot_app = appbuilder.build()

@app.route("/")
def index():
    return "T1 Vault Bot is running!"

@app.route(f"/{TELEGRAM_API_TOKEN}", methods=["POST"])
def telegram_webhook():
    """Receive updates from Telegram via Flask."""
    update = Update.de_json(request.get_json(force=True), bot)
    bot_app.update_queue.put_nowait(update)
    return "OK", 200

def get_paypal_balance():
    """Example helper for PayPal calls."""
    try:
        auth_response = requests.post(
            "https://api.paypal.com/v1/oauth2/token",
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET_KEY),
            data={"grant_type": "client_credentials"},
        )
        auth_response.raise_for_status()
        access_token = auth_response.json().get("access_token")

        balance_response = requests.get(
            "https://api.paypal.com/v1/reporting/balances",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        balance_response.raise_for_status()

        balances = balance_response.json().get("balances", [])
        for balance in balances:
            if balance.get("currency_code") == "USD":
                return float(balance.get("total_balance", {}).get("value", 0))
        return 0.0
    except Exception as e:
        print(f"Error retrieving PayPal balance: {e}")
        return 0.0

async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global goal_inventory
    username = f"@{update.effective_user.username}".lower() if update.effective_user.username else None
    if username not in AUTHORIZED_USERS:
        await update.message.reply_text("You are not authorized to set the vault goal.")
        return
    try:
        goal_inventory = float(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
        await update.message.reply_text(f"Vault goal updated to ${goal_inventory:.2f}.")
        bot = context.bot
        announcement = f"Gentlemen, the Vault goal has been set to ${goal_inventory:.2f}."
        if reason:
            announcement += f" Reason: {reason}"
        await bot.send_message(chat_id=ALLOWED_CHAT_ID, message_thread_id=ALLOWED_TOPIC_ID, text=announcement)
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a number.")

async def set_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTHORIZED_USERS
    user_id = update.effective_user.id
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text("Only the bot owner can set authorized users.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Please specify at least one username. Example: /setauthorized @username")
        return

    new_users = []
    for username in context.args:
        if username.startswith("@"):
            username_lower = username.lower()
            AUTHORIZED_USERS.add(username_lower)
            new_users.append(username_lower)

    if new_users:
        await update.message.reply_text(f"Authorized users updated: {', '.join(new_users)}")

def main():
    # Register handlers
    bot_app.add_handler(CommandHandler("setgoal", set_goal))
    bot_app.add_handler(CommandHandler("setauthorized", set_authorized))

    # Important: Set webhook once so Telegram knows where to send updates
    bot.set_webhook(url=WEBHOOK_URL)

    # Finally, run Flask on Render’s assigned port
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
