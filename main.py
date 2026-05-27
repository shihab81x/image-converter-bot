#!/usr/bin/env python3
"""
Image Converter Bot for Telegram
Converts images between formats: JPG, PNG, WEBP, BMP, GIF, ICO, TIFF
Optimized for Render free tier (512MB RAM)
Developer: @SDevX2
"""

import os
import gc
import time
import logging
import asyncio
import zipfile
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
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT        = int(os.environ.get("PORT", 10000))

TEMP_DIR           = os.path.join(os.path.dirname(__file__), "temp")
FILE_EXPIRY_SECONDS = 300   # 5 minutes
MAX_BATCH          = 5

os.makedirs(TEMP_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# user_id → { files, format, quality, resize, is_original }
user_state: dict = {}
# file_path → timestamp
file_timestamps: dict = {}


# ══════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🖼 Convert Image"),  KeyboardButton("📦 Batch Convert")],
            [KeyboardButton("📐 Resize Image"),   KeyboardButton("🗜 Compress Image")],
            [KeyboardButton("❓ Help"),            KeyboardButton("ℹ️ About")],
        ],
        resize_keyboard=True,
    )


def format_keyboard() -> InlineKeyboardMarkup:
    buttons, row = [], []
    for fmt in SUPPORTED_FORMATS:
        row.append(InlineKeyboardButton(fmt, callback_data=f"fmt_{fmt}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")])
    return InlineKeyboardMarkup(buttons)


def quality_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 Low (40)",    callback_data="q_low"),
            InlineKeyboardButton("🟡 Medium (65)", callback_data="q_medium"),
        ],
        [
            InlineKeyboardButton("🟠 High (85)",   callback_data="q_high"),
            InlineKeyboardButton("🔴 Max (95)",    callback_data="q_maximum"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")],
    ])


def resize_keyboard() -> InlineKeyboardMarkup:
    buttons, row = [], []
    for name in RESIZE_PRESETS:
        row.append(InlineKeyboardButton(name, callback_data=f"resize_{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⏭ No Resize", callback_data="resize_none")])
    buttons.append([InlineKeyboardButton("❌ Cancel",    callback_data="action_cancel")])
    return InlineKeyboardMarkup(buttons)


def output_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 আলাদা ফাইল", callback_data="out_individual"),
            InlineKeyboardButton("🗜 ZIP",          callback_data="out_zip"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")],
    ])


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
        logger.info(f"Auto-cleaned {len(expired)} expired temp files")


def make_zip(output_files: list, uid: int) -> str:
    zip_path = os.path.join(TEMP_DIR, f"{uid}_converted.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in output_files:
            zf.write(f, arcname=os.path.basename(f))
    return zip_path


def new_state() -> dict:
    return {"files": [], "format": None, "quality": "high", "resize": None, "is_original": False}


def _quality_label(quality: str) -> str:
    labels = {"low": "🔵 Low (40)", "medium": "🟡 Medium (65)",
               "high": "🟠 High (85)", "maximum": "🔴 Max (95)"}
    return labels.get(quality, quality)


# ══════════════════════════════════════════════
#  ERROR HANDLER
# ══════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception:", exc_info=context.error)
    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.reply_text(
                "⚠️ কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করো।",
                reply_markup=main_keyboard(),
            )
        except Exception:
            pass


# ══════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "বন্ধু"
    await update.message.reply_text(
        f"👋 হ্যালো <b>{name}</b>! স্বাগতম <b>Image Converter Bot</b> এ!\n\n"
        "🔄 <b>Supported Formats:</b> JPG · PNG · WEBP · BMP · GIF · ICO · TIFF\n\n"
        "✨ <b>Features:</b>\n"
        "  • যেকোনো format এ convert করো\n"
        "  • Resize করো (4টা preset)\n"
        "  • Quality compress করো\n"
        f"  • Batch convert (একসাথে {MAX_BATCH}টা)\n"
        "  • আলাদা ফাইল বা ZIP হিসেবে নামাও\n\n"
        f"📦 <b>Max file size:</b> {MAX_FILE_SIZE_MB}MB\n"
        "🕐 <b>Auto delete:</b> 5 মিনিট পরে\n\n"
        "📎 <b>Original quality পেতে:</b>\n"
        "Telegram এ attach করার সময় <b>Photo না দিয়ে File বেছে নাও</b> — তাহলে Telegram compress করবে না।\n\n"
        "নিচের বাটন থেকে শুরু করো অথবা সরাসরি image পাঠাও! 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>কিভাবে ব্যবহার করবে:</b>\n\n"
        "1️⃣ Image টা <b>File হিসেবে পাঠাও</b>\n"
        "   (Photo হিসেবে পাঠালে Telegram নিজেই compress করে)\n\n"
        "2️⃣ Output <b>format</b> বেছে নাও\n\n"
        "3️⃣ <b>Quality</b> বেছে নাও\n\n"
        "4️⃣ <b>Resize</b> করবে কিনা বেছে নাও\n\n"
        "5️⃣ <b>আলাদা ফাইল</b> বা <b>ZIP</b> — যেটা চাও বেছে নাও\n\n"
        "6️⃣ Converted image <b>download</b> করো ✅\n\n"
        f"📦 <b>Batch:</b> একসাথে {MAX_BATCH}টা পর্যন্ত image পাঠাতে পারবে, তারপর format বেছে নাও।\n\n"
        "<b>⌨️ Commands:</b>\n"
        "/start — Bot শুরু করো\n"
        "/help — এই message\n"
        "/about — Bot এর তথ্য\n"
        "/status — তোমার current session\n"
        "/cancel — চলমান কাজ বাতিল করো\n\n"
        "Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
    )


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Image Converter Bot</b>\n\n"
        "Telegram এর জন্য একটি image format converter।\n\n"
        "🔄 <b>Formats:</b> JPG · PNG · WEBP · BMP · GIF · ICO · TIFF\n"
        "⚙️ <b>Engine:</b> Python · Pillow · python-telegram-bot\n"
        "☁️ <b>Hosted on:</b> Render (free tier)\n\n"
        "🔒 <b>Privacy:</b>\n"
        "তোমার image গুলো server এ temporarily রাখা হয় এবং 5 মিনিটের মধ্যে automatically delete হয়ে যায়। কোনো image permanently store করা হয় না।\n\n"
        "👨‍💻 Developer: @SDevX2",
        parse_mode=ParseMode.HTML,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.get(uid)
    if not state or not state["files"]:
        await update.message.reply_text(
            "📭 তোমার কোনো active session নেই।\n\nImage পাঠাও শুরু করতে।",
            reply_markup=main_keyboard(),
        )
        return

    quality_label = _quality_label(state["quality"] or "high")
    await update.message.reply_text(
        "📋 <b>তোমার current session:</b>\n\n"
        f"🖼 Images: {len(state['files'])}টা\n"
        f"🔄 Format: {state['format'] or 'এখনো বেছে নাওনি'}\n"
        f"🎚 Quality: {quality_label}\n"
        f"📐 Resize: {state['resize'] or 'None'}\n"
        f"✅ Original quality: {'হ্যাঁ' if state['is_original'] else 'না (Photo হিসেবে পাঠানো)'}\n\n"
        "/cancel দিয়ে বাতিল করতে পারো।",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.pop(uid, None)
    if state and state.get("files"):
        cleanup_batch(state["files"])
        gc.collect()
        await update.message.reply_text(
            "❌ Operation বাতিল করা হয়েছে। সব temp file মুছে ফেলা হয়েছে।",
            reply_markup=main_keyboard(),
        )
    else:
        await update.message.reply_text(
            "কোনো active operation নেই।",
            reply_markup=main_keyboard(),
        )


# ══════════════════════════════════════════════
#  MESSAGE HANDLERS
# ══════════════════════════════════════════════

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Photo হিসেবে পাঠানো — Telegram compress করে ফেলে।"""
    cleanup_expired_files()
    uid = update.effective_user.id

    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(
            f"⚠️ Maximum {MAX_BATCH}টা image একসাথে নেওয়া যায়।\n"
            "Convert করো অথবা /cancel দাও।"
        )
        return

    photo = update.message.photo[-1]
    file  = await context.bot.get_file(photo.file_id)
    ext   = (file.file_path or "x.jpg").rsplit(".", 1)[-1]
    local_path = os.path.join(TEMP_DIR, f"{uid}_{photo.file_unique_id}.{ext}")
    await file.download_to_drive(local_path)
    track_file(local_path)

    info = get_image_info(local_path)
    if "error" in info:
        await update.message.reply_text(f"❌ Error: {info['error']}")
        cleanup_file(local_path)
        return

    if uid not in user_state:
        user_state[uid] = new_state()
    user_state[uid]["files"].append(local_path)
    user_state[uid]["is_original"] = False
    count = len(user_state[uid]["files"])

    await update.message.reply_text(
        f"🖼 <b>Image #{count} received</b>\n\n"
        f"Format: <code>{info['format']}</code>\n"
        f"Resolution: <code>{info['width']}×{info['height']}</code>\n"
        f"Size: <code>{info['size_mb']} MB</code>\n\n"
        "⚠️ <b>এটা Telegram এর compressed version!</b>\n"
        "Original quality পেতে <b>File হিসেবে পাঠাও</b>:\n"
        "Telegram → Attach → <b>File</b> → Gallery থেকে select করো।\n\n"
        "তবুও এটা দিয়ে convert করতে চাইলে format বেছে নাও 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=format_keyboard(),
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """File হিসেবে পাঠানো — Original quality।"""
    cleanup_expired_files()
    uid = update.effective_user.id
    doc = update.message.document

    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text(
            "❌ এটা image file না।\nJPG, PNG, WEBP ইত্যাদি image পাঠাও।"
        )
        return

    if uid in user_state and len(user_state[uid]["files"]) >= MAX_BATCH:
        await update.message.reply_text(
            f"⚠️ Maximum {MAX_BATCH}টা image একসাথে নেওয়া যায়।\n"
            "Convert করো অথবা /cancel দাও।"
        )
        return

    file = await context.bot.get_file(doc.file_id)
    ext  = (doc.file_name or "image.jpg").rsplit(".", 1)[-1]
    local_path = os.path.join(TEMP_DIR, f"{uid}_{doc.file_unique_id}.{ext}")
    await file.download_to_drive(local_path)
    track_file(local_path)

    info = get_image_info(local_path)
    if "error" in info:
        await update.message.reply_text(f"❌ Error: {info['error']}")
        cleanup_file(local_path)
        return

    if uid not in user_state:
        user_state[uid] = new_state()
    user_state[uid]["files"].append(local_path)
    user_state[uid]["is_original"] = True
    count = len(user_state[uid]["files"])

    await update.message.reply_text(
        f"✅ <b>Image #{count} received — Original quality!</b>\n\n"
        f"Format: <code>{info['format']}</code>\n"
        f"Resolution: <code>{info['width']}×{info['height']}</code>\n"
        f"Size: <code>{info['size_mb']} MB</code>\n\n"
        f"আরো image পাঠাতে পারো (max {MAX_BATCH}টা) অথবা নিচে format বেছে নাও 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=format_keyboard(),
    )


async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in ("🖼 Convert Image", "Convert Image"):
        await update.message.reply_text(
            "📎 Image টা <b>File হিসেবে পাঠাও</b> original quality এর জন্য।\n\n"
            "Telegram → Attach → <b>File</b> → Gallery থেকে select করো।",
            parse_mode=ParseMode.HTML,
        )
    elif text in ("📦 Batch Convert", "Batch Convert"):
        await update.message.reply_text(
            f"📦 একসাথে সর্বোচ্চ <b>{MAX_BATCH}টা</b> image পাঠাতে পারবে।\n\n"
            "⚠️ <b>File হিসেবে পাঠাও</b> original quality এর জন্য।\n"
            "সব image পাঠানো হলে format বেছে নাও।",
            parse_mode=ParseMode.HTML,
        )
    elif text in ("📐 Resize Image", "Resize Image"):
        await update.message.reply_text(
            "📐 আগে image পাঠাও, তারপর resize preset বেছে নিতে পারবে।"
        )
    elif text in ("🗜 Compress Image", "Compress Image"):
        await update.message.reply_text(
            "🗜 আগে image পাঠাও, তারপর quality level বেছে নিতে পারবে।"
        )
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
    await query.edit_message_text("❌ বাতিল করা হয়েছে।")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="নতুন image পাঠাও।",
        reply_markup=main_keyboard(),
    )


async def on_format_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    fmt  = query.data.replace("fmt_", "")

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("⚠️ কোনো image নেই। আগে image পাঠাও।")
        return

    user_state[uid]["format"] = fmt
    count = len(user_state[uid]["files"])

    await query.edit_message_text(
        f"✅ Format: <b>{fmt}</b>\n"
        f"Images: {count}টা\n\n"
        "🎚 <b>Quality বেছে নাও:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=quality_keyboard(),
    )


async def on_quality_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    quality = query.data.replace("q_", "")

    if uid not in user_state:
        await query.edit_message_text("⚠️ Session শেষ হয়ে গেছে। আবার image পাঠাও।")
        return

    user_state[uid]["quality"] = quality

    await query.edit_message_text(
        f"✅ Format: <b>{user_state[uid]['format']}</b>\n"
        f"✅ Quality: <b>{_quality_label(quality)}</b>\n\n"
        "📐 <b>Resize option বেছে নাও:</b>",
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
        await query.edit_message_text("⚠️ Session শেষ হয়ে গেছে। আবার image পাঠাও।")
        return

    user_state[uid]["resize"] = resize
    state = user_state[uid]

    await query.edit_message_text(
        f"✅ Format: <b>{state['format']}</b>\n"
        f"✅ Quality: <b>{_quality_label(state['quality'])}</b>\n"
        f"✅ Resize: <b>{resize or 'None'}</b>\n"
        f"🖼 Images: <b>{len(state['files'])}টা</b>\n\n"
        "📤 <b>Output কিভাবে চাও?</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=output_keyboard(),
    )


async def on_output_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    uid         = query.from_user.id
    send_as_zip = query.data == "out_zip"

    if uid not in user_state or not user_state[uid].get("files"):
        await query.edit_message_text("⚠️ Session শেষ হয়ে গেছে। আবার image পাঠাও।")
        return

    state   = user_state[uid]
    files   = state["files"]
    fmt     = state["format"]
    quality = state["quality"]
    resize  = state["resize"]

    await query.edit_message_text(
        f"⏳ <b>Converting {len(files)}টা image...</b>\n\n"
        f"Format: {fmt} | Quality: {_quality_label(quality)} | Resize: {resize or 'None'}\n\n"
        "একটু অপেক্ষা করো...",
        parse_mode=ParseMode.HTML,
    )

    output_files, errors = [], []

    for fpath in files:
        try:
            out = convert_image(fpath, fmt, quality, resize)
            track_file(out)
            output_files.append(out)
            gc.collect()
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: {e}")

    # ── Send output ──
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
                        caption=f"🗜 {len(output_files)}টা file — {fmt} format এ convert করা হয়েছে।",
                    )
                cleanup_file(zip_path)
            except Exception as e:
                errors.append(f"ZIP তৈরি করতে সমস্যা: {e}")
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
                    errors.append(f"পাঠাতে সমস্যা: {e}")

    # ── Summary ──
    summary = (
        f"🎉 <b>Conversion সম্পন্ন!</b>\n\n"
        f"✅ Converted: {len(output_files)}টা\n"
        f"❌ Failed: {len(errors)}টা"
    )
    if errors:
        summary += "\n\n<b>Errors:</b>\n" + "\n".join(errors[:5])

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=summary,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )

    # ── Cleanup ──
    for f in files + output_files:
        file_timestamps.pop(f, None)
    cleanup_batch(files)
    cleanup_batch(output_files)
    user_state.pop(uid, None)
    gc.collect()


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN set করো — Render → Environment Variables")
        return

    # Python 3.14 compatibility — explicit event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(BOT_TOKEN).build()
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
    app.add_handler(CallbackQueryHandler(on_quality_selected,pattern=r"^q_"))
    app.add_handler(CallbackQueryHandler(on_resize_selected, pattern=r"^resize_"))
    app.add_handler(CallbackQueryHandler(on_output_selected, pattern=r"^out_"))

    if WEBHOOK_URL:
        webhook_path     = "/webhook"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
        logger.info(f"Webhook mode → {full_webhook_url}  port={PORT}")
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
