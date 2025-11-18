# keep_alive.py
import os
from threading import Thread
import flask

app = flask.Flask(__name__)

@app.route("/")
def home():
    return "OK"   # ヘルスチェック用の簡単なレスポンス

def run():
    port = int(os.environ.get("PORT", 10000))  # Render が PORT を渡してくる
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
