from flask import Flask, jsonify, render_template_string
import requests
import json
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

GAMMA_API = os.getenv("GAMMA_API", "https://gamma-api.polymarket.com")


def parse_prob(market):
    prob = 50
    try:
        prices = market.get("outcomePrices", "")
        if isinstance(prices, str):
            prices = json.loads(prices)

        if isinstance(prices, list) and prices:
            prob = round(float(prices[0]) * 100)
    except Exception:
        pass
    return prob


def fetch_markets(limit=6):
    try:
        r = requests.get(
            f"{GAMMA_API}/markets?closed=false&limit=10",
            timeout=5
        )
        r.raise_for_status()
        data = r.json()

        markets = data if isinstance(data, list) else data.get("markets", [])
        markets = [m for m in markets if m.get("active") and not m.get("closed")][:limit]

        result = []
        for m in markets:
            result.append({
                "question": m.get("question", "Sin pregunta"),
                "prob": parse_prob(m),
                "volume": "Volumen N/A",
                "tag": "Polymarket"
            })

        if result:
            return result

    except Exception as e:
        app.logger.exception(f"Error leyendo Polymarket: {e}")

    return [
        {
            "question": "Demo: no se pudo leer Polymarket",
            "prob": 50,
            "volume": "N/A",
            "tag": "Fallback"
        }
    ]


@app.route("/")
def home():
    html = """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Polymarket Bot</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: #e2e8f0;
                margin: 0;
                padding: 24px;
            }
            .card {
                max-width: 900px;
                margin: 0 auto;
                background: #111827;
                border: 1px solid #243042;
                border-radius: 16px;
                padding: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,.25);
            }
            h1 { margin-top: 0; }
            .muted { color: #94a3b8; }
            button {
                background: #22c55e;
                color: #06240f;
                border: none;
                padding: 10px 14px;
                border-radius: 10px;
                cursor: pointer;
                font-weight: bold;
                margin-bottom: 16px;
            }
            button:hover { opacity: .9; }
            .item {
                background: #0b1220;
                border: 1px solid #243042;
                border-radius: 12px;
                padding: 14px;
                margin-bottom: 12px;
            }
            .top {
                display: flex;
                justify-content: space-between;
                gap: 12px;
                flex-wrap: wrap;
            }
            .prob {
                font-size: 22px;
                font-weight: bold;
            }
            a { color: #7dd3fc; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Polymarket Bot Online</h1>
            <p class="muted">Si ves esta página, Railway ya está respondiendo bien.</p>
            <p><a href="/markets" target="_blank">Ver /markets</a> · <a href="/health" target="_blank">Ver /health</a></p>
            <button onclick="loadMarkets()">Cargar mercados</button>
            <div id="content" class="muted">Todavía no cargué mercados.</div>
        </div>

        <script>
            async function loadMarkets() {
                const box = document.getElementById("content");
                box.innerHTML = "Cargando...";
                try {
                    const res = await fetch("/markets");
                    const data = await res.json();

                    if (!Array.isArray(data) || data.length === 0) {
                        box.innerHTML = "No hay mercados para mostrar.";
                        return;
                    }

                    box.innerHTML = data.map(m => `
                        <div class="item">
                            <div class="top">
                                <div>
                                    <div><strong>${m.question || "Sin pregunta"}</strong></div>
                                    <div class="muted">${m.tag || ""} · ${m.volume || ""}</div>
                                </div>
                                <div class="prob">${m.prob ?? 50}%</div>
                            </div>
                        </div>
                    `).join("");
                } catch (e) {
                    box.innerHTML = "Error cargando mercados.";
                }
            }

            loadMarkets();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/markets")
def get_markets():
    return jsonify(fetch_markets())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
