import paypalrestsdk
import matplotlib.pyplot as plt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import os

# PayPal Configuration
paypalrestsdk.configure({
    "mode": "live",  # Change to "live" for production
    "client_id": "PAYPAL_CLIENT_ID",
    "client_secret": "PAYPAL_SECRET_KEY"
})

# Telegram Bot Token
TELEGRAM_API_TOKEN = "TELEGRAM_API_TOKEN"

# Placeholder for vault Info
current_inventory = 500  # Example: Starting vault amount
goal_inventory = 1000    # Goal for the vault

# Function to Generate Progress Bar
def generate_progress_bar(current, goal):
    progress = current / goal
    plt.figure(figsize=(8, 2))
    plt.barh(['Vault Inventory'], [goal], color='gray', label='Goal')
    plt.barh(['Vault Inventory'], [current], color='green', label='Current')
    plt.xlim(0, goal)
    plt.title(f"Vault Inventory: ${current} / ${goal}")
    plt.xlabel("Amount in USD")
    plt.legend()

    # Save the chart
    plt.tight_layout()
    plt.savefig("vault_inventory.png")
    plt.close()

# Start Command Handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello, I am the T1 Vault Bot!\nUse /vault to see the current vault status.\nUse /donate to contribute to the vault.")

# vault Status Command
async def show_vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    generate_progress_bar(current_vault_inventory, goal_vault_inventory)
    chat_id = update.effective_chat.id
    await context.bot.send_photo(chat_id=chat_id, photo=open("vault_inventory.png", 'rb'), caption="Current Vault Inventory!")

# Donation Command
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Create a payment request
    payment = paypalrestsdk.Payment({
        "intent": "sale",
        "payer": {"payment_method": "paypal"},
        "redirect_urls": {
            "return_url": "https://github.com/NickHeight/success/blob/main/success.html",  # Replace with your return URL
            "cancel_url": "https://example.com/cancel"   # Replace with your cancel URL
        },
        "transactions": [{
            "amount": {"total": "10.00", "currency": "USD"},  # Default donation of $10
            "description": "Telegram Vault Contribution"
        }]
    })
async def get_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_thread_id = update.message.message_thread_id  # This is the topic ID
    await update.message.reply_text(
        f"Chat ID: {chat_id}\nTopic ID: {message_thread_id}"
    )


TARGET_TOPIC_ID = 4437  # Replace with the extracted Topic ID

async def restricted_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.message_thread_id == TARGET_TOPIC_ID:
        await update.message.reply_text("This bot is active in this topic.")
    else:
        await update.message.reply_text("This bot is restricted to another topic.")


    if payment.create():
        approval_url = next(link.href for link in payment.links if link.rel == "approval_url")
        await update.message.reply_text(f"To contribute, please complete your payment here: [Pay Now]({approval_url})", parse_mode="Markdown")
    else:
        await update.message.reply_text("Error creating payment. Please try again later.")

# Main Function
def main():
    # Build Application
    app = ApplicationBuilder().token(TELEGRAM_API_TOKEN).build()

    # Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vault", show_vault))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("gettopic", get_topic_id))

    # Start the Bot
    print("Bot is running...")
    app.run_polling()

    # Cleanup generated image
    if os.path.exists("vault_progress.png"):
        os.remove("vault_progress.png")

if __name__ == "__main__":
    main()
