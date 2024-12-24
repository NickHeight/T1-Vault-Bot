import paypalrestsdk
import matplotlib.pyplot as plt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os

# PayPal Configuration
paypalrestsdk.configure({
    "mode": "live",  # Change to "sandbox" for testing
    "client_id": "YAcXIKsdC6uqEJXRHAaJhWPb9U3uS5XSsOmGPzU_MX-Pfdqqo1U034F2KdMjMnLZuWEs8nqJ8n_z4q9b9",
    "client_secret": "EJGCYbe4drVkKPnsTgZ_nvsrcEHjm2xpm8f3_jUv1nawqhM5sqd9DIsMzEjCOmKQ4_biT0qJHG9mAXOcHtayk5hRuaZrEdUaTEi1TgZ6wOzFaB3DjANWaV2vEbkR0Cu3PBB61GM2CgRtQ2HoW5pVNs3lePUiWBL1"
})

# Telegram Bot Token
TELEGRAM_API_TOKEN = "7498848163:AAGgOF6GSWp40oq2jYUEhq55Ja3jLWnwzNg"

# Vault Inventory Info
current_vault_inventory = 500  # Current vault balance
goal_vault_inventory = 1000    # Vault goal

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
    await update.message.reply_text(
        "Hello, I am the T1 Vault Bot!\n"
        "Use /vault to see the current vault status.\n"
        "Use /donate to contribute to the vault."
    )

# Vault Status Command
async def show_vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    generate_progress_bar(current_vault_inventory, goal_vault_inventory)
    chat_id = update.effective_chat.id
    try:
        with open("vault_inventory.png", 'rb') as photo:
            await context.bot.send_photo(chat_id=chat_id, photo=photo, caption="Current Vault Inventory!")
    finally:
        # Clean up the generated image
        if os.path.exists("vault_inventory.png"):
            os.remove("vault_inventory.png")

# Donation Command
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Create a payment request
    payment = paypalrestsdk.Payment({
        "intent": "sale",
        "payer": {"payment_method": "paypal"},
        "redirect_urls": {
            "return_url": "https://yourdomain.com/success",  # Replace with your return URL
            "cancel_url": "https://yourdomain.com/cancel"   # Replace with your cancel URL
        },
        "transactions": [{
            "amount": {"total": "10.00", "currency": "USD"},  # Default donation of $10
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

# Command to Retrieve Topic ID
async def get_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_thread_id = update.message.message_thread_id  # This is the topic ID
    await update.message.reply_text(f"Chat ID: {chat_id}\nTopic ID: {message_thread_id}")

# Restricted Handler for Specific Topics
TARGET_TOPIC_ID = 4437  # Replace with the extracted Topic ID
async def restricted_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.message_thread_id == TARGET_TOPIC_ID:
        await update.message.reply_text("This bot is active in this topic.")
    else:
        await update.message.reply_text("This bot is restricted to another topic.")

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

if __name__ == "__main__":
    main()
