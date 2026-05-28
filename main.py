#!/usr/bin/env python3
"""
Image Converter Bot — Render Ready (Python 3.14 Compatible)
"""

import os
import gc
import time
import logging
import asyncio
import zipfile
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# ============ CONFIG ============
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT        = int(os.environ.get("PORT", 10000))

TEMP_DIR            = os.path.join(os.path.dirname(__file__), "temp")
FILE_EXPIRY_SECONDS = 300
MAX_BATCH           = 5
MAX_FILE_SIZE_MB    = 20
MAX_PIXELS          = 16_000_000

SUPPORTED_FORMATS = ["jpg", "jpeg", "png", "webp", "bmp", "gif", "ico", "tiff"]
RESIZE_PRESETS    = {"25%": 0.25, "50%": 0.50, "75%": 0.75, "1080p": 1080}
COMPRESS_QUALITY  = {"low": 40, "medium": 65, "high": 85, "maximum": 95}

os.makedirs(TEMP_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_state: dict = {}
file_timestamps: dict = {}
executor = ThreadPoolExecutor(max_workers=4)


# ══════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🖼 Convert"),  KeyboardButton("📦 Batch")],
            [KeyboardButton("📐 Resize"),     KeyboardButton("🗜 Compress")],
            [KeyboardButton("❓ Help"),       KeyboardButton("ℹ️ About")],
        ],
        resize_keyboard=True,
        input_field_placeholder="✨ Drop your image here...",
    )


def format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎨 JPG", callback_data="fmt_jpg"),
            InlineKeyboardButton("🌈 PNG", callback_data="fmt_png"),
            InlineKeyboardButton("⚡ WEBP", callback_data="fmt_webp"),
        ],
        [
            InlineKeyboardButton("🖌 BMP", callback_data="fmt_bmp"),
            InlineKeyboardButton("🎬 GIF", callback_data="fmt_gif"),
            InlineKeyboardButton("🎯 ICO", callback_data="fmt_ico"),
        ],
        [InlineKeyboardButton("📷 TIFF", callback_data="fmt_tiff")],
        [InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")],
    ])


def quality_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 Low (40%)", callback_data="q_low"),
            InlineKeyboardButton("🔷 Medium (65%)", callback_data="q_medium"),
        ],
        [
            InlineKeyboardButton("🔶 High (85%)", callback_data="q_high"),
            InlineKeyboardButton("👑 Max (95%)", callback_data="q_maximum"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")],
    ])


def resize_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 25%", callback_data="resize_25%"),
            InlineKeyboardButton("📱 50%", callback_data="resize_50%"),
        ],
        [
            InlineKeyboardButton("📱 75%", callback_data="resize_75%"),
            InlineKeyboardButton("🖥 1080p", callback_data="resize_1080p"),
        ],
        [
            InlineKeyboardButton("⏭ Skip Resize", callback_data="resize_none"),
            InlineKeyboardButton("❌ Cancel", callback_data="action_cancel"),
        ],
    ])


def output_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Separate Files", callback_data="out_individual"),
            InlineKeyboardButton("🗜 ZIP Archive", callback_data="out_zip"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")],
    ])


# ══════════════════════════════════════════════
#  CONVERTER ENGINE
# ══════════════════════════════════════════════

def get_image_info(path: str) -> dict:
    try:
        with Image.open(path) as img:
            size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
            return {
                "format": img.format or "UNKNOWN",
                "width": img.width,
                "height": img.height,
                "size_mb": size_mb,
            }
    except Exception as e:
        return {"error": str(e)}


def convert_image_sync(input_path: str, fmt: str, quality: str, resize: str | None) -> str:
    with Image.open(input_path) as img:
        img = img.copy()

        if img.width * img.height > MAX_PIXELS:
            ratio = (MAX_PIXELS / (img.width * img.height)) ** 0.5
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        if resize and resize != "none":
            if resize == "1080p":
                ratio = 1080 / img.height
                new_size = (int(img.width * ratio), 1080)
            else:
                ratio = RESIZE_PRESETS.get(resize, 1.0)
                new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        fmt_lower = fmt.lower()
        if fmt_lower in ("jpg", "jpeg"):
            pil_fmt, ext = "JPEG", "jpg"
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            save_kwargs = {"quality": COMPRESS_QUALITY.get(quality, 85), "optimize": True}
        elif fmt_lower == "png":
            pil_fmt, ext = "PNG", "png"
            save_kwargs = {"optimize": True}
        elif fmt_lower == "webp":
            pil_fmt, ext = "WEBP", "webp"
            save_kwargs = {"quality": COMPRESS_QUALITY.get(quality, 85), "method": 6}
        elif fmt_lower == "bmp":
            pil_fmt, ext = "BMP", "bmp"
            if img.mode == "RGBA":
                img = img.convert("RGB")
            save_kwargs = {}
        elif fmt_lower == "gif":
            pil_fmt, ext = "GIF", "gif"
            save_kwargs = {}
        elif fmt_lower == "ico":
            pil_fmt, ext = "ICO", "ico"
            img = img.convert("RGBA")
            save_kwargs = {}
        elif fmt_lower == "tiff":
            pil_fmt, ext = "TIFF", "tiff"
            save_kwargs = {}
        else:
            pil_fmt, ext = "JPEG", "jpg"
            save_kwargs = {"quality": 85}

        base = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(TEMP_DIR, f"{base}_converted.{ext}")
        img.save(output_path, format=pil_fmt, **save_kwargs)
        return output_path


async def convert_image_async(input_path: str, fmt: str, quality: str, resize: str | None) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, convert_image_sync, input_path, fmt, quality, resize)


def cleanup_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def cleanup_batch(paths: list):
    for p in paths:
        cleanup_file(p)


# ══════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════

def track_file(path: str):
    file_timestamps[path] = time.time()


def cleanup_expired_files():
    now = time.time()
    expired = [p for p, ts in list(file_timestamps.items()) if now - ts > FILE_EXPIRY_SECONDS]
    for p in expired:
        cleanup_file(p)
        file_timestamps.pop(p, None)
    if expired:
        gc.collect()
        logger.info(f"Cleaned {len(expired)} expired temp files")


def make_zip(output_files: list, uid: int) -> str:
    zip_path = os.path.join(TEMP_DIR, f"{uid}_converted.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in output_files:
            if os.path.exists(f):
                zf.write(f, arcname=os.path.basename(f))
    return zip_path


def new_state() -> dict:
    return {"files": [], "format": None, "quality": "high", "resize": None, "is_original": False}


def _quality_label(quality: str) -> str:
    labels = {"low": "💎 Low (40%)", "medium": "🔷 Medium (65%)", "high": "🔶 High (85%)", "maximum": "👑 Max (95%)"}
    return labels.get(quality, quality)


# ══════════════════════════════════════════════
#  ERROR HANDLER
# ══════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception:", exc_info=context.error)
    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.reply_text("⚠️ Something went wrong. Please try again!", reply_markup=main_keyboard())
        except Exception:
            pass


# ══════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name if user and user.first_name else "Friend"
    
    text = (
        f"👋 <b>Hey {name}!</b>\n\n"
        f"🎩 <b>Welcome to Image Converter Bot</b> — Premium Edition!\n\n"
        f"🔄 <b>Supported Formats:</b>\n"
        f"   JPG · PNG · WEBP · BMP · GIF · ICO · TIFF\n\n"
        f"✨ <b>What I can do:</b>\n"
        f"   • Convert between any format\n"
        f"   • Resize with 4 presets\n"
        f"   • Compress with quality control\n"
        f"   • Batch convert up to {MAX_BATCH} images\n"
        f"   • <b>Multiple users at once!</b> 🔥\n"
        f"   • Deliver as separate files or ZIP\n\n"
        f"📦 <b>Max file size:</b> {MAX_FILE_SIZE_MB}MB\n"
        f"🕐 <b>Auto-delete:</b> 5 minutes\n\n"
        f"💡 <b>Pro Tip:</b>\n"
        f"Send images as <b>File</b> (not Photo) to keep original quality!\n"
        f"Telegram → Attach → <b>File</b> → Gallery\n\n"
        f"🚀 <b>Let's get started!</b> Drop an image below 👇"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>How to use this bot:</b>\n\n"
        "1️⃣ Send your image as <b>File</b> (for original quality)\n"
        "   ⚠️ Sending as Photo compresses it via Telegram\n\n"
        "2️⃣ Choose your desired <b>output format</b>\n\n"
        "3️⃣ Select <b>quality level</b>\n\n"
        "4️⃣ Pick a <b>resize option</b> or skip\n\n"
        "5️⃣ Choose delivery: <b>Separate Files</b> or <b>ZIP</b>\n\n"
        "6️⃣ Download your converted image! ✅\n\n"
        f"📦 <b>Batch Mode:</b> Send up to {MAX_BATCH} images, then choose format once.\n\n"
        "<b>⌨️ Commands:</b>\n"
        "  /start — Launch the bot\n"
        "  /help  — Show this guide\n"
        "  /about — Bot info & credits\n"
        "  /status — Check your current session\n"
        "  /cancel — Cancel ongoing operation\n\n"
        "👨‍💻 <b>Developer:</b> @SDevX2"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>Image Converter Bot</b> — Multi-User Edition\n\n"
        "A powerful image conversion tool built for Telegram.\n\n"
        "🔄 <b>Formats:</b> JPG · PNG · WEBP · BMP · GIF · ICO · TIFF\n"
        "⚙️ <b>Engine:</b> Python · Pillow · python-telegram-bot\n"
        "☁️ <b>Hosted on:</b> Render (free tier optimized)\n"
        "🧵 <b>Threads:</b> 4 workers for concurrent processing\n\n"
        "🔒 <b>Privacy Policy:</b>\n"
        "Your images are stored temporarily and automatically deleted after 5 minutes. No images are kept permanently.\n\n"
        "👨‍💻 <b>Developer:</b> @SDevX2"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.get(uid)
    if not state or not state["files"]:
        await update.message.reply_text(
            "📭 You don't have an active session.\n\nSend an image to get started!",
            reply_markup=main_keyboard(),
        )
        return

    quality_label = _quality_label(state["quality"] or "high")
    text = (
        "📋 <b>Your Current Session:</b>\n\n"
        f"🖼 Images: <b>{len(state['files'])}</b>\n"
        f"🔄 Format: <b>{state['format'] or 'Not selected'}</b>\n"
        f"🎚 Quality: <b>{quality_label}</b>\n"
        f"📐 Resize: <b>{state['resize'] or 'None'}</b>\n"
        f"✅ Original Quality: <b>{'Yes' if state['is_original'] else 'No (sent as Photo)'}</b>\n\n"
        "Use /cancel to abort."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.pop(uid, None)
    if state and state.get("files"):
        cleanup_batch(state["files"])
        gc.collect()
        await update.message.reply_text("❌ Operation cancelled. All temp files have been purged.", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("No active operation to cancel.", reply_markup=main_keyboard())


# ══════════════════════════════════════════════
#  MESSAGE HANDLERS
# ══════════════════════════════════════════════

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_files()
    uid = update.effective_user.id

    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(
            f"⚠️ Maximum {MAX_BATCH} images allowed in one batch.\nConvert them or use /cancel to reset.",
            reply_markup=main_keyboard(),
        )
        return

    photo = update.message.photo[-1]
    file  = await context.bot.get_file(photo.file_id)
    ext   = (file.file_path or "x.jpg").rsplit(".", 1)[-1]
    local_path = os.path.join(TEMP_DIR, f"{uid}_{photo.file_unique_id}.{ext}")
    await file.download_to_drive(local_path)
    track_file(local_path)

    if uid not in user_state:
        user_state[uid] = new_state()
    user_state[uid]["files"].append(local_path)
    user_state[uid]["is_original"] = False
    count = len(user_state[uid]["files"])

    await update.message.reply_text(
        f"🖼 <b>Image #{count} Received</b>\n\n"
        f"⚠️ <b>This is Telegram's compressed version!</b>\n"
        f"For original quality, send as <b>File</b> instead of Photo.\n\n"
        f"Still want to convert this? Choose your format below 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=format_keyboard(),
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_files()
    uid = update.effective_user.id
    doc = update.message.document

    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text(
            "❌ That's not an image file.\nPlease send JPG, PNG, WEBP, or other supported formats.",
            reply_markup=main_keyboard(),
        )
        return

    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(
            f"⚠️ Maximum {MAX_BATCH} images per batch reached.\nConvert or /cancel to start fresh.",
            reply_markup=main_keyboard(),
        )
        return

    file = await context.bot.get_file(doc.file_id)
    ext  = (doc.file_name or "image.jpg").rsplit(".", 1)[-1]
    local_path = os.path.join(TEMP_DIR, f"{uid}_{doc.file_unique_id}.{ext}")
    await file.download_to_drive(local_path)
    track_file(local_path)

    if uid not in user_state:
        user_state[uid] = new_state()
    user_state[uid]["files"].append(local_path)
    user_state[uid]["is_original"] = True
    count = len(user_state[uid]["files"])

    await update.message.reply_text(
        f"✅ <b>Image #{count} Received — Original Quality!</b>\n\n"
        f"You can send up to {MAX_BATCH} images total.\n"
        f"Choose your output format below 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=format_keyboard(),
    )


async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in ("🖼 Convert", "Convert"):
        await update.message.reply_text(
            "📎 Send your image as <b>File</b> for best quality.\n\nTelegram → Attach → <b>File</b> → Gallery",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )
    elif text in ("📦 Batch", "Batch"):
        await update.message.reply_text(
            f"📦 Send up to <b>{MAX_BATCH}</b> images as <b>Files</b>.\n\nOnce all images are sent, choose your format and I'll convert them all!",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )
    elif text in ("📐 Resize", "Resize"):
        await update.message.reply_text("📐 Send an image first, then you can select a resize preset during conversion.", reply_markup=main_keyboard())
    elif text in ("🗜 Compress", "Compress"):
        await update.message.reply_text("🗜 Send an image first, then choose a quality level during conversion.", reply_markup=main_keyboard())
    elif text in ("❓ Help", "Help"):
        await cmd_help(update, context)
    elif text in ("ℹ️ About", "About"):
        await cmd_about(update, context)


# ══════════════════════════════════════════════
#  CALLBACK HANDLERS
# ══════════════════════════════════════════════

async def on_cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    state = user_state.pop(uid, None)
    if state and state.get("files"):
        cleanup_batch(state["files"])
        gc.collect()
    await query.edit_message_text("❌ Cancelled.")
    await context.bot.send_message(chat_id=query.message.chat_id, text="Send a new image to start!", reply_markup=main_keyboard())


async def on_format_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    fmt  = query.data.replace("fmt_", "")

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("⚠️ No images found. Send an image first!")
        return

    user_state[uid]["format"] = fmt
    count = len(user_state[uid]["files"])

    await query.edit_message_text(
        f"✅ <b>Format:</b> {fmt.upper()}\n🖼 <b>Images:</b> {count}\n\n🎚 <b>Select Quality:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=quality_keyboard(),
    )


async def on_quality_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    quality = query.data.replace("q_", "")

    if uid not in user_state:
        await query.edit_message_text("⚠️ Session expired. Send an image again!")
        return

    user_state[uid]["quality"] = quality

    await query.edit_message_text(
        f"✅ <b>Format:</b> {user_state[uid]['format'].upper()}\n"
        f"✅ <b>Quality:</b> {_quality_label(quality)}\n\n"
        f"📐 <b>Select Resize Option:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=resize_keyboard(),
    )


async def on_resize_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    resize = query.data.replace("resize_", "")
    if resize == "none":
        resize = None

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("⚠️ Session expired. Send an image again!")
        return

    user_state[uid]["resize"] = resize
    state = user_state[uid]

    await query.edit_message_text(
        f"✅ <b>Format:</b> {state['format'].upper()}\n"
        f"✅ <b>Quality:</b> {_quality_label(state['quality'])}\n"
        f"✅ <b>Resize:</b> {resize or 'None'}\n"
        f"🖼 <b>Images:</b> {len(state['files'])}\n\n"
        f"📤 <b>How do you want the output?</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=output_keyboard(),
    )


async def on_output_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    uid         = query.from_user.id
    send_as_zip = query.data == "out_zip"

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("⚠️ Session expired. Send an image again!")
        return

    state   = user_state[uid]
    files   = state["files"]
    fmt     = state["format"]
    quality = state["quality"]
    resize  = state["resize"]

    await query.edit_message_text(
        f"⏳ <b>Converting {len(files)} image(s)...</b>\n\n"
        f"Format: {fmt.upper()} | Quality: {_quality_label(quality)} | Resize: {resize or 'None'}\n\n"
        f"Please wait...",
        parse_mode=ParseMode.HTML,
    )

    output_files, errors = [], []

    for fpath in files:
        try:
            out = await convert_image_async(fpath, fmt, quality, resize)
            track_file(out)
            output_files.append(out)
            gc.collect()
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: {e}")

    if output_files:
        if send_as_zip:
            try:
                zip_path = make_zip(output_files, uid)
                track_file(zip_path)
                with open(zip_path, "rb") as zf:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=zf,
                        filename=f"converted_{fmt.lower()}.zip",
                        caption=f"🗜 {len(output_files)} files converted to {fmt.upper()}",
                    )
                cleanup_file(zip_path)
            except Exception as e:
                errors.append(f"ZIP error: {e}")
        else:
            for out in output_files:
                try:
                    with open(out, "rb") as f:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=f,
                            caption=f"✅ {os.path.basename(out)}",
                        )
                except Exception as e:
                    errors.append(f"Send error: {e}")

    summary = (
        f"🎉 <b>Conversion Complete!</b>\n\n"
        f"✅ Converted: {len(output_files)}\n"
        f"❌ Failed: {len(errors)}"
    )
    if errors:
        summary += "\n\n<b>Errors:</b>\n" + "\n".join(errors[:5])

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


# ══════════════════════════════════════════════
#  MAIN — PYTHON 3.14 FIX HERE
# ══════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        print("ERROR: Set BOT_TOKEN environment variable!")
        return

    # ✅ FIX: Explicit event loop for Python 3.14+
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    app.add_error_handler(error_handler)

    # Commands
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("about",  cmd_about))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO,          handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    # Callbacks
    app.add_handler(CallbackQueryHandler(on_cancel_action,   pattern=r"^action_cancel$"))
    app.add_handler(CallbackQueryHandler(on_format_selected, pattern=r"^fmt_"))
    app.add_handler(CallbackQueryHandler(on_quality_selected,  pattern=r"^q_"))
    app.add_handler(CallbackQueryHandler(on_resize_selected, pattern=r"^resize_"))
    app.add_handler(CallbackQueryHandler(on_output_selected, pattern=r"^out_"))

    if WEBHOOK_URL:
        webhook_path = "/webhook"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
        logger.info(f"Webhook mode → {full_webhook_url} port={PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url,
            drop_pending_updates=True,
        )
    else:
        logger.info("Webhook URL not set — falling back to polling")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
