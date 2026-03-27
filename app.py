from flask import Flask, jsonify, render_template_string, request
import requests
import json
import random
import os
import threading
from datetime import datetime
import anthropic

app = Flask(__name__)

# --- Estado global ---
state = {
    "balance": 1000.0,
    "initial_balance": 1000.0,
    "bets": [],
    "won": 0,
    "lost": 0
}

GAMMA_API = "https://gamma-api.polymarket.com"
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# --- HTML de la web ---
HTML = """ (aquí va todo tu HTML original) """

@app.route("/")
def index():
    return render_template_string(HTML)

# --- Métricas ---
@app.route("/metrics")
def metrics():
    open_bets = [b for b in state["bets"] if b["status"] == "open"]
    total = state["won"] + state["lost"]
    winrate = f"{round((state['won']/total)*100)}%" if total > 0 else "—"
    return jsonify({"balance": state["balance"], "open": len(open_bets), "winrate": winrate})

# --- Mercados ---
@app.route("/markets")
def get_markets():
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=10", timeout=5)
        r.raise_for_status()
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
            except:
                prob = 50
            vol = float(m.get("volume", 0))
            vol_str = f"${vol/1000000:.1f}M vol" if vol>1_000_000 else f"${vol/1000:.0f}K vol" if vol>1000 else "—"
            result.append({"question": m.get("question","")[:80], "prob": prob, "volume": vol_str})
        return jsonify(result)
    except Exception as e:
        print("Error en /markets:", e)
        return jsonify([])

# --- Apuestas manuales ---
@app.route("/bet", methods=["POST"])
def manual_bet():
    try:
        idx = int(request.args.get("idx", 0))
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=10", timeout=5)
        r.raise_for_status()
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
        except:
            prob = 0.5

        side = "SI" if prob >= 0.5 else "NO"
        place_bet(m.get("question","")[:80], side, 25, prob)
        return jsonify({"ok": True})
    except Exception as e:
        print("Error en /bet:", e)
        return jsonify({"ok": False})

# --- Funciones auxiliares ---
def get_news(query):
    try:
        news_key = os.environ.get("NEWS_API_KEY")
        url = f"https://newsapi.org/v2/everything?q={query}&pageSize=3&sortBy=publishedAt&apiKey={news_key}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        articles = r.json().get("articles", [])
        return " | ".join([a["title"] for a in articles[:3]]) if articles else "Sin noticias recientes."
    except:
        return "Sin noticias disponibles."

def save_prediction(market, prediction):
    record = {
        "timestamp": datetime.now().isoformat(),
        "question": market["question"],
        "market_price": market["prob"],
        "our_side": prediction["side"],
        "our_confidence": prediction["confidence"],
        "reason": prediction["reason"],
        "resolved": None,
        "correct": None
    }
    records = []
    if os.path.exists("predictions.json"):
        with open("predictions.json", "r") as f:
            records = json.load(f)
    records.append(record)
    with open("predictions.json", "w") as f:
        json.dump(records, f, indent=2)

def analyze_with_claude(markets_data):
    markets_text = ""
    for i, m in enumerate(markets_data):
        keywords = m['question'][:50].replace("?","")
        news = get_news(keywords)
        markets_text += f"\nMercado {i}: {m['question']}\nPrecio: {m['prob']}% SI | Volumen: {m['volume']}\nNoticias: {news}\n"

    prompt = f"""Sos un trader experto en mercados de prediccion. Analiza estos mercados con sus noticias recientes:

{markets_text}

Responde SOLO en este formato JSON:
{{
  "market_index": 0,
  "side": "SI",
  "confidence": 0.65,
  "reason": "Explicacion breve basada en las noticias"
}}

Solo apuesta si hay ventaja real vs el precio del mercado. Si no hay ventaja clara, pon confidence igual al precio del mercado."""

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == -1:
        raise ValueError("No JSON found en respuesta de Claude")
    return json.loads(raw[start:end])

def place_bet(question, side, amount, prob):
    if state["balance"] < amount: return
    state["balance"] -= amount
    bet = {"id": str(datetime.now().timestamp()), "question": question, "side": side, "amount": amount, "prob": prob, "status": "open", "pnl": 0}
    state["bets"].insert(0, bet)
    t = threading.Timer(random.uniform(5, 20), resolve_bet, args=[bet["id"]])
    t.daemon = True
    t.start()

def resolve_bet(bet_id):
    bet = next((b for b in state["bets"] if b["id"]==bet_id), None)
    if not bet or bet["status"]!="open": return
    won = random.random() < 0.52
    bet["status"] = "won" if won else "lost"
    if won:
        winnings = bet["amount"] * (1/bet["prob"]-1) * 0.95
        bet["pnl"] = round(winnings, 2)
        state["balance"] += bet["amount"] + winnings
        state["won"] += 1
    else:
        bet["pnl"] = -bet["amount"]
        state["lost"] += 1

# --- Endpoint Bot IA en segundo plano ---
@app.route("/bot-bet", methods=["POST"])
def bot_bet():
    threading.Thread(target=bot_bet_worker, daemon=True).start()
    return jsonify({"message": "Procesando apuesta en segundo plano..."})

def bot_bet_worker():
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=10", timeout=5)
        r.raise_for_status()
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:6]

        markets_data = []
        market_probs = []
        for m in markets:
            try:
                prices = m.get("outcomePrices", "")
                if isinstance(prices, str): prices = json.loads(prices)
                prob = float(prices[0]) if prices else 0.5
            except:
                prob = 0.5
            vol = float(m.get("volume", 0))
            vol_str = f"${vol/1000000:.1f}M" if vol>1_000_000 else f"${vol/1000:.0f}K"
            markets_data.append({"question": m.get("question","")[:80], "prob": round(prob*100), "volume": vol_str})
            market_probs.append(prob)

        if not markets_data: return

        analysis = analyze_with_claude(markets_data)
        save_prediction(markets_data[analysis["market_index"]], analysis)

        idx = analysis["market_index"]
        side = analysis["side"]
        confidence = analysis["confidence"]
        reason = analysis["reason"]
        market_prob = market_probs[idx]
        edge = abs(confidence - market_prob)
        if edge >= 0.04:
            amount = min(50, round(state["balance"] * 0.05))
            place_bet(markets_data[idx]["question"], side, amount, market_prob)

    except Exception as e:
        print("Error en worker bot:", e)

# --- Endpoint para ver apuestas ---
@app.route("/bets")
def get_bets():
    result = []
    for b in state["bets"][:10]:
        pnl_text = "—" if b["status"]=="open" else (("+" if b["pnl"]>0 else "")+str(round(b["pnl"]))+" USDC")
        status_map = {"open":"abierta","won":"ganada","lost":"perdida"}
        result.append({**b, "pnl_text": pnl_text, "status_text": status_map.get(b["status"],"")})
    return jsonify(result)

# --- Main ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
