#!/usr/bin/env python3
"""
Image Converter Bot for Telegram
Converts images between formats: JPG, PNG, WEBP, BMP, GIF, ICO, TIFF
Optimized for Render free tier (512MB RAM)
"""

import os
import gc
import time
import logging
import asyncio
import threading
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
    get_image_info, convert_image,
    cleanup_file, cleanup_batch,
    SUPPORTED_FORMATS, RESIZE_PRESETS, COMPRESS_QUALITY,
    MAX_FILE_SIZE_MB
)

# ============ CONFIG ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", 10000))

TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
FILE_EXPIRY_SECONDS = 300
MAX_BATCH = 5

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

user_state = {}
file_timestamps = {}


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
    for name in RESIZE_PRESETS:
        row.append(InlineKeyboardButton(name, callback_data=f"resize_{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    buttons.append([InlineKeyboardButton("No Resize", callback_data="resize_none")])
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def cleanup_expired_files():
    now = time.time()
    expired = [
        fpath for fpath, ts in file_timestamps.items()
        if now - ts > FILE_EXPIRY_SECONDS
    ]
    for fpath in expired:
        cleanup_file(fpath)
        file_timestamps.pop(fpath, None)
    if expired:
        gc.collect()
        logger.info(f"Auto-cleaned {len(expired)} expired files")


def track_file(file_path):
    file_timestamps[file_path] = time.time()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.reply_text(
                "Something went wrong. Please try again.",
                reply_markup=main_keyboard()
            )
        except Exception:
            pass


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
        "/about - Bot info\n"
        "/cancel - Cancel current operation\n\n"
        "Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
    )


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Image Converter Bot</b>\n\n"
        "Image format converter for Telegram.\n"
        "Supported: JPG, PNG, WEBP, BMP, GIF, ICO, TIFF\n\n"
        "<b>File Storage:</b>\n"
        "Files are stored temporarily and deleted within 5 minutes.\n\n"
        "Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.pop(uid, None)
    if state and state.get("files"):
        cleanup_batch(state["files"])
    gc.collect()
    await update.message.reply_text("Operation cancelled.", reply_markup=main_keyboard())


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_files()
    uid = update.effective_user.id

    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(f"Max {MAX_BATCH} images at a time. Convert or /cancel first.")
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

    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(f"Max {MAX_BATCH} images at a time. Convert or /cancel first.")
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
        await update.message.reply_text(f"Send me multiple images (up to {MAX_BATCH}), then choose format.")
    elif text == "Resize Image":
        await update.message.reply_text("Send an image first, then choose a resize preset.")
    elif text == "Compress Image":
        await update.message.reply_text("Send an image first, then choose quality level.")
    elif text == "Help":
        await cmd_help(update, context)
    elif text == "About":
        await cmd_about(update, context)


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
        f"Converting {file_count} image(s) to <b>{fmt}</b>\n\n<b>Choose quality:</b>",
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
        f"Quality: <b>{quality}</b>\n\n<b>Choose resize option (or skip):</b>",
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

    state = user_state[uid]
    files = state["files"]
    fmt = state["format"]
    quality = state["quality"]

    await query.edit_message_text(
        f"Converting {len(files)} image(s)...\n"
        f"Format: {fmt} | Quality: {quality} | Resize: {resize or 'None'}\n\nPlease wait...",
        parse_mode=ParseMode.HTML,
    )

    output_files = []
    errors = []

    for fpath in files:
        try:
            out = convert_image(fpath, fmt, quality, resize)
            track_file(out)
            output_files.append(out)
            gc.collect()
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: {e}")

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

    summary = f"<b>Conversion complete!</b>\n\nConverted: {len(output_files)}\n"
    if errors:
        summary += "\nErrors:\n" + "\n".join(errors[:5])

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=summary,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )

    for f in files + output_files:
        file_timestamps.pop(f, None)
    cleanup_batch(files)
    cleanup_batch(output_files)
    user_state.pop(uid, None)
    gc.collect()


# ============ HEALTH CHECK via PTB's built-in server ============

async def health_check(request):
    """
    Custom health endpoint handled by python-telegram-bot's webhook server.
    Render hits GET / — this returns 200 OK so the service stays 'live'.
    """
    from telegram.ext import BaseHandler
    from aiohttp import web
    return web.Response(text='{"status":"ok"}', content_type="application/json")


def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set. Add it in Render → Environment Variables.")
        return

    # Create a new event loop explicitly (fixes Python 3.14 compatibility)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))
    app.add_handler(CallbackQueryHandler(on_format_selected, pattern=r"^fmt_"))
    app.add_handler(CallbackQueryHandler(on_quality_selected, pattern=r"^q_"))
    app.add_handler(CallbackQueryHandler(on_resize_selected, pattern=r"^resize_"))

    if WEBHOOK_URL:
        webhook_path = "/webhook"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
        logger.info(f"Webhook mode → {full_webhook_url} on port {PORT}")

        # PTB's webhook server handles both /webhook (bot) and / (health check)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url,
            drop_pending_updates=True,
        )
    else:
        logger.info("Polling mode (local dev)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
