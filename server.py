# keep_alive.py
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "OK"  # RenderのHealth Check用

def run():
    # Render では 0.0.0.0 で待ち受け必須
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
