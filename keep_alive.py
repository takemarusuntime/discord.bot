# keep_alive.py
from flask import Flask
from threading import Thread

app = Flask('')

# Render が叩く可能性のある全てのパスで 200 を返す
@app.route('/')
def home():
    return "OK"

@app.route('/healthz')
def health():
    return "OK"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()
