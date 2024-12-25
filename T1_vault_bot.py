import asyncio
import json
import logging
import os
import pytz
import requests
import tornado.ioloop
import tornado.httpserver
import tornado.web

from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)
import paypalrestsdk

logging.basicConfig(level=logging.INFO)

# -------------------------
#  ENV VARS & PAYPAL CONFIG
# -------------------------
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET_KEY = os.getenv("PAYPAL_SECRET_KEY")

if not TELEGRAM_API_TOKEN:
    raise ValueError("TELEGRAM_API_TOKEN not set.")
if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET_KEY:
    raise ValueError("PayPal credentials not set.")

paypalrestsdk.configure({
    "mode": "live",  # or "sandbox" if testing
    "client_id": PAYPAL_CLIENT_ID,
    "client_secret": PAYPAL_SECRET_KEY
})

# -------------------------
#  GLOBALS
# -------------------------
goal_inventory = 1000.0
AUTHORIZED_USERS = set()
BOT_OWNER_ID = 6451807462
ALLOWED_TOPIC_ID = 4437
ALLOWED_CHAT_ID = -1002387080797

# For Telegram webhook
# Example: https://your-service.onrender.com/<TELEGRAM_API_TOKEN>
WEBHOOK_URL = f"https://t1-vault-bot.onrender.com/{TELEGRAM_API_TOKEN}"

# PayPal donation link (optional command)
PAYPAL_DONATION_LINK = "https://www.paypal.com/ncp/payment/URH8ZBQYMY9KY"


# -------------------------
#  TIME GREETING
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
#  TELEGRAM COMMANDS
# -------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    greeting = get_eastern_greeting()
    text = (
        f"{greeting} sir! As the T1 Vault Bot, I am at your service.\n"
        "Say /vault to see the current vault inventory.\n"
        "Say /donate to contribute to the vault."
    )
    await update.message.reply_text(text)

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Current vault inventory is ${goal_inventory:.2f}."
    )

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Thank you for your interest in contributing to the vault!\n"
        f"Please visit: {PAYPAL_DONATION_LINK}"
    )
    await update.message.reply_text(text)

async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global goal_inventory
    username = (f"@{update.effective_user.username}".lower()
                if update.effective_user.username else None)
    if username not in AUTHORIZED_USERS:
        await update.message.reply_text("You are not authorized to set the vault goal.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setgoal <amount> [reason]")
        return
    
    try:
        amount = float(context.args[0])
        goal_inventory = amount
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None

        await update.message.reply_text(f"Vault goal updated to ${goal_inventory:.2f}.")

        announcement = f"Gentlemen, the Vault goal is now ${goal_inventory:.2f}."
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
        await update.message.reply_text("Usage: /setauthorized @username1 @username2 ...")
        return
    
    new_users = []
    for username in context.args:
        if username.startswith("@"):
            lower_u = username.lower()
            AUTHORIZED_USERS.add(lower_u)
            new_users.append(lower_u)

    if new_users:
        await update.message.reply_text(f"Authorized users updated: {', '.join(new_users)}")
    else:
        await update.message.reply_text("No valid @usernames found.")


# -------------------------
#  PAYPAL WEBHOOK HANDLER
# -------------------------
class PayPalWebhookHandler(tornado.web.RequestHandler):
    """
    Tornado handler for PayPal events at /paypal-webhook.
    In production: verify signature to ensure the request is really from PayPal!
    """

    def initialize(self, telegram_app):
        # We'll store a reference to the PTB Application so we can call bot.send_message
        self.telegram_app = telegram_app

    async def post(self):
        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            logging.error("PayPal webhook: Invalid JSON")
            self.set_status(400)
            self.finish("Invalid JSON")
            return

        event_type = data.get("event_type")
        resource = data.get("resource", {})

        # For example, handle 'PAYMENT.SALE.COMPLETED'
        if event_type == "PAYMENT.SALE.COMPLETED":
            amount = resource.get("amount", {}).get("total", "0.00")
            payer_info = resource.get("payer", {}).get("payer_info", {})
            first_name = payer_info.get("first_name", "").strip() or "someone"

            text = (
                f"**Donation Received**\n"
                f"{first_name} donated ${amount} to the vault.\n"
                "Thank you! 🎉"
            )
            # Announce in your chat
            await self.telegram_app.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=ALLOWED_TOPIC_ID,
                text=text,
                parse_mode="Markdown"
            )

        self.set_status(200)
        self.finish("OK")


# -------------------------
#  ASYNC SETUP & MAIN
# -------------------------
async def run_bot_and_server():
    """
    1) Build the PTB Application (no run_webhook).
    2) Build a Tornado server with 2 routes:
       - /<TELEGRAM_API_TOKEN>  -> PTB's webhook handler
       - /paypal-webhook        -> our PayPalWebhookHandler
    3) Initialize & start the PTB app, set the Telegram webhook,
       then start Tornado's IO loop (forever).
    """

    # 1) PTB Application
    application = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # Register commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("donate", donate_command))
    application.add_handler(CommandHandler("setgoal", set_goal))
    application.add_handler(CommandHandler("setauthorized", set_authorized))

    # 2) Build the Tornado web app
    #   - We ask PTB for a tornado RequestHandler that handles Telegram updates at /<bot_token>
    telegram_handler_class = application.create_webhook_handler()

    tornado_app = tornado.web.Application([
        (fr"/{TELEGRAM_API_TOKEN}", telegram_handler_class),
        (r"/paypal-webhook", PayPalWebhookHandler, dict(telegram_app=application)),
    ])

    # 3) Initialize & start the PTB application
    await application.initialize()
    await application.start()

    # Set Telegram’s webhook so it knows to POST updates to /<TELEGRAM_API_TOKEN>
    await application.bot.set_webhook(WEBHOOK_URL)

    # 4) Start the Tornado server on your Render-assigned port
    port = int(os.getenv("PORT", "5000"))
    server = tornado.httpserver.HTTPServer(tornado_app)
    server.bind(port)
    server.start(1)  # 1 process; you could use 0 to autodetect CPU

    logging.info(f"Bot + Tornado server started on port {port}. Now entering IOLoop...")

    # Keep running forever
    try:
        tornado.ioloop.IOLoop.current().start()
    finally:
        logging.info("Shutting down PTB application...")
        await application.shutdown()
        await application.stop()


def main():
    asyncio.run(run_bot_and_server())


if __name__ == "__main__":
    main()
