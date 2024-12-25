import asyncio
import json
import logging
import os
import requests
import pytz

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
#  ENV & PAYPAL CONFIG
# -------------------------
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET_KEY = os.getenv("PAYPAL_SECRET_KEY")

if not TELEGRAM_API_TOKEN:
    raise ValueError("TELEGRAM_API_TOKEN not set.")
if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET_KEY:
    raise ValueError("PayPal credentials not set.")

paypalrestsdk.configure({
    "mode": "live",  # or "sandbox" if you're testing
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

# Example domain on Render:
WEBHOOK_URL = f"https://t1-vault-bot.onrender.com/{TELEGRAM_API_TOKEN}"
PAYPAL_DONATION_LINK = "https://www.paypal.com/ncp/payment/URH8ZBQYMY9KY"

# -------------------------
#  TIME-BASED GREETING
# -------------------------
def get_eastern_greeting() -> str:
    import pytz
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
    """Show the current 'goal_inventory' or a PayPal-based balance if preferred."""
    await update.message.reply_text(f"Current vault inventory is ${goal_inventory:.2f}.")


async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide a link to PayPal donation page."""
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

        # Announce to your group/thread
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
#  TORNADO HANDLERS
# -------------------------
class TelegramWebhookHandler(tornado.web.RequestHandler):
    """
    Handle Telegram updates at POST /<TELEGRAM_API_TOKEN>.
    We feed them into PTB's application.update_queue.
    """
    def initialize(self, ptb_application):
        self.ptb_app = ptb_application

    async def post(self):
        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            self.set_status(400)
            self.finish("Invalid JSON")
            return

        update = Update.de_json(data, self.ptb_app.bot)
        self.ptb_app.update_queue.put_nowait(update)

        self.set_status(200)
        self.finish("OK")


class PayPalWebhookHandler(tornado.web.RequestHandler):
    """
    Handle PayPal events at POST /paypal-webhook.
    In production, verify signatures from PayPal to ensure authenticity.
    """
    def initialize(self, ptb_application):
        self.ptb_app = ptb_application

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

        if event_type == "PAYMENT.SALE.COMPLETED":
            amount = resource.get("amount", {}).get("total", "0.00")
            payer_info = resource.get("payer", {}).get("payer_info", {})
            first_name = payer_info.get("first_name", "").strip() or "someone"

            text = (
                f"**Donation Received**\n"
                f"{first_name} donated ${amount} to the vault.\n"
                "Thank you! 🎉"
            )
            # Post in your group/thread
            await self.ptb_app.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=ALLOWED_TOPIC_ID,
                text=text,
                parse_mode="Markdown"
            )

        self.set_status(200)
        self.finish("OK")


# -------------------------
#  MAIN ASYNC SETUP
# -------------------------
async def run_bot_and_server():
    """
    1) Build & start PTB (manually).
    2) Set Telegram webhook to /<BOT_TOKEN>.
    3) Create Tornado routes for Telegram + PayPal.
    4) Listen on Render's PORT.
    5) Keep code alive with a 'while True' instead of stopping or shutting down.
    """
    # 1) Build the PTB application
    ptb_app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # Add commands
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(CommandHandler("vault", vault_command))
    ptb_app.add_handler(CommandHandler("donate", donate_command))
    ptb_app.add_handler(CommandHandler("setgoal", set_goal))
    ptb_app.add_handler(CommandHandler("setauthorized", set_authorized))

    # Start PTB
    await ptb_app.initialize()
    await ptb_app.start()
    logging.info("PTB Application started.")

    # 2) Tell Telegram to send updates to this route
    await ptb_app.bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Set Telegram webhook to {WEBHOOK_URL}")

    # 3) Tornado web app with two routes
    telegram_path = f"/{TELEGRAM_API_TOKEN}"
    tornado_app = tornado.web.Application([
        (telegram_path, TelegramWebhookHandler, dict(ptb_application=ptb_app)),
        (r"/paypal-webhook", PayPalWebhookHandler, dict(ptb_application=ptb_app)),
    ])

    # 4) Listen on Render's PORT
    port = int(os.getenv("PORT", "5000"))
    server = tornado.httpserver.HTTPServer(tornado_app)
    server.listen(port)
    logging.info(f"Tornado server listening on port {port}...")

    # 5) Keep this function alive so everything keeps running
    while True:
        await asyncio.sleep(3600)  # Sleep "forever"


def main():
    # We do NOT call tornado.ioloop.IOLoop.current().start().
    # Instead, we let 'while True: await asyncio.sleep()' block inside the same event loop.
    asyncio.run(run_bot_and_server())


if __name__ == "__main__":
    main()
