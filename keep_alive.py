# keep_alive.py
from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

# Render が確認するルート
@app.route("/")
def home():
    return "Alive"

# Render の Health Check が叩く場所（必須）
@app.route("/healthz")
def healthz():
    return "OK", 200


def run():
    # Render が環境変数 PORT を渡す ⇒ これを使わないと不安定になる
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    thread = Thread(target=run)
    thread.daemon = True
    thread.start()
