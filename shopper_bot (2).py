import re
import sqlite3
from datetime import datetime
from typing import Dict, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ========== CONFIGURATION ==========
BOT_TOKEN = "8632072107:AAHIp1ztPQgRRIiyGWXin_6OTV6Pa-PySWo"
ADMIN_USER_ID = @kiyaadisu  # Your Telegram user ID (integer)
GROUP_ID = -1001234567890  # Your group ID (negative number, optional - if set, bot can restrict commands)
# ===================================

# Conversation states for /newproduct
NAME, BRAND, CATEGORY, DESCRIPTION, IMAGE = range(5)

# ---------- Database setup ----------
conn = sqlite3.connect("shopper_data.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    brand TEXT,
    category TEXT,
    description TEXT,
    image_url TEXT,
    approved BOOLEAN DEFAULT 0,
    created_by INTEGER,
    created_at TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    rating INTEGER,  -- 1 to 5
    review_text TEXT,
    pros TEXT,
    cons TEXT,
    tiktok_url TEXT,
    user_id INTEGER,
    username TEXT,
    message_id INTEGER,
    created_at TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER,
    reported_by INTEGER,
    reason TEXT,
    status TEXT DEFAULT 'pending'
)
""")
conn.commit()

# Helper: get or create product by name
def get_product_id(name: str) -> Optional[int]:
    cursor.execute("SELECT id FROM products WHERE name = ? AND approved = 1", (name,))
    row = cursor.fetchone()
    return row[0] if row else None

def add_product(name, brand, category, description, image_url, user_id):
    try:
        cursor.execute(
            "INSERT INTO products (name, brand, category, description, image_url, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, brand, category, description, image_url, user_id, datetime.now())
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None  # duplicate

def add_review(product_id, rating, review_text, pros, cons, tiktok_url, user_id, username, message_id):
    cursor.execute(
        "INSERT INTO reviews (product_id, rating, review_text, pros, cons, tiktok_url, user_id, username, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, rating, review_text, pros, cons, tiktok_url, user_id, username, message_id, datetime.now())
    )
    conn.commit()

# ---------- Review parser ----------
def parse_review(text: str) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Returns (rating, product_name, pros, cons, tiktok_url)
    rating: 1-5 or None
    """
    rating = None
    # Star rating: ⭐⭐⭐⭐ (count stars)
    stars = text.count('⭐')
    if stars in range(1, 6):
        rating = stars
    else:
        # Numeric rating like "4/5" or "4.5/5" (floor to int)
        match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*5', text)
        if match:
            rating = round(float(match.group(1)))
            if rating < 1: rating = 1
            if rating > 5: rating = 5

    # Product name: look for "Product:" or "Product name:" line
    product_match = re.search(r'(?:Product|Product name)[:\s]+([^\n]+)', text, re.IGNORECASE)
    product_name = product_match.group(1).strip() if product_match else None

    # Pros: after "Pros:" line
    pros_match = re.search(r'Pros?[:\s]+([^\n]+)', text, re.IGNORECASE)
    pros = pros_match.group(1).strip() if pros_match else None

    # Cons
    cons_match = re.search(r'Cons?[:\s]+([^\n]+)', text, re.IGNORECASE)
    cons = cons_match.group(1).strip() if cons_match else None

    # TikTok URL
    tiktok_match = re.search(r'(https?://(?:www\.)?tiktok\.com/\S+)', text)
    tiktok_url = tiktok_match.group(1) if tiktok_match else None

    return rating, product_name, pros, cons, tiktok_url

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the ShopperVerse bot!\n\n"
        "📝 To review a product, post a message with:\n"
        "- Star rating (⭐⭐⭐⭐⭐) or number (4/5)\n"
        "- Product: [name]\n"
        "- Pros: ...\n"
        "- Cons: ...\n"
        "- (Optional) TikTok URL\n\n"
        "➕ To add a new product, send /newproduct in a private chat with me.\n"
        "🚨 See a bad review? Click the 'Report' button under it."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    text = message.text
    user = message.from_user
    rating, product_name, pros, cons, tiktok_url = parse_review(text)

    if rating is None or product_name is None:
        return  # not a valid review format

    # Check if product exists
    product_id = get_product_id(product_name)
    if not product_id:
        await message.reply_text(f"❌ Product '{product_name}' not found. Use /newproduct to add it first (in private chat).")
        return

    # Save review
    add_review(product_id, rating, text, pros, cons, tiktok_url, user.id, user.username or user.first_name, message.message_id)

    # Acknowledge
    await message.reply_text(f"✅ Review for **{product_name}** saved! (Rating: {rating}★)")

    # Add Report button to the original message (optional: we can edit the original message to add button)
    # But we cannot edit other people's messages easily. Instead, reply with a button that reports the parent.
    keyboard = [[InlineKeyboardButton("🚨 Report this review", callback_data=f"report_{message.message_id}")]]
    await message.reply_text("Found a problem? Click below:", reply_markup=InlineKeyboardMarkup(keyboard))

async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("report_"):
        original_msg_id = int(data.split("_")[1])
        reporter = query.from_user
        # Store report in DB (simplified: just forward to admin)
        await context.bot.forward_message(chat_id=ADMIN_USER_ID, from_chat_id=query.message.chat_id, message_id=original_msg_id)
        await context.bot.send_message(ADMIN_USER_ID, f"Reported by @{reporter.username or reporter.first_name}")
        await query.edit_message_text("📢 Reported to admin. Thanks!")

# ---------- Product submission conversation (private chat) ----------
async def newproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use /newproduct in a private chat with me.")
        return ConversationHandler.END
    await update.message.reply_text("Let's add a new product.\nWhat is the **product name**?")
    return NAME

async def newproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text("What is the **brand**?")
    return BRAND

async def newproduct_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['brand'] = update.message.text.strip()
    await update.message.reply_text("Which **category**? (e.g., Electronics, Beauty, Home)")
    return CATEGORY

async def newproduct_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['category'] = update.message.text.strip()
    await update.message.reply_text("Short **description** of the product:")
    return DESCRIPTION

async def newproduct_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text.strip()
    await update.message.reply_text("(Optional) Send an **image URL** or type 'skip'")
    return IMAGE

async def newproduct_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() != 'skip':
        context.user_data['image_url'] = text
    else:
        context.user_data['image_url'] = None

    # Save product (pending approval)
    product_id = add_product(
        context.user_data['name'],
        context.user_data['brand'],
        context.user_data['category'],
        context.user_data['description'],
        context.user_data['image_url'],
        update.effective_user.id
    )
    if product_id is None:
        await update.message.reply_text("❌ A product with that name already exists (or is pending approval).")
    else:
        # Notify admin
        await context.bot.send_message(
            ADMIN_USER_ID,
            f"🆕 New product pending approval:\n"
            f"Name: {context.user_data['name']}\n"
            f"Brand: {context.user_data['brand']}\n"
            f"Category: {context.user_data['category']}\n"
            f"Description: {context.user_data['description']}\n"
            f"Submitted by @{update.effective_user.username or update.effective_user.first_name}\n"
            f"Use /approve_product {product_id} to approve."
        )
        await update.message.reply_text("✅ Product submitted for admin review. You'll be notified when approved.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Product submission cancelled.")
    return ConversationHandler.END

# ---------- Admin commands ----------
async def approve_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    try:
        product_id = int(context.args[0])
        cursor.execute("UPDATE products SET approved = 1 WHERE id = ?", (product_id,))
        conn.commit()
        if cursor.rowcount:
            await update.message.reply_text(f"Product ID {product_id} approved.")
        else:
            await update.message.reply_text("Product not found.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /approve_product <product_id>")

async def list_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return
    cursor.execute("SELECT id, review_id, status FROM reports WHERE status='pending' LIMIT 10")
    reports = cursor.fetchall()
    if not reports:
        await update.message.reply_text("No pending reports.")
    else:
        msg = "Pending reports:\n" + "\n".join(f"ID {r[0]} – review {r[1]}" for r in reports)
        await update.message.reply_text(msg)

# ---------- Main ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve_product", approve_product))
    app.add_handler(CommandHandler("reports", list_reports))

    # Review detection (only in groups, not private)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_message))

    # Report callback
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))

    # Product submission conversation (private)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newproduct", newproduct_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, newproduct_name)],
            BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, newproduct_brand)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, newproduct_category)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, newproduct_description)],
            IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newproduct_image)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()