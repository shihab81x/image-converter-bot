#!/usr/bin/env python3
"""
Image Converter Bot for Telegram
Converts images between formats: JPG, PNG, WEBP, BMP, GIF, ICO, TIFF
Optimized for Render free tier (512MB RAM) + Cloudflare
"""

import os
import gc
import time
import logging
import asyncio
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from converter import (
    get_image_info, convert_image, batch_convert,
    cleanup_file, cleanup_batch,
    SUPPORTED_FORMATS, RESIZE_PRESETS, COMPRESS_QUALITY,
    MAX_FILE_SIZE_MB
)

# ============ CONFIG (from env vars) ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # e.g. https://your-app.onrender.com
PORT = int(os.environ.get("PORT", 8080))

TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
FILE_EXPIRY_SECONDS = 300  # 5 minutes
MAX_BATCH = 5  # reduced from 10 for RAM safety

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory user state
user_state = {}  # user_id -> {"files": [], "format": None, "quality": None, "resize": None}
file_timestamps = {}  # file_path -> creation_time


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Convert Image"), KeyboardButton("Batch Convert")],
            [KeyboardButton("Resize Image"), KeyboardButton("Compress Image")],
            [KeyboardButton("Help"), KeyboardButton("About")],
        ],
        resize_keyboard=True,
    )


def format_keyboard():
    buttons = []
    row = []
    for fmt in SUPPORTED_FORMATS:
        row.append(InlineKeyboardButton(fmt, callback_data=f"fmt_{fmt}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def quality_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Low (40)", callback_data="q_low"),
            InlineKeyboardButton("Medium (65)", callback_data="q_medium"),
        ],
        [
            InlineKeyboardButton("High (85)", callback_data="q_high"),
            InlineKeyboardButton("Max (95)", callback_data="q_maximum"),
        ],
    ])


def resize_keyboard():
    buttons = []
    row = []
    for name, (w, h) in RESIZE_PRESETS.items():
        row.append(InlineKeyboardButton(name, callback_data=f"resize_{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    buttons.append([InlineKeyboardButton("No Resize", callback_data="resize_none")])
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


# ============ AUTO CLEANUP ============

def cleanup_expired_files():
    """Delete temp files older than 5 minutes."""
    now = time.time()
    expired = [
        fpath for fpath, ts in file_timestamps.items()
        if now - ts > FILE_EXPIRY_SECONDS
    ]
    for fpath in expired:
        cleanup_file(fpath)
        file_timestamps.pop(fpath, None)
    if expired:
        gc.collect()  # free memory after cleanup
        logger.info(f"Auto-cleaned {len(expired)} expired files")


def track_file(file_path):
    file_timestamps[file_path] = time.time()


# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and don't crash the bot."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text(
                "Something went wrong. Please try again.",
                reply_markup=main_keyboard()
            )
        except:
            pass


# ============ COMMANDS ============

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Image Converter Bot</b>\n\n"
        "Supported formats: JPG, PNG, WEBP, BMP, GIF, ICO, TIFF\n\n"
        "<b>Features:</b>\n"
        "- Format conversion\n"
        "- Resize (512x512, 1024x1024, 1280x720, 1920x1080)\n"
        "- Compress (low/medium/high/max quality)\n"
        f"- Batch convert (up to {MAX_BATCH} images)\n\n"
        f"<b>Note:</b> Max file size: {MAX_FILE_SIZE_MB}MB. Files auto-deleted in 5 min.\n\n"
        "Send me an image or use the buttons below.\n"
        "Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>How to use:</b>\n\n"
        "1. Send any image to the bot\n"
        "2. Choose output format\n"
        "3. Select quality and resize options\n"
        "4. Download converted image\n\n"
        f"<b>Batch:</b> Send multiple images (max {MAX_BATCH}), then choose format.\n\n"
        "<b>Commands:</b>\n"
        "/start - Start bot\n"
        "/help - This message\n"
        "/about - Bot info & file storage details\n"
        "/cancel - Cancel current operation\n\n"
        "Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
    )


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Image Converter Bot</b>\n\n"
        "Image format converter for Telegram.\n"
        "Supported: JPG, PNG, WEBP, BMP, GIF, ICO, TIFF\n\n"
        "<b>Features:</b>\n"
        "- Format conversion\n"
        "- Resize & Compress\n"
        f"- Batch convert (up to {MAX_BATCH} images)\n\n"
        "<b>File Storage:</b>\n"
        "Your uploaded images are stored temporarily on the server.\n"
        "All files are automatically deleted within 5 minutes after conversion.\n"
        "No images are permanently stored.\n\n"
        "Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.pop(uid, None)
    if state and state.get("files"):
        cleanup_batch(state["files"])
    gc.collect()
    await update.message.reply_text(
        "Operation cancelled.", reply_markup=main_keyboard()
    )


# ============ MESSAGE HANDLERS ============

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_files()
    uid = update.effective_user.id

    # Check batch limit
    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(
            f"Max {MAX_BATCH} images at a time. Convert or /cancel first."
        )
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    os.makedirs(TEMP_DIR, exist_ok=True)
    ext = file.file_path.rsplit(".", 1)[-1] if file.file_path else "jpg"
    local_path = os.path.join(TEMP_DIR, f"{uid}_{photo.file_unique_id}.{ext}")
    await file.download_to_drive(local_path)
    track_file(local_path)

    info = get_image_info(local_path)

    if "error" in info:
        await update.message.reply_text(f"Error: {info['error']}")
        cleanup_file(local_path)
        return

    if uid not in user_state:
        user_state[uid] = {"files": [], "format": None, "quality": "high", "resize": None}

    user_state[uid]["files"].append(local_path)
    file_count = len(user_state[uid]["files"])

    await update.message.reply_text(
        f"<b>Image #{file_count} received!</b>\n\n"
        f"Format: {info['format']}\n"
        f"Resolution: {info['width']}x{info['height']}\n"
        f"Size: {info['size_mb']} MB\n\n"
        "<b>Choose output format:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=format_keyboard(),
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_files()
    uid = update.effective_user.id
    doc = update.message.document

    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text("Please send an image file (JPG, PNG, WEBP, etc.)")
        return

    # Check batch limit
    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(
            f"Max {MAX_BATCH} images at a time. Convert or /cancel first."
        )
        return

    file = await context.bot.get_file(doc.file_id)
    ext = doc.file_name.rsplit(".", 1)[-1] if doc.file_name else "jpg"
    local_path = os.path.join(TEMP_DIR, f"{uid}_{doc.file_unique_id}.{ext}")
    await file.download_to_drive(local_path)
    track_file(local_path)

    info = get_image_info(local_path)
    if "error" in info:
        await update.message.reply_text(f"Error: {info['error']}")
        cleanup_file(local_path)
        return

    if uid not in user_state:
        user_state[uid] = {"files": [], "format": None, "quality": "high", "resize": None}

    user_state[uid]["files"].append(local_path)
    file_count = len(user_state[uid]["files"])

    await update.message.reply_text(
        f"<b>Image #{file_count} received!</b>\n\n"
        f"Format: {info['format']}\n"
        f"Resolution: {info['width']}x{info['height']}\n"
        f"Size: {info['size_mb']} MB\n\n"
        "<b>Choose output format:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=format_keyboard(),
    )


async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "Convert Image":
        await update.message.reply_text("Send me an image and I'll convert it.")
    elif text == "Batch Convert":
        await update.message.reply_text(
            f"Send me multiple images (up to {MAX_BATCH}), then choose format."
        )
    elif text == "Resize Image":
        await update.message.reply_text("Send an image first, then choose a resize preset.")
    elif text == "Compress Image":
        await update.message.reply_text("Send an image first, then choose quality level.")
    elif text == "Help":
        await cmd_help(update, context)
    elif text == "About":
        await cmd_about(update, context)


# ============ CALLBACK HANDLERS ============

async def on_format_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    fmt = query.data.replace("fmt_", "")

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("No images found. Send an image first.")
        return

    user_state[uid]["format"] = fmt
    file_count = len(user_state[uid]["files"])

    await query.edit_message_text(
        f"Converting {file_count} image(s) to <b>{fmt}</b>\n\n"
        "<b>Choose quality:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=quality_keyboard(),
    )


async def on_quality_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    quality = query.data.replace("q_", "")

    if uid not in user_state:
        await query.edit_message_text("Session expired. Send image again.")
        return

    user_state[uid]["quality"] = quality

    await query.edit_message_text(
        f"Quality: <b>{quality}</b>\n\n"
        "<b>Choose resize option (or skip):</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=resize_keyboard(),
    )


async def on_resize_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    resize = query.data.replace("resize_", "")
    if resize == "none":
        resize = None

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("Session expired. Send image again.")
        return

    user_state[uid]["resize"] = resize
    state = user_state[uid]
    files = state["files"]
    fmt = state["format"]
    quality = state["quality"]

    await query.edit_message_text(
        f"Converting {len(files)} image(s)...\n"
        f"Format: {fmt} | Quality: {quality} | Resize: {resize or 'None'}\n\n"
        "Please wait...",
        parse_mode=ParseMode.HTML,
    )

    # Convert one at a time to save RAM
    output_files = []
    errors = []

    for fpath in files:
        try:
            out = convert_image(fpath, fmt, quality, resize)
            track_file(out)
            output_files.append(out)
            gc.collect()  # gc after each conversion
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: {e}")

    # Send converted files
    if output_files:
        for out in output_files:
            try:
                with open(out, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=f,
                        caption=f"Converted: {os.path.basename(out)}",
                    )
            except Exception as e:
                errors.append(f"Send failed: {e}")

    # Summary
    summary = f"<b>Conversion complete!</b>\n\nConverted: {len(output_files)}\n"
    if errors:
        summary += f"\nErrors:\n" + "\n".join(errors[:5])

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=summary,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )

    # Cleanup
    for f in files + output_files:
        file_timestamps.pop(f, None)
    cleanup_batch(files)
    cleanup_batch(output_files)
    user_state.pop(uid, None)
    gc.collect()


# ============ MAIN ============

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN environment variable not set!")
        print("Set it in Render dashboard or export BOT_TOKEN='your_token'")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Error handler — prevents crashes
    app.add_error_handler(error_handler)

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    # Photos and documents
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

    # Reply keyboard buttons
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text_buttons
    ))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(on_format_selected, pattern=r"^fmt_"))
    app.add_handler(CallbackQueryHandler(on_quality_selected, pattern=r"^q_"))
    app.add_handler(CallbackQueryHandler(on_resize_selected, pattern=r"^resize_"))

    # ============ WEBHOOK MODE (for Render + Cloudflare) ============
    if WEBHOOK_URL:
        webhook_path = f"/webhook/{BOT_TOKEN}"
        full_url = f"{WEBHOOK_URL}{webhook_path}"
        print(f"Starting webhook mode on port {PORT}...")
        print(f"Webhook URL: {full_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_url,
            drop_pending_updates=True,
        )
    else:
        # Fallback to polling (for local testing)
        print("No WEBHOOK_URL set — starting polling mode...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
