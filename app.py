from flask import Flask, jsonify, render_template_string, request as req
import requests
import json
import random
import os
import threading
from datetime import datetime
import anthropic
import logging

# --- LOGS PARA DEBUG ---
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

state = {
    "balance": 1000.0,
    "initial_balance": 1000.0,
    "bets": [],
    "won": 0,
    "lost": 0
}

GAMMA_API = "https://gamma-api.polymarket.com"
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# --- HTML IGUAL QUE TENÍAS ---
HTML = """ ... tu HTML completo ... """

@app.route("/")
def index():
    logging.info("GET / called")
    return render_template_string(HTML)

@app.route("/metrics")
def metrics():
    logging.info("GET /metrics called")
    try:
        open_bets = [b for b in state["bets"] if b["status"] == "open"]
        total = state["won"] + state["lost"]
        winrate = str(round((state["won"]/total)*100))+"%" if total > 0 else "—"
        logging.info("GET /metrics finished")
        return jsonify({"balance": state["balance"], "open": len(open_bets), "winrate": winrate})
    except Exception as e:
        logging.error("Error in /metrics: %s", e)
        return jsonify({"balance": state["balance"], "open":0, "winrate":"—"})

# --- /markets PROTEGIDO ---
@app.route("/markets")
def get_markets():
    logging.info("GET /markets called")
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=10", timeout=2)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:6]
        result = []
        for m in markets:
            prob = 50
            try:
                prices = m.get("outcomePrices", "")
                if isinstance(prices, str): prices = json.loads(prices)
                if prices: prob = round(float(prices[0]) * 100)
            except Exception as e:
                logging.warning("Price parse error: %s", e)
            vol = float(m.get("volume", 0))
            vol_str = f"${vol/1000000:.1f}M vol" if vol>1000000 else f"${vol/1000:.0f}K vol" if vol>1000 else "—"
            result.append({"question": m.get("question","")[:80], "prob": prob, "volume": vol_str})
        logging.info("GET /markets finished")
        return jsonify(result if result else [{"question":"No se pudieron cargar mercados","prob":0,"volume":"—"}])
    except Exception as e:
        logging.error("GET /markets error: %s", e)
        return jsonify([{"question":"Error al conectar Polymarket","prob":0,"volume":"—"}])

# --- resto de rutas IGUAL que tenías ---
@app.route("/bet", methods=["POST"])
def manual_bet():
    logging.info("POST /bet called")
    idx = int(req.args.get("idx", 0))
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=10", timeout=2)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:6]
        if idx >= len(markets): return jsonify({"ok": False})
        m = markets[idx]
        prob = 0.5
        try:
            prices = m.get("outcomePrices", "")
            if isinstance(prices, str): prices = json.loads(prices)
            if prices: prob = float(prices[0])
        except: pass
        place_bet(m.get("question","")[:80], "SI" if prob>=0.5 else "NO", 25, prob)
        logging.info("POST /bet finished")
        return jsonify({"ok": True})
    except Exception as e:
        logging.error("POST /bet error: %s", e)
        return jsonify({"ok": False})

def get_news(query):
    try:
        news_key = os.environ.get("NEWS_API_KEY")
        url = f"https://newsapi.org/v2/everything?q={query}&pageSize=3&sortBy=publishedAt&apiKey={news_key}"
        r = requests.get(url, timeout=2)
        articles = r.json().get("articles", [])
        if not articles:
            return "Sin noticias recientes."
        return " | ".join([a["title"] for a in articles[:3]])
    except Exception as e:
        logging.warning("get_news error: %s", e)
        return "Sin noticias disponibles."

# --- IA y apuestas, igual que tu código ---
def save_prediction(market, prediction):
    # tu función intacta
    ...

def analyze_with_claude(markets_data):
    # tu función intacta
    ...

@app.route("/bot-bet", methods=["POST"])
def bot_bet():
    logging.info("POST /bot-bet called")
    try:
        # mismo código que tenías, con timeout=2 en requests
        ...
    except Exception as e:
        logging.error("POST /bot-bet error: %s", e)
        return jsonify({"message": f"Error: {str(e)}", "reason": None})

@app.route("/bets")
def get_bets():
    logging.info("GET /bets called")
    return jsonify([...])  # tu código intacto

def place_bet(question, side, amount, prob):
    # tu código intacto
    ...

def resolve_bet(bet_id):
    # tu código intacto
    ...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
