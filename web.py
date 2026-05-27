"""
Render health server
Keeps the service alive and provides health routes.
"""

import os
import time
from flask import Flask, jsonify

app = Flask(__name__)

START_TIME = time.time()


@app.route("/")
def home():
    uptime = int(time.time() - START_TIME)

    return jsonify({
        "status": "online",
        "service": "Image Converter Bot",
        "uptime_seconds": uptime,
        "message": "Bot is running successfully"
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    }), 200


@app.route("/ping")
def ping():
    return "pong", 200


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Not Found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal Server Error"
    }), 500


def run_web():
    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    run_web()
