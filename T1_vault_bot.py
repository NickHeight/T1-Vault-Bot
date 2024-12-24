import paypalrestsdk
import matplotlib.pyplot as plt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os

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

# Vault Goal
goal_inventory = 1000  # Vault target amount in USD

# Allowed Topic ID
ALLOWED_TOPIC_ID = 4437  # Replace with your specific Topic ID

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

# Function to Generate Progress Bar
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
    plt.savefig("vault_inventory.png")
    plt.close()

# Restrict to Allowed Topic
def is_valid_topic(update: Update) -> bool:
    """Check if the message is in the allowed topic."""
    return update.message.message_thread_id == ALLOWED_TOPIC_ID

# Start Command Handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_topic(update):
        return
    await update.message.reply_text(
        "Hi Sir, I am the T1 Vault Bot!\n"
        "Use /vault to see the current vault status.\n"
        "Use /donate to contribute to the vault."
    )

# Vault Status Command
async def show_vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_topic(update):
        return
    current_inventory = get_paypal_balance()
    generate_progress_bar(current_inventory, goal_inventory)
    chat_id = update.effective_chat.id
    try:
        with open("vault_inventory.png", 'rb') as photo:
            await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=f"Vault Progress: ${current_inventory:.2f}")
    finally:
        if os.path.exists("vault_inventory.png"):
            os.remove("vault_inventory.png")

# Donation Command
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_topic(update):
        return
    payment = paypalrestsdk.Payment({
        "intent": "sale",
        "payer": {"payment_method": "paypal"},
        "redirect_urls": {
            "return_url": "https://github.com/NickHeight/success/blob/main/success.html",
            "cancel_url": "https://github.com/NickHeight/Cancel/blob/main/cancel.html"
        },
        "transactions": [{
            "amount": {"total": "10.00", "currency": "USD"},
            "description": "Telegram Vault Contribution"
        }]
    })

    if payment.create():
        approval_url = next(link.href for link in payment.links if link.rel == "approval_url")
        await update.message.reply_text(
            f"To contribute, please complete your payment here: [Pay Now]({approval_url})",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Error creating payment. Please try again later.")

# Main Function
def main():
    print(f"Loaded Telegram Token: {TELEGRAM_API_TOKEN[:5]}... (truncated for security)")
    app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vault", show_vault))
    app.add_handler(CommandHandler("donate", donate))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    # Dummy port binding for Render's web service requirement
    port = int(os.getenv("PORT", 5000))
    print(f"Bot is running on port {port}...")
    main()

if __name__ == "__main__":
    main()
