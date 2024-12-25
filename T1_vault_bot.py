import os
import logging
import requests
import asyncio
import pytz

from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue
)
import paypalrestsdk

logging.basicConfig(level=logging.INFO)

# -------------- ENV --------------
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET_KEY = os.getenv("PAYPAL_SECRET_KEY")

if not TELEGRAM_API_TOKEN:
    raise ValueError("TELEGRAM_API_TOKEN is not set.")
if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET_KEY:
    raise ValueError("PayPal credentials not set.")

# PayPal config (live or sandbox)
paypalrestsdk.configure({
    "mode": "live",  # or "sandbox"
    "client_id": PAYPAL_CLIENT_ID,
    "client_secret": PAYPAL_SECRET_KEY
})

# -------------- GLOBALS --------------
goal_inventory = 1000.0
AUTHORIZED_USERS = set()
BOT_OWNER_ID = 6451807462  # your personal Telegram user_id
ALLOWED_TOPIC_ID = 4437
ALLOWED_CHAT_ID = -1002387080797

PAYPAL_DONATION_LINK = "https://www.paypal.com/ncp/payment/URH8ZBQYMY9KY"
known_transaction_ids = set()  # store transaction_ids we've already announced

# -------------- TIME GREETING --------------
def get_eastern_greeting() -> str:
    eastern = pytz.timezone("US/Eastern")
    now_est = datetime.now(eastern)
    hour = now_est.hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"

# -------------- GET PAYPAL BALANCE --------------
def get_paypal_balance() -> float:
    """
    Retrieve the current PayPal balance in USD from /v1/reporting/balances.
    Returns 0.0 if anything fails.
    """
    try:
        # 1) Get an OAuth2 token
        auth_resp = requests.post(
            "https://api.paypal.com/v1/oauth2/token",
            headers={"Accept": "application/json"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET_KEY),
            data={"grant_type": "client_credentials"},
        )
        auth_resp.raise_for_status()
        access_token = auth_resp.json()["access_token"]

        # 2) Retrieve the balances
        bal_resp = requests.get(
            "https://api.paypal.com/v1/reporting/balances",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        bal_resp.raise_for_status()
        data = bal_resp.json()

        for item in data.get("balances", []):
            if item.get("currency_code") == "USD":
                return float(item["total_balance"]["value"])
        return 0.0
    except Exception as e:
        logging.error(f"Error retrieving PayPal balance: {e}")
        return 0.0

# -------------- GET TRANSACTIONS --------------
def get_recent_paypal_transactions() -> list:
    """
    Calls /v1/reporting/transactions to get a list of recent transactions.
    We'll check the last 24h as an example. Adjust as you prefer.
    Each transaction might include 'transaction_id', 'transaction_info', etc.
    """
    try:
        # 1) OAuth2 token
        auth_resp = requests.post(
            "https://api.paypal.com/v1/oauth2/token",
            headers={"Accept": "application/json"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET_KEY),
            data={"grant_type": "client_credentials"},
        )
        auth_resp.raise_for_status()
        access_token = auth_resp.json()["access_token"]

        # 2) Build date range: last 1 day
        end_date = datetime.now().astimezone()
        start_date = end_date - timedelta(days=1)
        # Format: "YYYY-MM-DDTHH:MM:SS-0700"
        # We'll assume local offset or UTC offset
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        # 3) GET transaction search
        url = "https://api.paypal.com/v1/reporting/transactions"
        params = {
            "start_date": start_str,
            "end_date": end_str,
            "fields": "all",
            "page_size": 50
        }
        tx_resp = requests.get(
            url, params=params,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        tx_resp.raise_for_status()
        data = tx_resp.json()

        # "transaction_details" is typically an array of transactions
        return data.get("transaction_details", [])
    except Exception as e:
        logging.error(f"Error retrieving recent PayPal transactions: {e}")
        return []

# -------------- JOB: POLL DONATIONS --------------
async def poll_paypal_donations(context: ContextTypes.DEFAULT_TYPE):
    """
    Periodically called. Fetches recent transactions from PayPal,
    checks if there's a new one we haven't announced, and announces it.
    """
    global known_transaction_ids

    transactions = get_recent_paypal_transactions()
    for item in transactions:
        tx_info = item.get("transaction_info", {})
        transaction_id = tx_info.get("transaction_id")
        if not transaction_id or transaction_id in known_transaction_ids:
            continue  # skip if we already saw it

        # Mark this transaction as known
        known_transaction_ids.add(transaction_id)

        # If this is an inbound (credit) transaction
        # PayPal docs: "transaction_info.transaction_amount.value" is the amount
        # "transaction_info.transaction_initiation_date" is the date
        # "payer_info.email_address" or "payer_info.payer_name.alternative_full_name" might exist
        transaction_amount = tx_info.get("transaction_amount", {}).get("value", "0.00")
        # This might be negative if it's money out, so check
        if tx_info.get("transaction_event_code", "").startswith("T00"):
            # or check if "transaction_amount.value" is > 0
            # Attempt to find donor name
            payer_info = item.get("payer_info", {})
            name = payer_info.get("payer_name", {}).get("alternate_full_name") or payer_info.get("email_address") or "someone"

            # Announce in Telegram
            message = (
                f"**Donation Received**\n"
                f"{name} donated ${transaction_amount} to the vault.\n"
                "Thank you! 🎉"
            )
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=ALLOWED_TOPIC_ID,
                text=message,
                parse_mode="Markdown"
            )

# -------------- TELEGRAM HANDLERS --------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    greeting = get_eastern_greeting()
    text = (
        f"{greeting} sir! As the T1 Vault Bot, I am at your service.\n"
        "Say /vault to see the current vault inventory.\n"
        "Say /donate to contribute to the vault."
    )
    await update.message.reply_text(text)

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Show current PayPal-based vault balance
    vault_balance = get_paypal_balance()
    # Optionally build an ASCII bar
    progress = (vault_balance / goal_inventory) * 100 if goal_inventory > 0 else 0
    progress = min(progress, 100.0)
    bar_length = 20
    filled = int(progress / 100 * bar_length)
    bar_str = "[" + "=" * filled + " " * (bar_length - filled) + "]"

    text = (
        f"Vault balance: ${vault_balance:.2f}\n"
        f"Goal: ${goal_inventory:.2f}\n"
        f"Progress: {bar_str} {progress:.1f}%\n\n"
        f"Donate here: {PAYPAL_DONATION_LINK}"
    )
    await update.message.reply_text(text)

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

# -------------- MAIN --------------
def main():
    application = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # Register commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("donate", donate_command))
    application.add_handler(CommandHandler("setgoal", set_goal))
    application.add_handler(CommandHandler("setauthorized", set_authorized))

    # Schedule the donation poll job
    # Runs every 60s. Adjust as desired. 
    job_queue = application.job_queue
    job_queue.run_repeating(poll_paypal_donations, interval=60, first=10)

    # Start polling Telegram for updates
    application.run_polling()

if __name__ == "__main__":
    main()
