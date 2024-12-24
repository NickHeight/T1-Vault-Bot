import asyncio
import os
from flask import Flask
from threading import Thread
import paypalrestsdk
import matplotlib.pyplot as plt
from PIL import Image

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Flask app for Render port binding
app = Flask(__name__)

# PayPal Configuration
paypalrestsdk.configure({
    "mode": "live",  # Change to "sandbox" for testing
    "client_id": os.getenv("PAYPAL_CLIENT_ID"),
    "client_secret": os.getenv("PAYPAL_SECRET_KEY")
})

# Telegram Bot Token
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")

if not TELEGRAM_API_TOKEN:
    raise ValueError("The TELEGRAM_API_TOKEN environment variable is not set. Please configure it correctly.")

# Vault Goal and Authorized Users
goal_inventory = 1000  # Vault target amount in USD
AUTHORIZED_USERS = set()  # Dynamic list of authorized users
BOT_OWNER_ID = 123456789  # Replace with your Telegram user ID

# Allowed Topic and Chat IDs
ALLOWED_TOPIC_ID = 4437
ALLOWED_CHAT_ID = -1002387080797

# Function to Retrieve PayPal Balance
def get_paypal_balance():
    try:
        balance_response = paypalrestsdk.Balance.retrieve()
        for currency in balance_response['balances']:
            if currency['currency_code'] == "USD":
                return float(currency['total_available'])
        return 0.0
    except Exception as e:
        print(f"Error retrieving PayPal balance: {e}")
        return 0.0

# Function to Generate Progress Bar with T1 Logo
def generate_progress_bar(current, goal):
    progress = current / goal if goal > 0 else 0
    plt.figure(figsize=(8, 2))
    plt.barh(['Vault Inventory'], [goal], color='gray', label='Goal')
    plt.barh(['Vault Inventory'], [current], color='green', label='Current Balance')
    plt.xlim(0, goal)
    plt.title(f"Vault Progress: ${current:.2f} / ${goal}")
    plt.xlabel("Amount in USD")
    plt.legend()
    plt.tight_layout()

    # Save the progress bar as a temporary image
    plt.savefig("vault_inventory_base.png")
    plt.close()

    # Add the T1 logo to the progress bar
    base_image = Image.open("vault_inventory_base.png")
    logo = Image.open("T1_logo.png").resize((100, 100))  # Adjust the size of the logo
    base_image.paste(logo, (20, 20), logo)  # Position the logo
    base_image.save("vault_inventory.png")

    # Clean up the base image
    os.remove("vault_inventory_base.png")

# Command to Update Goal Inventory
async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global goal_inventory

    # Check if the user is authorized
    username = f"@{update.effective_user.username}".lower() if update.effective_user.username else None
    if username not in AUTHORIZED_USERS:
        await update.message.reply_text("You are not authorized to set the vault goal.")
        return

    # Parse arguments
    if len(context.args) < 1:
        await update.message.reply_text("Please specify a valid goal amount. Example: /setgoal 1500 [Reason]")
        return

    try:
        goal_inventory = float(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None

        # Acknowledge privately
        await update.message.reply_text(f"Vault goal updated to ${goal_inventory:.2f}.")
        
        # Announce in the allowed topic
        announcement = f"Gentlemen, the Vault goal has been set to ${goal_inventory:.2f}."
        if reason:
            announcement += f" Reason: {reason}"
        bot = context.bot
        await bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            message_thread_id=ALLOWED_TOPIC_ID,
            text=announcement
        )
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a number. Example: /setgoal 1500 [Reason]")


# Command to Update Authorized Users Using Usernames
async def set_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTHORIZED_USERS

    # Check if the user is the bot owner
    user_id = update.effective_user.id
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text("Only the bot owner can set authorized users.")
        return

    # Parse arguments
    if len(context.args) < 1:
        await update.message.reply_text("Please specify at least one username. Example: /setauthorized @ceozorro @Lord_Malachai")
        return

    # Update authorized users
    new_users = []
    for username in context.args:
        if username.startswith("@"):
            new_users.append(username.lower())  # Convert to lowercase for consistency
        else:
            await update.message.reply_text(f"Invalid username format: {username}. Use '@' before usernames.")
            return

    AUTHORIZED_USERS.update(new_users)
    await update.message.reply_text(f"Authorized users updated: {', '.join(AUTHORIZED_USERS)}")


# Run Flask App for Render Port Binding
@app.route("/")
def index():
    return "T1 Vault Bot is running!"

def start_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Main Function
def main():
    print(f"Loaded Telegram Token: {TELEGRAM_API_TOKEN[:5]}... (truncated for security)")
    app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    app.add_handler(CommandHandler("setgoal", set_goal))
    app.add_handler(CommandHandler("setauthorized", set_authorized))

    print("Bot is running...")
    asyncio.run(app.run_polling())

if __name__ == "__main__":
    # Start Flask in a separate thread
    flask_thread = Thread(target=start_flask)
    flask_thread.start()

    # Start Telegram Bot
    main()
