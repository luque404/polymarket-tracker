from flask import Flask, jsonify, render_template_string, request
import requests
import json
import random
import os
import threading
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id TEXT PRIMARY KEY,
                question TEXT,
                side TEXT,
                amount REAL,
                prob REAL,
                status TEXT,
                pnl REAL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("INSERT INTO state (key, value) VALUES ('balance', '10000.0') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO state (key, value) VALUES ('won', '0') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO state (key, value) VALUES ('lost', '0') ON CONFLICT DO NOTHING")
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

init_db()

HTML = """<!DOCTYPE html>
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
.bar-labels { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 10px; }
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
.reasoning { font-size: 12px; color: #888; margin-top: 6px; font-style: italic; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
@media(max-width:500px){ .metrics{grid-template-columns:repeat(2,1fr);} }
</style>
</head>
<body>
<h1>Polymarket Tracker</h1>
<div class="sub">Paper trading · Saldo ficticio · Claude AI</div>
<div class="metrics">
  <div class="metric"><div class="metric-label">Saldo</div><div class="metric-value" id="balance">$10000</div></div>
  <div class="metric"><div class="metric-label">P&L</div><div class="metric-value" id="pnl">$0</div></div>
  <div class="metric"><div class="metric-label">Abiertas</div><div class="metric-value" id="open-count">0</div></div>
  <div class="metric"><div class="metric-label">Win rate</div><div class="metric-value" id="winrate">—</div></div>
</div>
<div class="card">
  <div class="row">
    <div><span class="dot"></span><span id="bot-status">Listo para analizar</span></div>
    <div style="display:flex;gap:8px;">
      <button class="btn" onclick="loadMarkets()">Actualizar</button>
      <button class="btn btn-primary" onclick="botBet()">Apostar con IA</button>
    </div>
  </div>
  <div class="reasoning" id="reasoning"></div>
</div>
<div class="section-title">Mercados activos</div>
<div id="markets"><div class="empty">Cargando mercados...</div></div>
<div class="section-title">Mis apuestas ficticias</div>
<div class="card" id="bets"><div class="empty">Sin apuestas todavia.</div></div>
<script>
async function loadMetrics(){
  const d = await fetch("/metrics").then(r=>r.json());
  document.getElementById("balance").textContent = "$"+Math.round(d.balance);
  const pnl = d.balance - 10000;
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
    return "<div class='card'><div class='market-q'>"+m.question+"</div><div class='bar-track'><div class='bar-fill' style='width:"+m.prob+"%;background:"+color+"'></div></div><div class='bar-labels'><span style='color:"+color+"'>Si "+m.prob+"%</span><span style='color:#888'>No "+(100-m.prob)+"%</span></div><div class='row'><span style='font-size:12px;color:#888'>"+m.volume+"</span><button class='btn' onclick='manualBet("+i+")'>+ Apostar</button></div></div>";
  }).join("");
}
async function manualBet(i){
  await fetch("/bet?idx="+i,{method:"POST"});
  await loadMetrics(); await loadBets();
}
async function botBet(){
  document.getElementById("bot-status").textContent = "Claude analizando mercados...";
  document.getElementById("reasoning").textContent = "";
  const d = await fetch("/bot-bet",{method:"POST"}).then(r=>r.json());
  document.getElementById("bot-status").textContent = d.message;
  if(d.reasoning) document.getElementById("reasoning").textContent = "Razonamiento: "+d.reasoning;
  await loadMetrics(); await loadBets();
}
async function loadBets(){
  const d = await fetch("/bets").then(r=>r.json());
  if(!d.length){ document.getElementById("bets").innerHTML = "<div class='empty'>Sin apuestas todavia.</div>"; return; }
  document.getElementById("bets").innerHTML = d.map(b=>"<div class='bet-row'><div class='bet-q'>"+b.question+"</div><span class='badge "+(b.side==='SI'?'yes':'no')+"'>"+b.side+"</span><span style='color:#888'>$"+b.amount+"</span><span style='font-weight:500;color:"+(b.pnl>0?'#4caf50':b.pnl<0?'#f44336':'#888')+"'>"+b.pnl_text+"</span><span class='badge b-"+b.status+"'>"+b.status_text+"</span></div>").join("");
}
loadMarkets(); loadMetrics(); loadBets();
setInterval(function(){ loadMetrics(); loadBets(); }, 8000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

def get_state_value(key, default):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM state WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return float(row[0]) if row else default
    except:
        return default

def set_state_value(key, value):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s", (key, str(value), str(value)))
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

def get_all_bets():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM bets ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except:
        return []

def save_bet(bet):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO bets (id, question, side, amount, prob, status, pnl) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET status = %s, pnl = %s",
            (bet["id"], bet["question"], bet["side"], bet["amount"], bet["prob"], bet["status"], bet["pnl"], bet["status"], bet["pnl"]))
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

@app.route("/metrics")
def metrics():
    bets = get_all_bets()
    open_bets = [b for b in bets if b["status"] == "open"]
    won = int(get_state_value("won", 0))
    lost = int(get_state_value("lost", 0))
    total = won + lost
    winrate = str(round((won/total)*100))+"%" if total > 0 else "—"
    return jsonify({"balance": get_state_value("balance", 10000), "open": len(open_bets), "winrate": winrate})

@app.route("/markets")
def get_markets():
    try:
        r = requests.get(GAMMA_API+"/markets?closed=false&limit=10", timeout=5)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:6]
        result = []
        for m in markets:
            prob = 50
            try:
                prices = m.get("outcomePrices", "")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if prices:
                    prob = round(float(prices[0]) * 100)
            except:
                pass
            vol = float(m.get("volume", 0))
            vol_str = "$"+str(round(vol/1000000,1))+"M vol" if vol>1000000 else "$"+str(round(vol/1000))+"K vol" if vol>1000 else "—"
            result.append({"question": m.get("question","")[:80], "prob": prob, "volume": vol_str})
        return jsonify(result)
    except:
        return jsonify([])

def get_news(question):
    if not NEWS_API_KEY:
        return ""
    try:
        words = question.split()[:4]
        query = " ".join(words)
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "pageSize": 3, "sortBy": "publishedAt", "apiKey": NEWS_API_KEY},
            timeout=5
        )
        articles = r.json().get("articles", [])
        if not articles:
            return ""
        headlines = [a["title"] for a in articles[:3] if a.get("title")]
        return "Noticias recientes: " + " | ".join(headlines)
    except:
        return ""
def get_wikipedia(question):
    try:
        words = question.split()[:4]
        query = " ".join(words)
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"+query.replace(" ","_"),
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            extract = data.get("extract","")
            return "Wikipedia: "+extract[:500] if extract else ""
        r2 = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action":"query","list":"search","srsearch":query,"format":"json","srlimit":1},
            timeout=5
        )
        results = r2.json().get("query",{}).get("search",[])
        if results:
            title = results[0]["title"]
            r3 = requests.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/"+title.replace(" ","_"),
                timeout=5
            )
            if r3.status_code == 200:
                extract = r3.json().get("extract","")
                return "Wikipedia: "+extract[:500] if extract else ""
        return ""
    except:
        return ""

def ask_claude(question, market_prob):
    if not ANTHROPIC_API_KEY:
        return None, "Sin API key de Claude"
    try:
        news_context = get_news(question)
        wiki_context = get_wikipedia(question)
        prompt = f"""Eres un analista experto en mercados de prediccion.

Mercado: "{question}"
Probabilidad actual del mercado: {round(market_prob*100)}%
{news_context}
{wiki_context}

Analiza este mercado y responde SOLO en este formato JSON exacto, sin texto adicional:
{{"prob": 65, "side": "SI", "reasoning": "explicacion breve en español"}}

- prob: tu estimacion de probabilidad del evento (0-100)
- side: "SI" o "NO"
- reasoning: max 100 caracteres explicando por que
- confidence: numero del 1 al 10 indicando cuanta informacion real tenes para decidir (1=casi nada, 10=mucho contexto)"""

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=15
        )
        data = r.json()
        text = data["content"][0]["text"].strip()
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        parsed = json.loads(match.group()) if match else json.loads(text)
        return parsed, None
    except Exception as e:
        return None, str(e)

@app.route("/bet", methods=["POST"])
def manual_bet():
    idx = int(request.args.get("idx", 0))
    try:
        r = requests.get(GAMMA_API+"/markets?closed=false&limit=50", timeout=5)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:40]
        if idx >= len(markets):
            return jsonify({"ok": False})
        m = markets[idx]
        prob = 0.5
        try:
            prices = m.get("outcomePrices", "")
            if isinstance(prices, str):
                prices = json.loads(prices)
            if prices:
                prob = float(prices[0])
        except:
            pass
        place_bet(m.get("question","")[:80], "SI" if prob>=0.5 else "NO", 25, prob)
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

@app.route("/bot-bet", methods=["POST"])
def bot_bet():
    try:
        r = requests.get(GAMMA_API+"/markets?closed=false&limit=50", timeout=5)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        EXCLUDED = ["soccer", "football", "nfl", "nba", "nhl", "mlb", "sports", "basketball", "tennis", "golf", "cricket", "rugby", "f1", "racing", "olympics"]
        markets = [m for m in markets if m.get("active") and not m.get("closed") and not any(x in (m.get("question","") + " ".join([t.get("slug","") for t in m.get("tags",[])])).lower() for x in EXCLUDED)][:40]
        available = []
        for m in markets:
            try:
                prices = m.get("outcomePrices", "")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if prices:
                    prob = float(prices[0])
                    vol = float(m.get("volume", 0))
                    days_ok = True
                    end_date = m.get("endDate", m.get("end_date", ""))
                    if end_date:
                        try:
                            from datetime import timezone
                            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                            days_ok = (end - datetime.now(timezone.utc)).days <= 20
                        except:
                            days_ok = True
                    if 0.2 < prob < 0.8 and vol > 100000 and days_ok:
                        available.append((m, prob))
            except:
                pass
        existing_bets = get_all_bets()
        existing_questions = [b["question"] for b in existing_bets if b["status"] == "open"]
        available = [(m, p) for m, p in available if m.get("question","")[:80] not in existing_questions]
        if not available:
            return jsonify({"message": "Ya apostado en todos los mercados disponibles", "reasoning": ""})
        best_market = None
        best_result = None
        best_edge = 0
        for m_candidate, prob_candidate in available[:10]:
            q_candidate = m_candidate.get("question","")[:80]
            result_candidate, _ = ask_claude(q_candidate, prob_candidate)
            if result_candidate:
                edge_candidate = abs(result_candidate["prob"]/100 - prob_candidate)
                if edge_candidate > best_edge:
                    best_edge = edge_candidate
                    best_market = m_candidate
                    best_result = result_candidate
                    market_prob = prob_candidate
        if not best_market:
            m, market_prob = random.choice(available)
            question = m.get("question","")[:80]
            claude_result, error = ask_claude(question, market_prob)
        else:
            m = best_market
            question = best_market.get("question","")[:80]
            claude_result = best_result
            error = None
        if claude_result:
            ai_prob = claude_result["prob"] / 100
            side = claude_result["side"]
            reasoning = claude_result.get("reasoning", "")
            confidence_score = claude_result.get("confidence", 5)
            edge = abs(ai_prob - market_prob)
            if edge < 0.05 or confidence_score < 3:
                return jsonify({"message": "Claude: sin ventaja suficiente en este mercado", "reasoning": reasoning})
            confidence = abs(claude_result["prob"] - round(market_prob*100))
            if confidence > 20 and confidence_score >= 7:
                pct = 0.08
            elif confidence > 10 and confidence_score >= 5:
                pct = 0.05
            else:
                pct = 0.03
            amount = min(200, round(get_state_value("balance", 10000) * pct))
            place_bet(question, side, amount, market_prob)
            return jsonify({"message": "Claude aposto: "+side+" con $"+str(amount)+" USDC", "reasoning": reasoning})
        else:
            ai_prob = max(0.1, min(0.9, market_prob + random.uniform(-0.15, 0.15)))
            edge = abs(ai_prob - market_prob)
            if edge < 0.05:
                return jsonify({"message": "Sin ventaja suficiente", "reasoning": ""})
            side = "SI" if ai_prob > market_prob else "NO"
            amount = min(50, round(get_state_value("balance", 10000) * 0.03))
            place_bet(question, side, amount, market_prob)
            return jsonify({"message": "Apuesta colocada: "+side+" $"+str(amount), "reasoning": "Modo aleatorio: "+str(error)})
    except Exception as e:
        return jsonify({"message": "Error: "+str(e), "reasoning": ""})

@app.route("/bets")
def get_bets():
    bets = get_all_bets()[:10]
    result = []
    for b in bets:
        pnl = b["pnl"] or 0
        pnl_text = "—" if b["status"]=="open" else (("+" if pnl>0 else "")+str(round(pnl))+" USDC")
        status_map = {"open":"abierta","won":"ganada","lost":"perdida"}
        result.append({"question":b["question"],"side":b["side"],"amount":b["amount"],"pnl":pnl,"status":b["status"],"pnl_text":pnl_text,"status_text":status_map.get(b["status"],"")})
    return jsonify(result)

def place_bet(question, side, amount, prob):
    if get_state_value("balance", 10000) < amount:
        return
    set_state_value("balance", get_state_value("balance", 10000) - amount)
    bet = {"id": str(datetime.now().timestamp()), "question": question, "side": side, "amount": amount, "prob": prob, "status": "open", "pnl": 0}
    save_bet(bet)
    t = threading.Timer(random.uniform(5, 20), resolve_bet, args=[bet["id"]])
    t.daemon = True
    t.start()

def resolve_bet(bet_id):
    bets = get_all_bets()
    bet = next((b for b in bets if b["id"]==bet_id), None)
    if not bet or bet["status"]!="open":
        return
    try:
        r = requests.get(GAMMA_API+"/markets?closed=true&limit=50", timeout=5)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        resolved = next((m for m in markets if m.get("question","")[:80] == bet["question"] and m.get("resolved")), None)
        if not resolved:
            t = threading.Timer(3600, resolve_bet, args=[bet_id])
            t.daemon = True
            t.start()
            return
        outcomes = resolved.get("outcomes", ["Yes","No"])
        winner = resolved.get("winner", "")
        if bet["side"] == "SI":
            won = winner == outcomes[0] if outcomes else False
        else:
            won = winner == outcomes[1] if len(outcomes)>1 else False
    except:
        won = random.random() < 0.52
    bet["status"] = "won" if won else "lost"
    if won:
        winnings = bet["amount"] * (1/bet["prob"]-1) * 0.95
        bet["pnl"] = round(winnings, 2)
        balance = get_state_value("balance", 10000)
        set_state_value("balance", balance + bet["amount"] + winnings)
        set_state_value("won", get_state_value("won", 0) + 1)
    else:
        bet["pnl"] = -bet["amount"]
        set_state_value("lost", get_state_value("lost", 0) + 1)
    save_bet(bet)

def auto_bet_loop():
    import time
    while True:
        time.sleep(900)
        try:
            with app.test_request_context():
                bot_bet()
        except:
            pass

auto_thread = threading.Thread(target=auto_bet_loop, daemon=True)
auto_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
