from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

@app.route("/markets")
def get_markets():
    return jsonify([
        {
            "question": "Test funcionando",
            "prob": 50,
            "volume": "N/A",
            "tag": "Polymarket"
        }
    ])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
