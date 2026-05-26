"""
Flask health check endpoint for Render.
Render pings this to keep the service alive and check health.
The actual Telegram webhook runs inside the bot application on the same port.
"""

import os
import threading
import time
from flask import Flask, jsonify

app = Flask(__name__)
start_time = time.time()


@app.route("/")
def health():
    """Health check endpoint for Render."""
    uptime = int(time.time() - start_time)
    return jsonify({
        "status": "ok",
        "bot": "Image Converter Bot",
        "uptime_seconds": uptime,
    })


@app.route("/health")
def health_check():
    return jsonify({"status": "healthy"}), 200


def run_web():
    """Run Flask web server (called from main.py if needed separately)."""
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
