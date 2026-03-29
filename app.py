# ============================================================
# POLYMARKET PAPER TRADING BOT v2.0
# Arquitectura: Signal Aggregator → Dual Claude → Kelly → DB
# ============================================================

from flask import Flask, jsonify, render_template_string, request
import requests
import json
import os
import threading
import time
import re
import math
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# ── ENV ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATABASE_URL      = os.environ.get("DATABASE_URL", "")
NEWS_API_KEY      = os.environ.get("NEWS_API_KEY", "")
REDDIT_CLIENT_ID  = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_SECRET     = os.environ.get("REDDIT_SECRET", "")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

SPORTS_FILTER = [
    "soccer","football","nfl","nba","nhl","mlb","sports","basketball",
    "tennis","golf","cricket","rugby","f1","racing","olympics","qualify",
    "world cup","fifa","champion","league","playoff","serie a","premier",
    "bundesliga","ligue","laliga","ucl","ufc","boxing","wrestling","nascar",
    "formula","grand prix","match","tournament","game","season","draft"
]

# ── DB ───────────────────────────────────────────────────────
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

def get_state(key, default=0.0):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT value FROM state WHERE key=%s",(key,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return float(row[0]) if row else default
    except: return default

def set_state(key, value):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO state(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=%s",
                    (key,str(value),str(value)))
        conn.commit(); cur.close(); conn.close()
    except: pass

def get_all_bets():
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM bets ORDER BY id DESC")
        rows = cur.fetchall(); cur.close(); conn.close()
        return [dict(r) for r in rows]
    except: return []

def save_bet(bet):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO bets
                (id, question, market_id, side, amount, prob_market, prob_claude,
                 edge, confidence, kelly_f, status, pnl, reasoning, sources_used,
                 price_entry, price_current)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                status=EXCLUDED.status, pnl=EXCLUDED.pnl
        """, (
            bet["id"], bet["question"], bet.get("market_id",""),
            bet["side"], bet["amount"],
            bet.get("prob_market", 0.5), bet.get("prob_claude", 0.5),
            bet.get("edge", 0), bet.get("confidence", 5),
            bet.get("kelly_f", 0.03), bet["status"], bet["pnl"],
            bet.get("reasoning",""), bet.get("sources_used",""),
            bet.get("price_entry", 0.5), bet.get("price_current", 0.5)
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"[save_bet error] {e}")

def update_bet_price(bet_id, price_current, status=None, pnl=None,
                     take_profit_hit=False, stop_loss_hit=False):
    try:
        conn = get_db(); cur = conn.cursor()
        updates = ["price_current=%s"]
        vals    = [price_current]
        if status:
            updates += ["status=%s","resolved_at=NOW()"]
            vals.append(status)
        if pnl is not None:
            updates.append("pnl=%s"); vals.append(pnl)
        if take_profit_hit:
            updates.append("take_profit_hit=TRUE")
        if stop_loss_hit:
            updates.append("stop_loss_hit=TRUE")
        vals.append(bet_id)
        cur.execute(f"UPDATE bets SET {','.join(updates)} WHERE id=%s", vals)
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"[update_bet_price error] {e}")

# ── SIGNAL LAYER ─────────────────────────────────────────────

def get_news_signal(question):
    """Returns (headlines_text, signal_score -1..1)"""
    if not NEWS_API_KEY:
        return "", 0.0
    try:
        words = [w for w in question.split() if len(w) > 4][:5]
        query = " ".join(words[:3])
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "pageSize": 5, "sortBy": "publishedAt",
                    "language": "en", "apiKey": NEWS_API_KEY},
            timeout=6
        )
        articles = r.json().get("articles", [])
        if not articles:
            return "", 0.0
        headlines = [a["title"] for a in articles[:5] if a.get("title")]
        text = " | ".join(headlines[:4])
        return f"Noticias recientes: {text}", len(headlines) / 5.0
    except:
        return "", 0.0

def get_reddit_sentiment(question):
    """Searches Reddit for relevant posts, returns sentiment summary."""
    try:
        words = [w for w in question.split() if len(w) > 4][:3]
        query = " ".join(words)
        headers = {"User-Agent": "PolymarketBot/2.0"}
        r = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "sort": "new", "limit": 10, "t": "week"},
            headers=headers, timeout=6
        )
        posts = r.json().get("data", {}).get("children", [])
        if not posts:
            return "", 0.0
        titles = [p["data"]["title"] for p in posts[:5]]
        scores = [p["data"]["score"] for p in posts[:5]]
        avg_score = sum(scores) / len(scores) if scores else 0
        sentiment = "positivo" if avg_score > 10 else "neutral" if avg_score > 0 else "negativo"
        text = f"Reddit ({len(posts)} posts, sentiment {sentiment}): " + " | ".join(titles[:3])
        return text, min(1.0, len(posts) / 10.0)
    except:
        return "", 0.0

def get_metaculus_signal(question):
    """Tries to find a matching Metaculus question for cross-validation."""
    try:
        words = [w for w in question.split() if len(w) > 4][:3]
        query = " ".join(words)
        r = requests.get(
            "https://www.metaculus.com/api2/questions/",
            params={"search": query, "status": "open", "limit": 3},
            timeout=6
        )
        results = r.json().get("results", [])
        if not results:
            return "", None
        q = results[0]
        community_pred = q.get("community_prediction", {})
        pred_val = community_pred.get("full", {}).get("q2")
        if pred_val is None:
            return "", None
        title = q.get("title","")[:60]
        text = f"Metaculus forecasters estiman {round(pred_val*100)}% para: {title}"
        return text, pred_val
    except:
        return "", None

def get_price_history_signal(market_id):
    """Returns price momentum signal."""
    try:
        r = requests.get(
            f"{CLOB_API}/prices-history?market={market_id}&interval=1d&fidelity=1",
            timeout=6
        )
        history = r.json().get("history", [])
        if len(history) < 3:
            return "", 0.0, None
        current  = history[-1]["p"]
        day_ago  = history[-2]["p"]
        week_ago = history[-7]["p"] if len(history) >= 7 else history[0]["p"]
        chg_24h  = round((current - day_ago)  * 100, 1)
        chg_7d   = round((current - week_ago) * 100, 1)
        direction = "↑ subiendo" if chg_24h > 0 else "↓ bajando"
        # momentum signal: consistent direction = stronger signal
        momentum = chg_24h * 0.7 + chg_7d * 0.3
        text = f"Precio {direction} {abs(chg_24h)}% en 24h / {abs(chg_7d)}% en 7 días (actual: {round(current*100)}%)"
        return text, momentum / 100, current
    except:
        return "", 0.0, None

def get_orderbook_signal(market_id):
    """Gets real orderbook depth from CLOB for liquidity signal."""
    try:
        r = requests.get(f"{CLOB_API}/book?token_id={market_id}", timeout=5)
        data = r.json()
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks:
            return "", 0.0
        best_bid  = float(bids[0]["price"])  if bids else 0
        best_ask  = float(asks[0]["price"])  if asks else 1
        spread    = round((best_ask - best_bid) * 100, 2)
        bid_depth = sum(float(b["size"]) for b in bids[:5])
        ask_depth = sum(float(a["size"]) for a in asks[:5])
        imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth + 1)
        text = (f"Orderbook: spread {spread}%, "
                f"{'presión compradora' if imbalance > 0.1 else 'presión vendedora' if imbalance < -0.1 else 'equilibrado'} "
                f"(imbalance {round(imbalance*100)}%)")
        return text, imbalance
    except:
        return "", 0.0

def aggregate_signals(question, market_id, market_prob):
    """Combines all signals into a unified context string."""
    signals = []
    source_list = []

    news_text, news_conf = get_news_signal(question)
    if news_text:
        signals.append(news_text); source_list.append("NewsAPI")

    reddit_text, reddit_conf = get_reddit_sentiment(question)
    if reddit_text:
        signals.append(reddit_text); source_list.append("Reddit")

    meta_text, meta_pred = get_metaculus_signal(question)
    if meta_text:
        signals.append(meta_text); source_list.append("Metaculus")
        if meta_pred:
            meta_edge = meta_pred - market_prob
            if abs(meta_edge) > 0.08:
                signals.append(f"⚠️  Metaculus vs Polymarket: diferencia de {round(meta_edge*100)}pp — posible mispricing")

    price_text, momentum, current_price = get_price_history_signal(market_id)
    if price_text:
        signals.append(price_text); source_list.append("PriceHistory")

    ob_text, imbalance = get_orderbook_signal(market_id)
    if ob_text:
        signals.append(ob_text); source_list.append("Orderbook")

    return "\n".join(signals), ", ".join(source_list) or "ninguna", meta_pred

# ── PERFORMANCE CONTEXT FOR CLAUDE ───────────────────────────

def get_performance_context():
    """Builds a performance summary to feed Claude as memory."""
    bets = get_all_bets()
    resolved = [b for b in bets if b["status"] in ("won","lost")]
    if not resolved:
        return "Sin historial de apuestas resueltas aún."

    won   = [b for b in resolved if b["status"] == "won"]
    lost  = [b for b in resolved if b["status"] == "lost"]
    wr    = round(len(won) / len(resolved) * 100, 1)
    total_pnl = sum(b["pnl"] for b in resolved)

    # Edge accuracy: did Claude's prob align with outcome?
    edge_hits = 0
    for b in resolved:
        claude_prob = b.get("prob_claude") or b.get("prob_market", 0.5)
        if b["side"] == "SI":
            predicted_win = claude_prob > 0.5
        else:
            predicted_win = claude_prob < 0.5
        if (predicted_win and b["status"] == "won") or (not predicted_win and b["status"] == "lost"):
            edge_hits += 1
    edge_acc = round(edge_hits / len(resolved) * 100, 1) if resolved else 0

    # Recent errors for learning
    recent_lost = [b for b in lost[-3:]]
    error_context = ""
    if recent_lost:
        errors = "; ".join([f'"{b["question"][:40]}" (aposté {b["side"]}, reasoning: {b.get("reasoning","?")[:50]})' for b in recent_lost])
        error_context = f"\nÚltimas apuestas perdidas (APRENDE de estos errores): {errors}"

    return (f"Historial: {len(resolved)} resueltas, win rate {wr}%, P&L total {round(total_pnl)} USDC, "
            f"edge accuracy {edge_acc}%.{error_context}")

# ── KELLY CRITERION ───────────────────────────────────────────

def kelly_fraction(prob_win, odds_b, max_fraction=0.12, kelly_divisor=4):
    """
    Kelly: f* = (b*p - q) / b
    prob_win: Claude's estimated probability of winning
    odds_b:   net odds (payout per unit risked), e.g. if market prob=0.3, odds = 1/0.3 - 1 = 2.33
    Returns fraction of bankroll to bet (fractional Kelly = /4 for safety)
    """
    if odds_b <= 0 or prob_win <= 0:
        return 0.0
    q  = 1 - prob_win
    f  = (odds_b * prob_win - q) / odds_b
    f  = max(0, f / kelly_divisor)       # fractional Kelly
    return min(f, max_fraction)          # hard cap

def compute_bet_size(balance, kelly_f, confidence):
    """Translates Kelly fraction to actual dollar amount."""
    base   = balance * kelly_f
    # confidence multiplier: scale between 0.5x and 1.0x
    conf_mult = 0.5 + (confidence / 10) * 0.5
    amount = base * conf_mult
    return min(300, max(10, round(amount, 2)))

# ── DUAL CLAUDE PIPELINE ──────────────────────────────────────

def haiku_filter(markets_with_prob):
    """
    Claude Haiku: fast bulk filter.
    Takes list of (market, prob), returns top 5 most interesting.
    """
    if not ANTHROPIC_API_KEY:
        return markets_with_prob[:5]
    try:
        perf_ctx = get_performance_context()
        market_list = "\n".join([
            f"{i+1}. [{round(p*100)}%] {m.get('question','')[:80]} (vol: ${round(float(m.get('volume',0))/1000)}K)"
            for i, (m, p) in enumerate(markets_with_prob[:30])
        ])
        prompt = f"""Eres un filtro rápido de mercados de predicción.

Contexto de rendimiento del bot:
{perf_ctx}

Lista de mercados disponibles:
{market_list}

Selecciona los 5 mercados con MAYOR potencial de edge (donde el mercado puede estar equivocado).
Prioriza: eventos con información asimétrica, mercados con momentum claro, probabilidades extremas injustificadas.
Evita: mercados donde tenemos historial malo, temas sin información disponible.

Responde SOLO con JSON:
{{"top": [1, 3, 7, 12, 18]}}
(indices de los mercados seleccionados)"""

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001",
                  "max_tokens": 100,
                  "messages": [{"role":"user","content":prompt}]},
            timeout=15
        )
        text  = r.json()["content"][0]["text"].strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        data  = json.loads(match.group()) if match else {}
        indices = [i-1 for i in data.get("top", []) if 0 < i <= len(markets_with_prob)]
        if indices:
            return [markets_with_prob[i] for i in indices[:5]]
    except Exception as e:
        print(f"[haiku_filter error] {e}")
    return markets_with_prob[:5]

def sonnet_analyze(question, market_prob, end_date, market_id, signals_text, meta_pred=None):
    """
    Claude Sonnet: deep analysis on a single market.
    Returns full structured analysis.
    """
    if not ANTHROPIC_API_KEY:
        return None, "Sin API key"
    try:
        perf_ctx = get_performance_context()
        meta_hint = f"\nPredicción de Metaculus (forecasters expertos): {round(meta_pred*100)}%" if meta_pred else ""
        prompt = f"""Eres un analista elite de mercados de predicción con track record probado.

=== CONTEXTO DE RENDIMIENTO ===
{perf_ctx}

=== MERCADO A ANALIZAR ===
Pregunta: "{question}"
Probabilidad actual del mercado: {round(market_prob*100)}%
Fecha de resolución: {end_date}
{meta_hint}

=== SEÑALES AGREGADAS ===
{signals_text if signals_text else "Sin señales adicionales disponibles."}

=== TU TAREA ===
1. Estima la probabilidad REAL del evento (no la del mercado)
2. Identifica si hay edge real (diferencia > 8pp entre tu estimación y el mercado)
3. Decide si apostar SI o NO
4. Evalúa tu confianza en la información disponible (1-10)

Razona paso a paso internamente, luego responde SOLO en este JSON exacto:
{{
  "prob": 65,
  "side": "SI",
  "reasoning": "explicación de máx 120 caracteres en español",
  "confidence": 7,
  "edge_quality": "alta|media|baja",
  "key_signal": "la señal más importante que usaste"
}}"""

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-6",
                  "max_tokens": 300,
                  "messages": [{"role":"user","content":prompt}]},
            timeout=25
        )
        text  = r.json()["content"][0]["text"].strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(match.group()) if match else None, None
    except Exception as e:
        return None, str(e)

# ── TAKE PROFIT / STOP LOSS MONITOR ──────────────────────────

TAKE_PROFIT_THRESHOLD = 0.20   # +20% from entry → close
STOP_LOSS_THRESHOLD   = 0.25   # -50% → close (paper only)

def monitor_open_positions():
    """Checks open bets against current market price. Simulates take profit / stop loss."""
    bets = get_all_bets()
    open_bets = [b for b in bets if b["status"] == "open"]
    balance   = get_state("balance", 10000)

    for b in open_bets:
        try:
            market_id = b.get("market_id","")
            if not market_id:
                continue
            _, _, current_price = get_price_history_signal(market_id)
            if current_price is None:
                continue

            entry = b.get("price_entry") or b.get("prob_market", 0.5)
            side  = b["side"]

            # For NO bets, we win when price goes DOWN
            if side == "NO":
                price_move = (entry - current_price) / entry   # positive = price dropped = good for NO
            else:
                price_move = (current_price - entry) / entry   # positive = price up = good for SI

            update_bet_price(b["id"], current_price)

            if price_move >= TAKE_PROFIT_THRESHOLD:
                # Simulate closing at current favorable price
                if side == "NO":
                    implied_odds = 1 / (1 - current_price) - 1
                else:
                    implied_odds = 1 / current_price - 1
                winnings = b["amount"] * implied_odds * 0.95
                new_balance = balance + b["amount"] + winnings
                set_state("balance", new_balance)
                set_state("won", get_state("won",0) + 1)
                update_bet_price(b["id"], current_price, status="won",
                                 pnl=round(winnings,2), take_profit_hit=True)
                print(f"[TAKE PROFIT] {b['question'][:40]} +{round(winnings,2)} USDC")
                balance = new_balance

            elif price_move <= -STOP_LOSS_THRESHOLD:
                update_bet_price(b["id"], current_price, status="lost",
                                 pnl=-b["amount"], stop_loss_hit=True)
                set_state("lost", get_state("lost",0) + 1)
                print(f"[STOP LOSS] {b['question'][:40]}")

        except Exception as e:
            print(f"[monitor error] {e}")

# ── REAL RESOLUTION ───────────────────────────────────────────

def resolve_bet_real(bet_id):
    """Tries to resolve a bet using real Polymarket data."""
    bets = get_all_bets()
    bet  = next((b for b in bets if b["id"] == bet_id), None)
    if not bet or bet["status"] != "open":
        return

    try:
        mid = bet.get("market_id","")
        if mid:
            r = requests.get(f"{GAMMA_API}/markets/{mid}", timeout=5)
            m = r.json()
            if m.get("resolved") or m.get("closed"):
                winner  = m.get("winner","")
                outcomes= m.get("outcomes", ["Yes","No"])
                if bet["side"] == "SI":
                    won = (winner == outcomes[0]) if outcomes else False
                else:
                    won = (winner == outcomes[1]) if len(outcomes) > 1 else False
                _finalize_bet(bet, won)
                return

        # Fallback: search by question in closed markets
        r2 = requests.get(f"{GAMMA_API}/markets?closed=true&limit=100", timeout=5)
        data = r2.json()
        markets = data if isinstance(data, list) else data.get("markets",[])
        resolved = next((m for m in markets
                         if m.get("question","")[:80] == bet["question"]
                         and m.get("resolved")), None)
        if resolved:
            winner  = resolved.get("winner","")
            outcomes= resolved.get("outcomes",["Yes","No"])
            won = (winner == outcomes[0]) if bet["side"] == "SI" else (winner == outcomes[1] if len(outcomes)>1 else False)
            _finalize_bet(bet, won)
        else:
            # Not resolved yet — retry in 2h
            t = threading.Timer(7200, resolve_bet_real, args=[bet_id])
            t.daemon = True; t.start()
    except Exception as e:
        print(f"[resolve error] {e}")
        t = threading.Timer(7200, resolve_bet_real, args=[bet_id])
        t.daemon = True; t.start()

def _finalize_bet(bet, won):
    balance = get_state("balance", 10000)
    if won:
        # Use actual market prob for correct payout
        entry_prob = bet.get("price_entry") or bet["prob_market"]
        odds       = (1 / entry_prob - 1) if bet["side"] == "SI" else (1 / (1 - entry_prob) - 1)
        winnings   = bet["amount"] * odds * 0.95
        set_state("balance", balance + bet["amount"] + winnings)
        set_state("won", get_state("won",0) + 1)
        update_bet_price(bet["id"], bet.get("price_current", entry_prob),
                         status="won", pnl=round(winnings,2))
        print(f"[WON] {bet['question'][:40]} +{round(winnings,2)} USDC")
    else:
        set_state("lost", get_state("lost",0) + 1)
        update_bet_price(bet["id"], bet.get("price_current", bet["prob_market"]),
                         status="lost", pnl=-bet["amount"])
        print(f"[LOST] {bet['question'][:40]} -{bet['amount']} USDC")

def place_bet(question, market_id, side, amount, prob_market,
              prob_claude, edge, confidence, kelly_f, reasoning, sources_used):
    balance = get_state("balance", 10000)
    if balance < amount:
        return None
    set_state("balance", balance - amount)
    set_state("bets_placed", get_state("bets_placed",0) + 1)
    set_state("total_edge", get_state("total_edge",0) + edge)

    bet = {
        "id":           str(datetime.now().timestamp()),
        "question":     question,
        "market_id":    market_id,
        "side":         side,
        "amount":       amount,
        "prob_market":  prob_market,
        "prob_claude":  prob_claude,
        "edge":         round(edge, 4),
        "confidence":   confidence,
        "kelly_f":      round(kelly_f, 4),
        "status":       "open",
        "pnl":          0,
        "reasoning":    reasoning,
        "sources_used": sources_used,
        "price_entry":  prob_market,
        "price_current":prob_market,
    }
    save_bet(bet)

    # Schedule real resolution check
    t = threading.Timer(3600, resolve_bet_real, args=[bet["id"]])
    t.daemon = True; t.start()
    return bet

# ── MAIN BOT LOGIC ────────────────────────────────────────────

@app.route("/bot-bet", methods=["POST"])
def bot_bet():
    try:
        # 1. Fetch markets
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=100", timeout=8)
        data    = r.json()
        markets = data if isinstance(data, list) else data.get("markets",[])

        # 2. Filter: no sports, prob range, volume, expiry
        available = []
        now_utc = datetime.now(timezone.utc)
        for m in markets:
            if not m.get("active") or m.get("closed"):
                continue
            q = m.get("question","").lower()
            tags = " ".join(t.get("slug","") for t in m.get("tags",[]))
            if any(x in q + tags for x in SPORTS_FILTER):
                continue
            try:
                prices = m.get("outcomePrices","")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if not prices:
                    continue
                prob = float(prices[0])
                vol  = float(m.get("volume", 0))
                if not (0.20 < prob < 0.80):
                    continue
                if vol < 10000:
                    continue
                end_date = m.get("endDate", m.get("end_date",""))
                if end_date:
                    end = datetime.fromisoformat(end_date.replace("Z","+00:00"))
                    days_left = (end - now_utc).days
                    if days_left > 365 or days_left < 1:
                        continue
                    m['days_left'] = days_left
                available.append((m, prob))
            except:
                continue

        # 3. Deduplicate against open bets
        existing_bets     = get_all_bets()
        existing_questions = {b["question"] for b in existing_bets if b["status"] == "open"}
        existing_keywords  = set()
        for q in existing_questions:
            for w in q.lower().split():
                if len(w) > 5:
                    existing_keywords.add(w)

        def topic_overlap(question):
            words   = question.lower().split()
            matches = sum(1 for w in words if len(w) > 5 and w in existing_keywords)
            return matches >= 3

        available = [(m, p) for m, p in available
                     if m.get("question","")[:80] not in existing_questions
                     and not topic_overlap(m.get("question",""))]
        open_count = len([b for b in get_all_bets() if b["status"]=="open"])
        if open_count >= 15:
            return jsonify({"message": f"Máximo 15 apuestas abiertas ({open_count} activas)", "reasoning": ""})
        if not available:
            return jsonify({"message": "Sin mercados nuevos disponibles", "reasoning": ""})

        # 4. Haiku filter → top 5
        available.sort(key=lambda x: x[0].get('days_left', 365))
        top5 = haiku_filter(available)

        # 5. Sonnet deep analysis on each → pick best edge
        best_result   = None
        best_market   = None
        best_prob     = None
        best_edge     = 0
        best_signals  = ""
        best_sources  = ""
        best_meta     = None

        for m_candidate, prob_candidate in top5:
            q   = m_candidate.get("question","")[:80]
            mid = m_candidate.get("id","")
            end = m_candidate.get("endDate", m_candidate.get("end_date",""))

            signals_text, sources, meta_pred = aggregate_signals(q, mid, prob_candidate)
            result, err = sonnet_analyze(q, prob_candidate, end, mid, signals_text, meta_pred)

            if not result:
                continue
            ai_prob = result["prob"] / 100
            edge    = abs(ai_prob - prob_candidate)

            if edge > best_edge:
                best_edge    = edge
                best_market  = m_candidate
                best_prob    = prob_candidate
                best_result  = result
                best_signals = signals_text
                best_sources = sources
                best_meta    = meta_pred

        if not best_market or not best_result:
            return jsonify({"message": "Claude: sin edge suficiente en ningún mercado", "reasoning": ""})

        ai_prob    = best_result["prob"] / 100
        side       = best_result["side"]
        confidence = best_result.get("confidence", 5)
        reasoning  = best_result.get("reasoning", "")
        edge       = best_edge

        # 6. Edge threshold + confidence gate
        if edge < 0.08 or confidence < 4:
            return jsonify({
                "message": f"Claude: edge {round(edge*100,1)}pp insuficiente (mín 8pp) o confianza baja ({confidence}/10)",
                "reasoning": reasoning
            })

        # 7. Kelly sizing
        if side == "SI":
            odds_b = 1 / best_prob - 1
        else:
            odds_b = 1 / (1 - best_prob) - 1
        kelly_f = kelly_fraction(ai_prob if side=="SI" else (1-ai_prob), odds_b)

        if kelly_f == 0:
            return jsonify({"message": "Kelly: sin edge positivo esperado", "reasoning": reasoning})

        balance = get_state("balance", 10000)
        amount  = compute_bet_size(balance, kelly_f, confidence)

        # 8. Place bet
        question = best_market.get("question","")[:80]
        market_id = best_market.get("id","")
        bet = place_bet(
            question, market_id, side, amount,
            best_prob, ai_prob, edge, confidence,
            kelly_f, reasoning, best_sources
        )
        if not bet:
            return jsonify({"message": "Saldo insuficiente", "reasoning": ""})

        return jsonify({
            "message":    f"✅ Claude apostó {side} ${amount} USDC (Kelly {round(kelly_f*100,1)}%, edge {round(edge*100,1)}pp, conf {confidence}/10)",
            "reasoning":  reasoning,
            "key_signal": best_result.get("key_signal",""),
            "sources":    best_sources,
            "edge":       round(edge*100,1),
            "confidence": confidence
        })

    except Exception as e:
        return jsonify({"message": f"Error: {e}", "reasoning": ""})

# ── API ENDPOINTS ─────────────────────────────────────────────

@app.route("/metrics")
def metrics():
    bets       = get_all_bets()
    open_bets  = [b for b in bets if b["status"] == "open"]
    won        = int(get_state("won",0))
    lost       = int(get_state("lost",0))
    total      = won + lost
    winrate    = f"{round(won/total*100)}%" if total > 0 else "—"
    avg_edge   = round(get_state("total_edge",0) / max(1,get_state("bets_placed",1)) * 100, 1)
    total_pnl  = sum(b["pnl"] for b in bets if b["status"] != "open")
    return jsonify({
        "balance":    get_state("balance",10000),
        "open":       len(open_bets),
        "winrate":    winrate,
        "won":        won,
        "lost":       lost,
        "avg_edge":   f"{avg_edge}pp",
        "total_pnl":  round(total_pnl, 2)
    })

@app.route("/markets")
def get_markets():
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=20", timeout=5)
        data    = r.json()
        markets = data if isinstance(data, list) else data.get("markets",[])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:20]
        result  = []
        for m in markets:
            try:
                prices = m.get("outcomePrices","")
                if isinstance(prices, str): prices = json.loads(prices)
                prob = round(float(prices[0]) * 100) if prices else 50
                vol  = float(m.get("volume", 0))
                vol_str = (f"${round(vol/1e6,1)}M" if vol>1e6 else f"${round(vol/1000)}K") + " vol"
                result.append({"question": m.get("question","")[:80], "prob": prob, "volume": vol_str})
            except: continue
        return jsonify(result)
    except: return jsonify([])

@app.route("/bets")
def get_bets():
    bets   = get_all_bets()[:15]
    result = []
    for b in bets:
        pnl      = b["pnl"] or 0
        pnl_text = "—" if b["status"]=="open" else (("+" if pnl>0 else "")+str(round(pnl))+" USDC")
        tp_flag  = " 🎯" if b.get("take_profit_hit") else ""
        sl_flag  = " 🛑" if b.get("stop_loss_hit")   else ""
        result.append({
            "question":    b["question"],
            "side":        b["side"],
            "amount":      b["amount"],
            "pnl":         pnl,
            "status":      b["status"],
            "pnl_text":    pnl_text,
            "status_text": {"open":"abierta","won":"ganada","lost":"perdida"}.get(b["status"],"") + tp_flag + sl_flag,
            "edge":        round((b.get("edge") or 0)*100, 1),
            "confidence":  b.get("confidence", 0),
            "kelly_f":     round((b.get("kelly_f") or 0)*100, 1),
            "reasoning":   b.get("reasoning",""),
            "sources":     b.get("sources_used",""),
        })
    return jsonify(result)

@app.route("/monitor", methods=["POST"])
def manual_monitor():
    threading.Thread(target=monitor_open_positions, daemon=True).start()
    return jsonify({"ok": True, "message": "Monitor iniciado"})

@app.route("/performance")
def performance():
    bets     = get_all_bets()
    resolved = [b for b in bets if b["status"] in ("won","lost")]
    if not resolved:
        return jsonify({"message": "Sin apuestas resueltas aún"})
    by_edge = {"high":[],"medium":[],"low":[]}
    for b in resolved:
        e = (b.get("edge") or 0)
        cat = "high" if e > 0.15 else "medium" if e > 0.08 else "low"
        by_edge[cat].append(b)
    def wr(lst):
        if not lst: return "—"
        w = sum(1 for b in lst if b["status"]=="won")
        return f"{round(w/len(lst)*100)}% ({len(lst)} bets)"
    return jsonify({
        "win_rate_high_edge":   wr(by_edge["high"]),
        "win_rate_medium_edge": wr(by_edge["medium"]),
        "win_rate_low_edge":    wr(by_edge["low"]),
        "avg_confidence_won":   round(sum(b.get("confidence",5) for b in resolved if b["status"]=="won") / max(1,sum(1 for b in resolved if b["status"]=="won")),1),
        "sources_effectiveness": "Ver /bets para detalle por apuesta"
    })

# ── BACKGROUND LOOPS ──────────────────────────────────────────

def bet_loop():
    while True:
        time.sleep(900)   # every 15 min
        try:
            with app.test_request_context():
                bot_bet()
        except Exception as e:
            print(f"[bet_loop error] {e}")

def monitor_loop():
    while True:
        time.sleep(3600)  # every 1h
        try:
            monitor_open_positions()
        except Exception as e:
            print(f"[monitor_loop error] {e}")

threading.Thread(target=bet_loop,     daemon=True).start()
threading.Thread(target=monitor_loop, daemon=True).start()

# ── FRONTEND ──────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html>
<head>
<title>Polymarket Bot v2</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#e0e0e0;padding:20px;max-width:900px;margin:0 auto}
h1{font-size:18px;font-weight:500;margin-bottom:3px}
.sub{font-size:12px;color:#555;margin-bottom:18px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.metric{background:#111;border-radius:10px;padding:12px}
.metric-label{font-size:10px;color:#555;margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em}
.metric-value{font-size:20px;font-weight:500}
.positive{color:#4caf50}.negative{color:#f44336}.neutral{color:#888}
.card{background:#111;border-radius:10px;padding:14px;margin-bottom:10px;border:1px solid #1a1a1a}
.market-q{font-size:13px;font-weight:500;margin-bottom:8px;line-height:1.4}
.bar-track{height:5px;background:#1e1e1e;border-radius:3px;overflow:hidden;margin-bottom:3px}
.bar-fill{height:100%;border-radius:3px}
.bar-labels{display:flex;justify-content:space-between;font-size:11px;margin-bottom:8px}
.btn{padding:5px 14px;border-radius:7px;border:1px solid #2a2a2a;background:transparent;color:#e0e0e0;cursor:pointer;font-size:11px}
.btn:hover{background:#1a1a1a}
.btn-primary{background:#e0e0e0;color:#0a0a0a;border-color:#e0e0e0;font-weight:500}
.btn-primary:hover{opacity:.85}
.row{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.bet-row{padding:10px 0;border-bottom:1px solid #1a1a1a;font-size:12px}
.bet-row:last-child{border-bottom:none}
.bet-main{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}
.bet-meta{font-size:10px;color:#444;margin-top:3px}
.bet-q{flex:1;min-width:100px;font-size:12px;line-height:1.3}
.badge{font-size:10px;padding:2px 8px;border-radius:5px;font-weight:500;white-space:nowrap}
.yes{background:#0f2e0f;color:#4caf50}.no{background:#2e0f0f;color:#f44336}
.b-open{background:#1a1a1a;color:#555}.b-won{background:#0f2e0f;color:#4caf50}.b-lost{background:#2e0f0f;color:#f44336}
.edge-badge{background:#1a1a2e;color:#7b7bff;font-size:10px;padding:2px 7px;border-radius:5px}
.dot{width:7px;height:7px;border-radius:50%;background:#4caf50;display:inline-block;margin-right:7px;animation:pulse 2s infinite}
.section-title{font-size:10px;color:#444;text-transform:uppercase;letter-spacing:.08em;margin:14px 0 6px}
.empty{color:#444;font-size:12px}
.reasoning-text{font-size:11px;color:#555;margin-top:5px;font-style:italic}
.signal-text{font-size:10px;color:#3a6ea5;margin-top:3px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@media(max-width:500px){.metrics{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<h1>Polymarket Bot v2</h1>
<div class="sub">Paper trading · Kelly Criterion · Dual Claude · Multi-signal</div>
<div class="metrics">
  <div class="metric"><div class="metric-label">Saldo</div><div class="metric-value" id="balance">$10000</div></div>
  <div class="metric"><div class="metric-label">P&L Total</div><div class="metric-value" id="pnl">$0</div></div>
  <div class="metric"><div class="metric-label">Abiertas</div><div class="metric-value" id="open-count">0</div></div>
  <div class="metric"><div class="metric-label">Win rate</div><div class="metric-value" id="winrate">—</div></div>
  <div class="metric"><div class="metric-label">Ganadas</div><div class="metric-value positive" id="won">0</div></div>
  <div class="metric"><div class="metric-label">Perdidas</div><div class="metric-value negative" id="lost">0</div></div>
  <div class="metric"><div class="metric-label">Edge medio</div><div class="metric-value" id="avg-edge">—</div></div>
  <div class="metric"><div class="metric-label">P&L USDC</div><div class="metric-value" id="total-pnl">0</div></div>
</div>
<div class="card">
  <div class="row">
    <div><span class="dot"></span><span id="bot-status">Bot v2 listo</span></div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn" onclick="loadMarkets()">Actualizar</button>
      <button class="btn" onclick="doMonitor()">Monitor</button>
      <button class="btn btn-primary" onclick="botBet()">🧠 Apostar con IA</button>
    </div>
  </div>
  <div class="reasoning-text" id="reasoning"></div>
  <div class="signal-text" id="signal-info"></div>
</div>
<div class="section-title">Mercados activos</div>
<div id="markets"><div class="empty">Cargando...</div></div>
<div class="section-title">Mis apuestas</div>
<div class="card" id="bets"><div class="empty">Sin apuestas todavía.</div></div>

<script>
async function loadMetrics(){
  const d = await fetch("/metrics").then(r=>r.json());
  document.getElementById("balance").textContent = "$"+Math.round(d.balance);
  const pnl = d.balance - 10000;
  const el = document.getElementById("pnl");
  el.textContent = (pnl>=0?"+":"")+Math.round(pnl);
  el.className = "metric-value "+(pnl>0?"positive":pnl<0?"negative":"neutral");
  document.getElementById("open-count").textContent = d.open;
  document.getElementById("winrate").textContent = d.winrate;
  document.getElementById("won").textContent = d.won||0;
  document.getElementById("lost").textContent = d.lost||0;
  document.getElementById("avg-edge").textContent = d.avg_edge||"—";
  const tpnl = document.getElementById("total-pnl");
  tpnl.textContent = (d.total_pnl>=0?"+":"")+Math.round(d.total_pnl);
  tpnl.className = "metric-value "+(d.total_pnl>0?"positive":d.total_pnl<0?"negative":"neutral");
}
async function loadMarkets(){
  document.getElementById("markets").innerHTML="<div class='empty'>Cargando...</div>";
  const d = await fetch("/markets").then(r=>r.json());
  if(!d.length){document.getElementById("markets").innerHTML="<div class='empty'>Sin mercados.</div>";return;}
  document.getElementById("markets").innerHTML = d.map(m=>{
    const c = m.prob>50?"#4caf50":"#ff9800";
    return `<div class='card'><div class='market-q'>${m.question}</div>
    <div class='bar-track'><div class='bar-fill' style='width:${m.prob}%;background:${c}'></div></div>
    <div class='bar-labels'><span style='color:${c}'>SI ${m.prob}%</span><span style='color:#444'>NO ${100-m.prob}%</span></div>
    <div class='row'><span style='font-size:11px;color:#444'>${m.volume}</span></div></div>`;
  }).join("");
}
async function botBet(){
  document.getElementById("bot-status").textContent="🧠 Haiku filtrando → Sonnet analizando...";
  document.getElementById("reasoning").textContent="";
  document.getElementById("signal-info").textContent="";
  const d = await fetch("/bot-bet",{method:"POST"}).then(r=>r.json());
  document.getElementById("bot-status").textContent = d.message;
  if(d.reasoning) document.getElementById("reasoning").textContent = "Razonamiento: "+d.reasoning;
  if(d.sources||d.key_signal) document.getElementById("signal-info").textContent =
    "Fuentes: "+(d.sources||"—")+(d.key_signal?" · Señal clave: "+d.key_signal:"");
  await loadMetrics(); await loadBets();
}
async function doMonitor(){
  document.getElementById("bot-status").textContent="Monitoreando posiciones abiertas...";
  await fetch("/monitor",{method:"POST"});
  document.getElementById("bot-status").textContent="Monitor ejecutado";
  await loadMetrics(); await loadBets();
}
async function loadBets(){
  const d = await fetch("/bets").then(r=>r.json());
  if(!d.length){document.getElementById("bets").innerHTML="<div class='empty'>Sin apuestas todavía.</div>";return;}
  document.getElementById("bets").innerHTML = d.map(b=>{
    const pnlClass = b.pnl>0?"positive":b.pnl<0?"negative":"neutral";
    const sideClass = b.side==="SI"?"yes":"no";
    const stClass = "b-"+b.status;
    return `<div class='bet-row'>
      <div class='bet-main'>
        <div class='bet-q'>${b.question}</div>
        <span class='badge ${sideClass}'>${b.side}</span>
        <span style='color:#555'>$${b.amount}</span>
        <span class='edge-badge'>edge ${b.edge}pp</span>
        <span style='color:#555;font-size:10px'>conf ${b.confidence}/10</span>
        <span class='${pnlClass}' style='font-weight:500'>${b.pnl_text}</span>
        <span class='badge ${stClass}'>${b.status_text}</span>
      </div>
      ${b.reasoning?`<div class='bet-meta'>💬 ${b.reasoning}</div>`:""}
      ${b.sources?`<div class='bet-meta' style='color:#3a4a5a'>📡 ${b.sources}</div>`:""}
    </div>`;
  }).join("");
}
loadMarkets(); loadMetrics(); loadBets();
setInterval(()=>{loadMetrics();loadBets();}, 10000);
</script>
</body>
</html>"""

@app.route("/setup-db")
def setup_db():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            CREATE TABLE bets (
                id TEXT PRIMARY KEY,
                question TEXT,
                market_id TEXT,
                side TEXT,
                amount REAL,
                prob_market REAL,
                prob_claude REAL,
                edge REAL,
                confidence INTEGER,
                kelly_f REAL,
                status TEXT DEFAULT 'open',
                pnl REAL DEFAULT 0,
                reasoning TEXT,
                sources_used TEXT,
                price_entry REAL,
                price_current REAL,
                take_profit_hit BOOLEAN DEFAULT FALSE,
                stop_loss_hit BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                resolved_at TIMESTAMPTZ
            )
        """)
        conn.commit(); cur.close(); conn.close()
        return "Tabla creada OK"
    except Exception as e:
        return f"Error: {e}"
@app.route("/debug")
def debug():
    try:
        r = requests.get(f"{GAMMA_API}/markets?closed=false&limit=100", timeout=8)
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets",[])
        total = len(markets)
        active = [m for m in markets if m.get("active") and not m.get("closed")]
        no_sports = [m for m in active if not any(x in m.get("question","").lower() for x in SPORTS_FILTER)]
        in_range = []
        for m in no_sports:
            try:
                prices = m.get("outcomePrices","")
                if isinstance(prices, str): prices = json.loads(prices)
                prob = float(prices[0])
                vol = float(m.get("volume",0))
                if 0.20 < prob < 0.80 and vol > 10000:
                    in_range.append(m.get("question","")[:60])
            except: continue
        return jsonify({
            "total": total,
            "active": len(active),
            "no_sports": len(no_sports),
            "pass_filters": len(in_range),
            "examples": in_range[:5]
        })
    except Exception as e:
        return jsonify({"error": str(e)})
@app.route("/clear-open", methods=["POST"])
def clear_open():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE state SET value='10000.0' WHERE key='balance'")
        cur.execute("UPDATE state SET value='0' WHERE key='won'")
        cur.execute("UPDATE state SET value='0' WHERE key='lost'")
        conn.commit(); cur.close(); conn.close()
        return jsonify({"ok": True, "message": "Apuestas viejas cerradas"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
