from flask import Flask, jsonify, render_template_string, request as req
import requests
import json
import random
import os
import threading
from datetime import datetime
import anthropic

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

HTML = """[AQUÍ VA TU HTML COMPLETO, igual que tenías]"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/metrics")
def metrics():
    open_bets = [b for b in state["bets"] if b["status"] == "open"]
    total = state["won"] + state["lost"]
    winrate = str(round((state["won"]/total)*100))+"%" if total > 0 else "—"
    return jsonify({"balance": state["balance"], "open": len(open_bets), "winrate": winrate})

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
            except: pass
            vol = float(m.get("volume", 0))
            vol_str = f"${vol/1000000:.1f}M vol" if vol>1000000 else f"${vol/1000:.0f}K vol" if vol>1000 else "—"
            result.append({"question": m.get("question","")[:80], "prob": prob, "volume": vol_str})
        return jsonify(result)
    except Exception as e:
        return jsonify([])

@app.route("/bet", methods=["POST"])
def manual_bet():
    idx = int(req.args.get("idx", 0))
    try:
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
        except: pass
        place_bet(m.get("question","")[:80], "SI" if prob>=0.5 else "NO", 25, prob)
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

def get_news(query):
    try:
        news_key = os.environ.get("NEWS_API_KEY")
        url = f"https://newsapi.org/v2/everything?q={query}&pageSize=3&sortBy=publishedAt&apiKey={news_key}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        articles = r.json().get("articles", [])
        if not articles:
            return "Sin noticias recientes."
        return " | ".join([a["title"] for a in articles[:3]])
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

Solo aposta si las noticias muestran ventaja real vs el precio del mercado. Si no hay ventaja clara, pon confidence igual al precio del mercado."""

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1: raise ValueError("No JSON found")
    return json.loads(raw[start:end])

@app.route("/bot-bet", methods=["POST"])
def bot_bet():
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
            vol_str = f"${vol/1000000:.1f}M" if vol>1000000 else f"${vol/1000:.0f}K"
            markets_data.append({
                "question": m.get("question","")[:80],
                "prob": round(prob * 100),
                "volume": vol_str
            })
            market_probs.append(prob)

        if not markets_data:
            return jsonify({"message": "Sin mercados disponibles", "reason": None})

        analysis = analyze_with_claude(markets_data)
        save_prediction(markets_data[analysis["market_index"]], analysis)

        idx = analysis.get("market_index", 0)
        side = analysis.get("side", "SI")
        confidence = analysis.get("confidence", 0.5)
        reason = analysis.get("reason", "")

        if idx >= len(markets_data):
            return jsonify({"message": "Sin oportunidad clara", "reason": reason})

        market_prob = market_probs[idx]
        edge = abs(confidence - market_prob)

        if edge < 0.04:
            return jsonify({
                "message": "Sin ventaja suficiente - esperando mejor oportunidad",
                "reason": reason
            })

        amount = min(50, round(state["balance"] * 0.05))
        place_bet(markets_data[idx]["question"], side, amount, market_prob)

        return jsonify({
            "message": f"Apuesta: {side} ${amount} USDC ficticio",
            "reason": reason
        })

    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}", "reason": None})

@app.route("/bets")
def get_bets():
    result = []
    for b in state["bets"][:10]:
        pnl_text = "—" if b["status"]=="open" else (("+" if b["pnl"]>0 else "")+str(round(b["pnl"]))+" USDC")
        status_map = {"open":"abierta","won":"ganada","lost":"perdida"}
        result.append({**b, "pnl_text": pnl_text, "status_text": status_map.get(b["status"],"")})
    return jsonify(result)

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
