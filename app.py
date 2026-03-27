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

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Polymarket Tracker</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 20px; max-width: 800px; margin: 0 auto; }
h1 { font-size: 20px; font-weight: 500; margin-bottom: 4px; }
.sub { font-size: 13px; color: #888; margin-bottom: 20px; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.metric { background: #1a1a1a; border-radius: 10px; padding: 14px; }
.metric-label { font-size: 11px; color: #888; margin-bottom: 6px; }
.metric-value { font-size: 22px; font-weight: 500; }
.positive { color: #4caf50; }
.negative { color: #f44336; }
.card { background: #1a1a1a; border-radius: 10px; padding: 16px; margin-bottom: 12px; }
.market-q { font-size: 14px; font-weight: 500; margin-bottom: 10px; line-height: 1.4; }
.bar-track { height: 6px; background: #333; border-radius: 3px; overflow: hidden; margin-bottom: 4px; }
.bar-fill { height: 100%; border-radius: 3px; }
.bar-labels { display: flex; justify-content: space-between; font-size: 12px; }
.btn { padding: 6px 16px; border-radius: 8px; border: 1px solid #444; background: transparent; color: #e0e0e0; cursor: pointer; font-size: 12px; }
.btn:hover { background: #2a2a2a; }
.btn-primary { background: #e0e0e0; color: #0f0f0f; border-color: #e0e0e0; font-weight: 500; }
.btn-primary:hover { opacity: 0.85; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.bet-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 0; border-bottom: 1px solid #222; font-size: 13px; }
.bet-row:last-child { border-bottom: none; }
.bet-q { flex: 1; min-width: 120px; }
.badge { font-size: 11px; padding: 3px 10px; border-radius: 6px; font-weight: 500; white-space: nowrap; }
.yes { background: #1a3a1a; color: #4caf50; }
.no { background: #3a1a1a; color: #f44336; }
.b-open { background: #2a2a2a; color: #888; }
.b-won { background: #1a3a1a; color: #4caf50; }
.b-lost { background: #3a1a1a; color: #f44336; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #4caf50; display: inline-block; margin-right: 8px; animation: pulse 2s infinite; }
.section-title { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin: 16px 0 8px; }
.empty { color: #888; font-size: 13px; }
.ai-reason { font-size: 12px; color: #888; margin-top: 8px; padding: 8px; background: #111; border-radius: 6px; border-left: 2px solid #4caf50; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
@media(max-width:500px){ .metrics{grid-template-columns:repeat(2,1fr);} }
</style>
</head>
<body>
<h1>Polymarket Tracker</h1>
<div class="sub">Paper trading · IA Claude · Corriendo 24/7</div>
<div class="metrics">
  <div class="metric"><div class="metric-label">Saldo</div><div class="metric-value" id="balance">$1000</div></div>
  <div class="metric"><div class="metric-label">P&L</div><div class="metric-value" id="pnl">$0</div></div>
  <div class="metric"><div class="metric-label">Abiertas</div><div class="metric-value" id="open-count">0</div></div>
  <div class="metric"><div class="metric-label">Win rate</div><div class="metric-value" id="winrate">—</div></div>
</div>
<div class="card">
  <div class="row">
    <div><span class="dot"></span><span id="bot-status">Bot con IA listo</span></div>
    <div style="display:flex;gap:8px;">
      <button class="btn" onclick="loadMarkets()">Actualizar</button>
      <button class="btn btn-primary" onclick="botBet()">Analizar con IA</button>
    </div>
  </div>
  <div id="ai-reason" class="ai-reason" style="display:none"></div>
</div>
<div class="section-title">Mercados activos</div>
<div id="markets"><div class="empty">Cargando mercados...</div></div>
<div class="section-title">Mis apuestas ficticias</div>
<div class="card" id="bets"><div class="empty">Sin apuestas todavía.</div></div>
<script>
async function loadMetrics(){
  const d = await fetch("/metrics").then(r=>r.json());
  document.getElementById("balance").textContent = "$"+Math.round(d.balance);
  const pnl = d.balance - 1000;
  const el = document.getElementById("pnl");
  el.textContent = (pnl>=0?"+":"-")+"$"+Math.round(Math.abs(pnl));
  el.className = "metric-value "+(pnl>0?"positive":pnl<0?"negative":"");
  document.getElementById("open-count").textContent = d.open;
  document.getElementById("winrate").textContent = d.winrate;
}
async function loadMarkets(){
  document.getElementById("markets").innerHTML = "<div class='empty'>Cargando...</div>";
  const d = await fetch("/markets").then(r=>r.json());
  if(!d.length){ document.getElementById("markets").innerHTML = "<div class='empty'>No se encontraron mercados.</div>"; return; }
  document.getElementById("markets").innerHTML = d.map((m,i)=>{
    const color = m.prob > 50 ? "#4caf50" : "#ff9800";
    return `<div class="card">
      <div class="market-q">${m.question}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${m.prob}%;background:${color}"></div></div>
      <div class="bar-labels" style="margin-bottom:10px;">
        <span style="color:${color}">Si ${m.prob}%</span>
        <span style="color:#888">No ${100-m.prob}%</span>
      </div>
      <div class="row">
        <span style="font-size:12px;color:#888">${m.volume}</span>
        <button class="btn" onclick="manualBet(${i})">+ Apostar</button>
      </div>
    </div>`;
  }).join("");
}
async function manualBet(i){
  await fetch("/bet?idx="+i, {method:"POST"});
  await loadMetrics(); await loadBets();
}
async function botBet(){
  document.getElementById("bot-status").textContent = "Claude analizando mercados...";
  document.getElementById("ai-reason").style.display = "none";
  const d = await fetch("/bot-bet", {method:"POST"}).then(r=>r.json());
  document.getElementById("bot-status").textContent = d.message;
  if(d.reason){
    document.getElementById("ai-reason").style.display = "block";
    document.getElementById("ai-reason").textContent = "Claude: " + d.reason;
  }
  await loadMetrics(); await loadBets();
}
async function loadBets(){
  const d = await fetch("/bets").then(r=>r.json());
  if(!d.length){ document.getElementById("bets").innerHTML = "<div class='empty'>Sin apuestas todavia.</div>"; return; }
  document.getElementById("bets").innerHTML = d.map(b=>`
    <div class="bet-row">
      <div class="bet-q">${b.question}</div>
      <span class="badge ${b.side==='SI'?'yes':'no'}">${b.side}</span>
      <span style="color:#888">$${b.amount}</span>
      <span style="font-weight:500;color:${b.pnl>0?'#4caf50':b.pnl<0?'#f44336':'#888'}">${b.pnl_text}</span>
      <span class="badge b-${b.status}">${b.status_text}</span>
    </div>`).join("");
}
loadMarkets(); loadMetrics(); loadBets();
setInterval(()=>{ loadMetrics(); loadBets(); }, 8000);
</script>
</body>
</html>
"""

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
        # timeout corto y manejo de excepción más explícito
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
                print("Price parse error:", e)
            vol = float(m.get("volume", 0))
            vol_str = f"${vol/1000000:.1f}M vol" if vol>1000000 else f"${vol/1000:.0f}K vol" if vol>1000 else "—"
            result.append({"question": m.get("question","")[:80], "prob": prob, "volume": vol_str})
        # si no hay mercados, devolvemos un placeholder
        return jsonify(result if result else [{"question":"No se pudieron cargar mercados","prob":0,"volume":"—"}])
    except Exception as e:
        print("GET /markets error:", e)
        return jsonify([{"question":"Error al conectar Polymarket","prob":0,"volume":"—"}])

@app.route("/bet", methods=["POST"])
def manual_bet():
    idx = int(req.args.get("idx", 0))
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=10", timeout=5)
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
    except: return jsonify({"ok": False})

def get_news(query):
    try:
        news_key = os.environ.get("NEWS_API_KEY")
        url = f"https://newsapi.org/v2/everything?q={query}&pageSize=3&sortBy=publishedAt&apiKey={news_key}"
        r = requests.get(url, timeout=5)
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
        ai_prob = confidence
        edge = abs(ai_prob - market_prob)

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
