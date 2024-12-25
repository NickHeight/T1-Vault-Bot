import os
import json
import logging
import requests
import pytz

from datetime import datetime
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)
from telegram import Update
import paypalrestsdk

# Tornado imports for custom route
import tornado.web

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
    "mode": "live",  # or "sandbox", must match your webhook environment
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

# Your Render domain + token path for Telegram
WEBHOOK_URL = f"https://t1-vault-bot.onrender.com/{TELEGRAM_API_TOKEN}"
# Donation link (if you still want /donate command)
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
#  TELEGRAM COMMAND HANDLERS
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
    """Show a static vault info or maybe retrieve the balance, etc."""
    message = f"Current vault inventory is ${goal_inventory:.2f}."
    await update.message.reply_text(message)


async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Thank you for your interest in contributing to the vault!\n"
        f"Please proceed here: {PAYPAL_DONATION_LINK}"
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
        goal_inventory = float(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None

        await update.message.reply_text(f"Vault goal updated to ${goal_inventory:.2f}.")

        # Announce to a group or a thread
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
        await update.message.reply_text("Usage: /setauthorized @username")
        return
    
    new_users = []
    for username in context.args:
        if username.startswith("@"):
            u_lower = username.lower()
            AUTHORIZED_USERS.add(u_lower)
            new_users.append(u_lower)

    if new_users:
        await update.message.reply_text(f"Authorized users updated: {', '.join(new_users)}")
    else:
        await update.message.reply_text("No valid @usernames given.")


# -------------------------
#  PAYPAL WEBHOOK HANDLER
# -------------------------
class PayPalWebhookHandler(tornado.web.RequestHandler):
    """
    Tornado handler for PayPal webhook events.
    We'll parse the JSON, check if it's a donation event, 
    and announce the FIRST name only.
    
    In production, also verify the PayPal signature from the headers.
    """
    def initialize(self, application):
        self.application = application  # the PTB "Application" reference

    async def post(self):
        # Parse the JSON body
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
            # Example resource structure for classic 'PAYMENT.SALE.COMPLETED'
            amount = resource.get("amount", {}).get("total", "0.00")
            payer_info = resource.get("payer", {}).get("payer_info", {})
            email = payer_info.get("email")
            first_name = payer_info.get("first_name", "").strip()

            # If no first name is given, optionally fallback to "someone"
            # or you could do "email.split('@')[0]" if you want partial email
            donor_name = first_name if first_name else "someone"

            text = (
                f"**Donation Received**\n"
                f"{donor_name} donated ${amount} to the vault.\n"
                f"Thank you! 🎉"
            )
            # Send message to your group/thread
            await self.application.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=ALLOWED_TOPIC_ID,
                text=text,
                parse_mode="Markdown"
            )

        self.set_status(200)
        self.finish("OK")


# -------------------------
#  MAIN (run_webhook with a custom Tornado app)
# -------------------------
def main():
    from telegram.ext import Application

    # 1) Create PTB Application
    application = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # 2) Register Telegram command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("donate", donate_command))
    application.add_handler(CommandHandler("setgoal", set_goal))
    application.add_handler(CommandHandler("setauthorized", set_authorized))

    # 3) Build a Tornado web_app that has a route for /paypal-webhook
    paypal_webhook_app = tornado.web.Application([
        (r"/paypal-webhook", PayPalWebhookHandler, dict(application=application)),
    ])

    # 4) Run in webhook mode, passing our custom Tornado routes
    port = int(os.getenv("PORT", "5000"))
    logging.info("Starting T1 Vault Bot with PayPal webhook route...")

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TELEGRAM_API_TOKEN,  # Path for Telegram updates
        webhook_url=WEBHOOK_URL,      # Tells Telegram where to send updates
        web_app=paypal_webhook_app    # Our Tornado routes (for PayPal)
    )

if __name__ == "__main__":
    main()
