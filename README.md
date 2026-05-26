# Image Converter Bot

Telegram bot for image format conversion. Supports JPG, PNG, WEBP, BMP, GIF, ICO, TIFF.

## Features

- Format conversion (JPG, PNG, WEBP, BMP, GIF, ICO, TIFF)
- Resize presets (512x512, 1024x1024, 1280x720, 1920x1080)
- Quality compression (Low/Medium/High/Max)
- Batch convert (up to 5 images)
- Auto-downscale large images (RAM optimized)
- Auto file cleanup (5 min)

## Deploy to Render

1. Fork this repo
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** Free
5. Add Environment Variables:
   - `BOT_TOKEN` = your Telegram bot token
   - `WEBHOOK_URL` = your Render app URL (e.g. `https://your-app.onrender.com`)
6. Deploy

## Local Development

```bash
pip install -r requirements.txt
export BOT_TOKEN="your_bot_token"
python main.py
```

Runs in polling mode when `WEBHOOK_URL` is not set.

## Tech Stack

- Python 3.11
- python-telegram-bot 21.6
- Pillow 11.1.0
- Flask 3.1.1

## License

MIT

Developer: @SDevX2
