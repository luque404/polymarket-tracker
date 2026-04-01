
# ============================================================
# POLYMARKET PAPER TRADING BOT v3.0
# Research packets -> structured analysis -> portfolio allocation
# ============================================================

import json
import hashlib
import logging
import os
import re
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import psycopg2
import requests
from flask import Flask, jsonify, render_template_string, request
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── ENV / CONFIG ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")
METACULUS_API_KEY = os.environ.get("METACULUS_API_KEY", "")
ENABLE_BACKGROUND_LOOPS = os.environ.get("ENABLE_BACKGROUND_LOOPS", "").lower() == "true"
RESEARCH_LAB_MODE = os.environ.get("RESEARCH_LAB_MODE", "true").lower() == "true"

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
try:
    PAPER_STARTING_BALANCE = float(os.environ.get("PAPER_STARTING_BALANCE", "50000"))
except ValueError:
    PAPER_STARTING_BALANCE = 50000.0
DEFAULT_BALANCE = PAPER_STARTING_BALANCE
CURRENT_STRATEGY_VERSION = os.environ.get("STRATEGY_VERSION", "research_lab_v4")
FAST_MODEL = os.environ.get("CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")
STRONG_MODEL = os.environ.get("CLAUDE_STRONG_MODEL", "claude-sonnet-4-6")
REQUEST_TIMEOUT = 8
BET_LOOP_INTERVAL_SECONDS = 600
MONITOR_LOOP_INTERVAL_SECONDS = 3600
INITIAL_RESOLUTION_CHECK_SECONDS = 3600
RESOLUTION_RETRY_SECONDS = 7200
MARKETS_FETCH_LIMIT = 500
MARKETS_PREVIEW_LIMIT = 20
MAX_OPEN_BETS = 96
MAX_POSITIONS_PER_CYCLE = 16
MAX_CORE_POSITIONS_PER_CYCLE = 4
MAX_SECONDARY_POSITIONS_PER_CYCLE = 7
MAX_EXPLORATORY_POSITIONS_PER_CYCLE = 8
MAX_TOTAL_EXPOSURE_PCT = 0.78
MAX_CATEGORY_EXPOSURE_PCT = 0.20
MAX_SIDE_EXPOSURE_PCT = 0.42
MAX_THESIS_EXPOSURE_PCT = 0.20
MIN_MARKET_PROB = 0.08
MAX_MARKET_PROB = 0.92
MIN_MARKET_VOLUME = 20
MAX_DAYS_TO_RESOLUTION = 365
MIN_DAYS_TO_RESOLUTION = 1
MIN_COMPOUND_SCORE = 0.42
MIN_EDGE_TO_BET = 0.05
MIN_CONFIDENCE_TO_BET = 5
MIN_SOURCE_QUALITY_TO_BET = 0.35
MIN_EVIDENCE_STRENGTH_TO_BET = 0.35
TAKE_PROFIT_THRESHOLD = 0.18
STOP_LOSS_THRESHOLD = 0.22
TRAILING_STOP_GIVEBACK = 0.10
CORE_MAX_FRACTION = 0.14
EXPERIMENTAL_MAX_FRACTION = 0.025
EXPERIMENTAL_SCORE_FLOOR = 0.29
EXPLORATION_CAPITAL_RESERVE_PCT = 0.20
LONG_DATED_PENALTY_START_DAYS = 60
FAST_FEEDBACK_DAYS = 28
POLYMARKET_FEE_HAIRCUT = 0.95
WATCHLIST_LIMIT = 16
TIER_A_SCORE_FLOOR = 0.68
TIER_B_SCORE_FLOOR = 0.52
TIER_C_SCORE_FLOOR = 0.34
OBVIOUS_ENOUGH_SCORE = 0.46
CORE_BUDGET_PCT = 0.34
SECONDARY_BUDGET_PCT = 0.26
EXPLORATORY_BUDGET_PCT = 0.14
FAST_FEEDBACK_BUDGET_PCT = 0.26
LONG_DATED_HIGH_CONVICTION_BUDGET_PCT = 0.18

SOURCE_WEIGHTS = {
    "market_native": 1.00,
    "official": 0.95,
    "forecasting": 0.82,
    "reputable_media": 0.68,
    "crowd": 0.42,
    "heuristic": 0.30,
}

CATEGORY_KEYWORDS = {
    "politics": ["president", "election", "prime minister", "congress", "senate", "vote", "campaign", "trump", "biden", "orban"],
    "crypto": ["bitcoin", "btc", "eth", "ethereum", "solana", "crypto", "token", "sec", "etf"],
    "macro": ["inflation", "fed", "rates", "gdp", "recession", "cpi", "macro", "oil"],
    "tech": ["openai", "google", "apple", "microsoft", "meta", "ai", "launch", "product", "gpt"],
    "celebrities": ["rihanna", "kanye", "celebrity", "album", "movie", "actor", "singer"],
    "regulatory": ["approval", "ban", "lawsuit", "regulation", "sec", "court", "judge", "legal"],
    "courts_law": ["court", "judge", "lawsuit", "trial", "ruling", "legal"],
    "elections": ["election", "primary", "vote", "wins state", "electoral"],
    "product_launches": ["launch", "release", "ship", "announce", "product", "gta", "tesla"],
    "war_geopolitics": ["war", "ukraine", "russia", "china", "israel", "gaza", "attack", "ceasefire"],
    "weird_impossible": ["second coming", "jesus", "alien", "zombie", "apocalypse", "asteroid", "flat earth"],
    "deadlines": ["before", "by ", "this year", "by end", "deadline", "before gta"],
}

SPORTS_FILTER = [
    "soccer", "football", "nfl", "nba", "nhl", "mlb", "basketball", "tennis", "golf", "cricket",
    "rugby", "f1 race", "racing", "olympics", "world cup", "fifa", "premier league", "bundesliga",
    "ligue 1", "la liga", "ucl", "ufc", "boxing", "wrestling", "nascar", "formula 1", "grand prix",
    "playoff", "serie a", "champions league", "europa league",
]

BETS_SCHEMA = {
    "id": "TEXT PRIMARY KEY",
    "question": "TEXT",
    "market_id": "TEXT",
    "side": "TEXT",
    "amount": "REAL",
    "prob_market": "REAL",
    "prob_claude": "REAL",
    "edge": "REAL",
    "confidence": "INTEGER",
    "kelly_f": "REAL",
    "status": "TEXT DEFAULT 'open'",
    "pnl": "REAL DEFAULT 0",
    "reasoning": "TEXT",
    "sources_used": "TEXT",
    "price_entry": "REAL",
    "price_current": "REAL",
    "peak_return": "REAL DEFAULT 0",
    "take_profit_hit": "BOOLEAN DEFAULT FALSE",
    "stop_loss_hit": "BOOLEAN DEFAULT FALSE",
    "category": "TEXT",
    "thesis_type": "TEXT",
    "mispricing_type": "TEXT",
    "trade_class": "TEXT DEFAULT 'core'",
    "tier": "TEXT DEFAULT 'TIER_C'",
    "selection_bucket": "TEXT DEFAULT 'selected_now'",
    "horizon_bucket": "TEXT DEFAULT 'medium'",
    "strategy_version": "TEXT DEFAULT 'legacy'",
    "lab_epoch": "TEXT DEFAULT 'legacy'",
    "active_lab": "BOOLEAN DEFAULT TRUE",
    "source_quality_score": "REAL DEFAULT 0",
    "source_diversity_score": "REAL DEFAULT 0",
    "factual_strength": "REAL DEFAULT 0",
    "chatter_dependency": "REAL DEFAULT 0",
    "evidence_strength": "REAL DEFAULT 0",
    "composite_score": "REAL DEFAULT 0",
    "mispricing_score": "REAL DEFAULT 0",
    "opportunity_score": "REAL DEFAULT 0",
    "portfolio_priority_score": "REAL DEFAULT 0",
    "ease_of_win_score": "REAL DEFAULT 0",
    "market_quality_score": "REAL DEFAULT 0",
    "liquidity_score": "REAL DEFAULT 0",
    "spread_penalty": "REAL DEFAULT 0",
    "capital_efficiency_score": "REAL DEFAULT 0",
    "historical_pattern_score": "REAL DEFAULT 0",
    "learning_velocity_score": "REAL DEFAULT 0",
    "market_learnability_score": "REAL DEFAULT 0",
    "conclusion_reliability_score": "REAL DEFAULT 0",
    "recommendation_strength": "REAL DEFAULT 0",
    "market_quality": "TEXT",
    "obvious_enough_to_take": "BOOLEAN DEFAULT FALSE",
    "external_match_confidence": "REAL DEFAULT 0",
    "microstructure_quality_score": "REAL DEFAULT 0",
    "recommended_aggression": "TEXT",
    "what_must_be_true": "TEXT",
    "what_would_invalidate_the_trade": "TEXT",
    "main_risks": "TEXT",
    "invalidation_condition": "TEXT",
    "key_signal": "TEXT",
    "research_packet": "TEXT",
    "analysis_json": "TEXT",
    "research_summary_hash": "TEXT",
    "portfolio_cycle_id": "TEXT",
    "evidence_count": "INTEGER DEFAULT 0",
    "contradictions_found": "INTEGER DEFAULT 0",
    "recency_score": "REAL DEFAULT 0",
    "uncertainty_score": "REAL DEFAULT 0",
    "missing_data_flags": "TEXT",
    "market_prob_bucket": "TEXT",
    "confidence_bucket": "TEXT",
    "edge_bucket": "TEXT",
    "time_to_resolution_hours": "REAL DEFAULT 0",
    "feedback_time_bucket": "TEXT",
    "resolved_reason": "TEXT",
    "created_at": "TIMESTAMPTZ DEFAULT NOW()",
    "resolved_at": "TIMESTAMPTZ",
}

STATE_DEFAULTS = {
    "balance": str(DEFAULT_BALANCE),
    "won": "0",
    "lost": "0",
    "bets_placed": "0",
    "total_edge": "0",
    "cycles_run": "0",
    "markets_analyzed_last_cycle": "0",
    "discarded_low_evidence_last_cycle": "0",
    "discarded_correlation_last_cycle": "0",
    "passed_to_portfolio_last_cycle": "0",
    "watchlist_last_cycle": "0",
    "selected_secondary_last_cycle": "0",
    "selected_core_last_cycle": "0",
    "selected_exploratory_last_cycle": "0",
    "current_lab_epoch": "lab-1",
    "current_strategy_version": CURRENT_STRATEGY_VERSION,
    "paper_starting_balance": str(DEFAULT_BALANCE),
    "lab_resets": "0",
}

BACKGROUND_LOOPS_LOCK = threading.Lock()
BACKGROUND_LOOPS_STARTED = False
LAST_CYCLE_DATA = {
    "cycle_id": None,
    "candidates": [],
    "shortlist": [],
    "selected": [],
    "watchlist": [],
    "rejected": [],
    "summary": {},
    "blockers": {},
}


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(DATABASE_URL)


def ensure_table_columns(cur, table_name, schema):
    columns_sql = ", ".join(f"{name} {definition}" for name, definition in schema.items())
    cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})")
    for column_name, definition in schema.items():
        if "PRIMARY KEY" in definition.upper():
            continue
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {definition}")


def init_db():
    if not DATABASE_URL:
        logger.warning("DATABASE_URL missing; DB initialization skipped")
        return False
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                ensure_table_columns(cur, "bets", BETS_SCHEMA)
                cur.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
                for key, value in STATE_DEFAULTS.items():
                    cur.execute("INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", (key, value))
                cur.execute("UPDATE bets SET strategy_version=COALESCE(strategy_version, 'legacy')")
                cur.execute("UPDATE bets SET lab_epoch=COALESCE(lab_epoch, 'legacy')")
                cur.execute("UPDATE bets SET active_lab=COALESCE(active_lab, TRUE)")
                cur.execute("UPDATE bets SET active_lab=FALSE WHERE lab_epoch='legacy'")
                cur.execute("UPDATE bets SET selection_bucket=COALESCE(selection_bucket, 'legacy_archive') WHERE lab_epoch='legacy'")
        return True
    except psycopg2.Error:
        logger.exception("DB initialization failed")
        return False


def get_state(key, default=0.0):
    if not DATABASE_URL:
        return default
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM state WHERE key=%s", (key,))
                row = cur.fetchone()
        return float(row[0]) if row else default
    except (psycopg2.Error, TypeError, ValueError):
        logger.exception("Failed to read state key=%s", key)
        return default


def get_state_text(key, default=""):
    if not DATABASE_URL:
        return default
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM state WHERE key=%s", (key,))
                row = cur.fetchone()
        return str(row[0]) if row and row[0] is not None else default
    except psycopg2.Error:
        logger.exception("Failed to read text state key=%s", key)
        return default


def set_state(key, value):
    if not DATABASE_URL:
        return False
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                    (key, str(value)),
                )
        return True
    except psycopg2.Error:
        logger.exception("Failed to set state key=%s", key)
        return False


def get_current_lab_epoch():
    return get_state_text("current_lab_epoch", "lab-1")


def get_current_strategy_version():
    return get_state_text("current_strategy_version", CURRENT_STRATEGY_VERSION)


def get_paper_starting_balance():
    return safe_float(get_state("paper_starting_balance", DEFAULT_BALANCE), DEFAULT_BALANCE)


def get_all_bets(active_lab_only=False, include_legacy=True, lab_epoch=None):
    if not DATABASE_URL:
        return []
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                filters = []
                params = []
                if active_lab_only:
                    filters.append("COALESCE(active_lab, TRUE)=TRUE")
                if not include_legacy:
                    filters.append("(lab_epoch=%s OR COALESCE(active_lab, TRUE)=TRUE)")
                    params.append(get_current_lab_epoch())
                if lab_epoch is not None:
                    filters.append("lab_epoch=%s")
                    params.append(lab_epoch)
                where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
                cur.execute(f"SELECT * FROM bets {where_clause} ORDER BY created_at DESC, id DESC", params)
                rows = cur.fetchall()
        return [dict(row) for row in rows]
    except psycopg2.Error:
        logger.exception("Failed to fetch bets")
        return []


def save_bet(bet):
    if not DATABASE_URL:
        return False
    columns = list(BETS_SCHEMA.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join([f"{column}=EXCLUDED.{column}" for column in columns if column != "id" and column != "created_at"])
    values = [bet.get(column) for column in columns]
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO bets ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {updates}",
                    values,
                )
        return True
    except psycopg2.Error:
        logger.exception("Failed to save bet id=%s", bet.get("id"))
        return False


def update_bet_fields(bet_id, fields):
    if not DATABASE_URL or not fields:
        return False
    try:
        assignments = []
        values = []
        for key, value in fields.items():
            assignments.append(f"{key}=%s")
            values.append(value)
        values.append(bet_id)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE bets SET {', '.join(assignments)} WHERE id=%s", values)
        return True
    except psycopg2.Error:
        logger.exception("Failed to update bet id=%s", bet_id)
        return False


def next_lab_epoch():
    return f"lab-{int(get_state('lab_resets', 0)) + 2}"


def archive_lab_epoch(lab_epoch, archive_open=True):
    if not DATABASE_URL:
        return {"archived_total": 0, "archived_open": 0, "refund": 0.0}
    bets = get_all_bets(lab_epoch=lab_epoch)
    open_bets = [bet for bet in bets if bet.get("status") == "open"]
    refund = round(sum(safe_float(bet.get("amount"), 0.0) for bet in open_bets), 2) if archive_open else 0.0
    status_sql = "CASE WHEN status='open' THEN 'lab_reset_archived' ELSE status END" if archive_open else "status"
    resolved_reason_sql = "CASE WHEN status='open' THEN 'lab_reset_archive' ELSE resolved_reason END" if archive_open else "resolved_reason"
    resolved_at_sql = "CASE WHEN status='open' THEN NOW() ELSE resolved_at END" if archive_open else "resolved_at"
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE bets
                    SET active_lab=FALSE,
                        selection_bucket='legacy_archive',
                        status={status_sql},
                        resolved_reason={resolved_reason_sql},
                        resolved_at={resolved_at_sql}
                    WHERE lab_epoch=%s
                    """,
                    (lab_epoch,),
                )
        return {"archived_total": len(bets), "archived_open": len(open_bets), "refund": refund}
    except psycopg2.Error:
        logger.exception("Failed to archive lab epoch=%s", lab_epoch)
        raise


def reset_lab_state(new_epoch=None, balance=None):
    target_epoch = new_epoch or next_lab_epoch()
    target_balance = round(balance if balance is not None else get_paper_starting_balance(), 2)
    if balance is not None:
        set_state("paper_starting_balance", target_balance)
    set_state("balance", target_balance)
    set_state("won", 0)
    set_state("lost", 0)
    set_state("bets_placed", 0)
    set_state("total_edge", 0)
    set_state("cycles_run", 0)
    set_state("markets_analyzed_last_cycle", 0)
    set_state("discarded_low_evidence_last_cycle", 0)
    set_state("discarded_correlation_last_cycle", 0)
    set_state("passed_to_portfolio_last_cycle", 0)
    set_state("watchlist_last_cycle", 0)
    set_state("selected_core_last_cycle", 0)
    set_state("selected_secondary_last_cycle", 0)
    set_state("selected_exploratory_last_cycle", 0)
    set_state("current_lab_epoch", target_epoch)
    set_state("current_strategy_version", CURRENT_STRATEGY_VERSION)
    set_state("lab_resets", int(get_state("lab_resets", 0)) + 1)
    LAST_CYCLE_DATA["cycle_id"] = None
    LAST_CYCLE_DATA["candidates"] = []
    LAST_CYCLE_DATA["shortlist"] = []
    LAST_CYCLE_DATA["selected"] = []
    LAST_CYCLE_DATA["watchlist"] = []
    LAST_CYCLE_DATA["rejected"] = []
    return {"lab_epoch": target_epoch, "balance": target_balance}


def archive_current_lab_and_reset(balance=None):
    old_epoch = get_current_lab_epoch()
    archive_result = archive_lab_epoch(old_epoch, archive_open=True)
    reset_result = reset_lab_state(balance=balance)
    return {**archive_result, **reset_result, "previous_lab_epoch": old_epoch}


def build_cycle_summary(analyzed_count, shortlist_count, selected, watchlist, rejected):
    core_count = sum(1 for item in selected if item.get("trade_class") == "core")
    secondary_count = sum(1 for item in selected if item.get("trade_class") == "secondary")
    exploratory_count = sum(1 for item in selected if item.get("trade_class") == "experimental")
    reason_counts = Counter(reason for _, reason in rejected)
    top_blockers = dict(reason_counts.most_common(6))
    if selected:
        headline = f"Se agregaron {len(selected)} trades: {core_count} core, {secondary_count} secondary y {exploratory_count} exploratory."
    elif watchlist:
        top_reason = next(iter(top_blockers), "prioridad insuficiente")
        headline = f"Analizó {analyzed_count} mercados. Encontró {len(watchlist)} oportunidades en watchlist, pero no hubo entradas por {top_reason}."
    elif shortlist_count:
        top_reason = next(iter(top_blockers), "falta de edge claro")
        headline = f"Analizó {analyzed_count} mercados. {shortlist_count} pasaron el filtro inicial, pero ninguno alcanzó prioridad suficiente para entrar."
        if top_reason not in ("low_score",):
            headline = f"{headline[:-1]} Motivo principal: {top_reason}."
    else:
        headline = f"Analizó {analyzed_count} mercados y no encontró candidatos suficientemente fuertes para pasar el filtro inicial."
    return {
        "headline": headline,
        "analyzed": analyzed_count,
        "shortlist": shortlist_count,
        "selected": len(selected),
        "watchlist": len(watchlist),
        "rejected": len(rejected),
        "core_selected": core_count,
        "secondary_selected": secondary_count,
        "exploratory_selected": exploratory_count,
        "blockers": top_blockers,
    }


init_db()

# ── GENERAL HELPERS ──────────────────────────────────────────
def clamp(value, low, high):
    return max(low, min(high, value))


def safe_json_loads(value, default=None):
    if value in (None, ""):
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if default is None else default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values, default=0.0):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else default


def parse_market_prices(market):
    prices = market.get("outcomePrices", "")
    if isinstance(prices, str):
        prices = json.loads(prices)
    return prices


def get_yes_probability(market):
    prices = parse_market_prices(market)
    if not prices:
        raise ValueError("Missing outcomePrices")
    return safe_float(prices[0])


def normalize_question(question):
    return re.sub(r"\s+", " ", (question or "").strip())


def keyword_tokens(text):
    return [token for token in re.findall(r"[a-zA-Z0-9]+", (text or "").lower()) if len(token) > 3]


def top_overlap_terms(text_a, text_b):
    return sorted(set(keyword_tokens(text_a)) & set(keyword_tokens(text_b)))


def hash_text(text):
    return hashlib.sha1((text or "").strip().lower().encode("utf-8")).hexdigest()


def extract_market_semantics(question):
    normalized = normalize_question(question)
    lowered = normalized.lower()
    tokens = keyword_tokens(normalized)
    deadline = None
    date_match = re.search(r"(20\d{2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", lowered)
    if "before" in lowered or "by " in lowered or "deadline" in lowered:
        deadline = date_match.group(0) if date_match else "implicit_deadline"
    subject = " ".join(tokens[:3]) if tokens else normalized[:40]
    region = next((token for token in tokens if token in {"usa", "us", "china", "russia", "ukraine", "hungary", "europe", "israel"}), "")
    resolution_type = (
        "deadline"
        if deadline
        else "election"
        if detect_category(normalized) == "elections"
        else "legal"
        if detect_category(normalized) in ("regulatory", "courts_law")
        else "launch"
        if detect_category(normalized) == "product_launches"
        else "binary"
    )
    event = " ".join(tokens[1:5]) if len(tokens) > 1 else normalized[:60]
    return {
        "normalized_question": normalized,
        "subject": subject,
        "event": event,
        "deadline": deadline,
        "region": region,
        "resolution_type": resolution_type,
        "keywords": tokens[:10],
    }


def iso_to_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def hours_between(start, end):
    if not start or not end:
        return 0.0
    return round((end - start).total_seconds() / 3600, 2)


def bucket_probability(prob):
    if prob < 0.2:
        return "0-20%"
    if prob < 0.4:
        return "20-40%"
    if prob < 0.6:
        return "40-60%"
    if prob < 0.8:
        return "60-80%"
    return "80-100%"


def bucket_confidence(confidence):
    if confidence <= 4:
        return "low"
    if confidence <= 7:
        return "medium"
    return "high"


def bucket_edge(edge):
    if edge < 0.05:
        return "tiny"
    if edge < 0.10:
        return "small"
    if edge < 0.18:
        return "medium"
    return "large"


def bucket_time_to_feedback(hours):
    days = hours / 24 if hours is not None else 999
    if days <= 3:
        return "0-3d"
    if days <= 7:
        return "3-7d"
    if days <= 21:
        return "1-3w"
    if days <= 45:
        return "3-6w"
    return "6w+"


def detect_category(question):
    lowered = (question or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "general"


def detect_thesis_type(question, market_prob, packet):
    lowered = (question or "").lower()
    if packet.get("external_forecast_divergence", 0) > 0.10:
        return "external forecast divergence"
    if packet.get("microstructure_dislocation_score", 0) > 0.60:
        return "microstructure dislocation"
    if "before" in lowered or detect_category(question) == "deadlines":
        return "timeline too aggressive"
    if detect_category(question) == "weird_impossible":
        return "impossible event mispricing"
    if market_prob >= 0.70:
        return "overpriced optimism"
    if market_prob <= 0.30:
        return "overpriced doom"
    if abs(packet.get("crowd_signal_score", 0)) > 0.55 and packet.get("contradictions_found", 0) > 0:
        return "crowd narrative overshoot"
    return "information asymmetry"


def detect_mispricing_patterns(question, market_prob, packet):
    lowered = (question or "").lower()
    patterns = []
    if market_prob >= 0.72:
        patterns.append("overpriced optimism")
    if market_prob <= 0.28:
        patterns.append("overpriced doom")
    if packet.get("category") == "weird_impossible":
        patterns.append("event improbability mispricing")
    if packet.get("resolution_type") == "deadline" and market_prob >= 0.58:
        patterns.append("timeline too aggressive")
    if packet.get("resolution_type") == "deadline" and market_prob <= 0.35:
        patterns.append("timeline too conservative")
    if packet.get("hype_narrative_overshoot_flag"):
        patterns.append("narrative overshoot")
    if packet.get("external_forecast_divergence", 0) >= 0.10 and packet.get("external_match_confidence", 0) >= 0.5:
        patterns.append("external forecast divergence")
    if packet.get("cluster_divergence", 0) >= 0.10:
        patterns.append("related-market inconsistency")
    if packet.get("microstructure_dislocation_score", 0) >= 0.55:
        patterns.append("orderbook/microstructure dislocation")
    if packet.get("source_quality_score", 0) < 0.45 and market_prob >= 0.65:
        patterns.append("low-information market priced too confidently")
    if packet.get("recency_score", 0) >= 0.8 and abs(packet.get("momentum_24h", 0)) < 0.01 and packet.get("factual_strength", 0) >= 0.40:
        patterns.append("stale pricing after relevant news")
    if packet.get("crowd_signal_score", 0) > 0.45 and packet.get("factual_strength", 0) < 0.35:
        patterns.append("crowd overreaction")
    if packet.get("category") in ("celebrities", "product_launches") and market_prob >= 0.65:
        patterns.append("celebrity / launch / release overpricing")
    if packet.get("category") in ("regulatory", "courts_law") and packet.get("external_forecast_divergence", 0) >= 0.08:
        patterns.append("regulatory / legal lag mispricing")
    if "weird" in lowered and "overpricing" not in patterns:
        patterns.append("weird market overpricing")
    return patterns or [packet.get("thesis_type", "information asymmetry")]


def compute_learning_velocity_score(packet):
    days_left = max(packet.get("days_left", 999), 1)
    time_component = clamp(1 - (days_left / 120.0), 0.0, 1.0)
    take_profit_component = clamp(abs(packet.get("momentum_24h", 0)) * 4 + packet.get("microstructure_dislocation_score", 0) * 0.5, 0.0, 1.0)
    invalidate_component = clamp((1 - packet.get("uncertainty_score", 0)) * 0.35 + packet.get("factual_strength", 0) * 0.35 + packet.get("recency_score", 0) * 0.30, 0.0, 1.0)
    score = time_component * 0.45 + take_profit_component * 0.25 + invalidate_component * 0.30
    return round(clamp(score, 0.0, 1.0), 4)


def compute_market_learnability_score(packet):
    clear_resolution = 1.0 if packet.get("resolution_type") in ("binary", "deadline", "election", "legal", "launch") else 0.6
    evidence_component = clamp(packet.get("factual_strength", 0) * 0.35 + packet.get("source_quality_score", 0) * 0.25 + packet.get("source_diversity_score", 0) * 0.15, 0.0, 1.0)
    learnability = clear_resolution * 0.35 + evidence_component * 0.35 + packet.get("learning_velocity_score", 0) * 0.30 - packet.get("chatter_dependency", 0) * 0.15 - packet.get("uncertainty_score", 0) * 0.20
    return round(clamp(learnability, 0.0, 1.0), 4)


def detect_market_supported(market, now_utc):
    if not market.get("active") or market.get("closed"):
        return False, None
    question = normalize_question(market.get("question", ""))
    tags = " ".join(tag.get("slug", "") for tag in market.get("tags", []))
    if any(term in (question + " " + tags).lower() for term in SPORTS_FILTER):
        return False, None
    prob = get_yes_probability(market)
    volume = safe_float(market.get("volume", 0))
    if not (MIN_MARKET_PROB < prob < MAX_MARKET_PROB):
        return False, None
    if volume < MIN_MARKET_VOLUME:
        return False, None
    end_date = iso_to_datetime(market.get("endDate", market.get("end_date", "")))
    if end_date:
        days_left = (end_date - now_utc).days
        if days_left > MAX_DAYS_TO_RESOLUTION or days_left < MIN_DAYS_TO_RESOLUTION:
            return False, None
        market["days_left"] = days_left
    else:
        market["days_left"] = MAX_DAYS_TO_RESOLUTION
    return True, prob


def fetch_active_markets(limit=MARKETS_FETCH_LIMIT):
    response = requests.get(f"{GAMMA_API}/markets?closed=false&limit={limit}", timeout=REQUEST_TIMEOUT)
    payload = response.json()
    return payload if isinstance(payload, list) else payload.get("markets", [])


def fetch_orderbook(market_id):
    try:
        response = requests.get(f"{CLOB_API}/book?token_id={market_id}", timeout=REQUEST_TIMEOUT)
        data = response.json()
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks:
            return {"spread": 1.0, "midpoint": 0.5, "best_bid": 0.0, "best_ask": 1.0, "last_trade_price": None, "orderbook_imbalance": 0.0, "bid_depth": 0.0, "ask_depth": 0.0, "liquidity_score": 0.0, "spread_quality_bucket": "poor", "smart_money": "none", "rare_flow": False}
        best_bid = safe_float(bids[0].get("price"))
        best_ask = safe_float(asks[0].get("price"), 1.0)
        midpoint = round((best_bid + best_ask) / 2, 4)
        bid_depth = sum(safe_float(bid.get("size")) for bid in bids[:5])
        ask_depth = sum(safe_float(ask.get("size")) for ask in asks[:5])
        total_depth = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / (total_depth + 1)
        top_bid = max((safe_float(bid.get("size")) for bid in bids[:3]), default=0.0)
        top_ask = max((safe_float(ask.get("size")) for ask in asks[:3]), default=0.0)
        smart_money = "buy" if top_bid > max(5000, top_ask * 1.8) else "sell" if top_ask > max(5000, top_bid * 1.8) else "none"
        rare_flow = abs(imbalance) > 0.45 or smart_money != "none"
        spread = round(max(0.0, best_ask - best_bid), 4)
        liquidity_score = clamp((bid_depth + ask_depth) / 30000.0, 0.0, 1.0)
        spread_quality_bucket = "tight" if spread <= 0.015 else "ok" if spread <= 0.03 else "wide" if spread <= 0.06 else "poor"
        return {
            "spread": spread,
            "midpoint": midpoint,
            "best_bid": round(best_bid, 4),
            "best_ask": round(best_ask, 4),
            "last_trade_price": midpoint,
            "orderbook_imbalance": round(imbalance, 4),
            "bid_depth": round(bid_depth, 2),
            "ask_depth": round(ask_depth, 2),
            "liquidity_score": round(liquidity_score, 4),
            "spread_quality_bucket": spread_quality_bucket,
            "smart_money": smart_money,
            "rare_flow": rare_flow,
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Orderbook fetch failed for market_id=%s", market_id)
        return {"spread": 1.0, "midpoint": 0.5, "best_bid": 0.0, "best_ask": 1.0, "last_trade_price": None, "orderbook_imbalance": 0.0, "bid_depth": 0.0, "ask_depth": 0.0, "liquidity_score": 0.0, "spread_quality_bucket": "poor", "smart_money": "none", "rare_flow": False}


def fetch_price_history(market_id):
    try:
        response = requests.get(f"{CLOB_API}/prices-history?market={market_id}&interval=1d&fidelity=1", timeout=REQUEST_TIMEOUT)
        history = response.json().get("history", [])
        intraday_response = requests.get(f"{CLOB_API}/prices-history?market={market_id}&interval=1h&fidelity=1", timeout=REQUEST_TIMEOUT)
        intraday_history = intraday_response.json().get("history", [])
        if len(history) < 2:
            return {"current_price": None, "momentum_1h": 0.0, "momentum_24h": 0.0, "momentum_7d": 0.0, "realized_drift": 0.0, "volatility_proxy": 0.0, "unusual_movement": False}
        current = safe_float(history[-1].get("p"))
        day_ago = safe_float(history[-2].get("p"), current)
        week_ago = safe_float(history[-7].get("p"), history[0].get("p", current)) if len(history) >= 7 else safe_float(history[0].get("p"), current)
        hour_ago = safe_float(intraday_history[-2].get("p"), current) if len(intraday_history) >= 2 else day_ago
        momentum_24h = current - day_ago
        momentum_7d = current - week_ago
        momentum_1h = current - hour_ago
        realized_drift = mean([safe_float(point.get("p")) for point in history[-5:]], current) - safe_float(history[0].get("p"), current)
        returns = []
        for prev, nxt in zip(history[-8:-1], history[-7:]):
            prev_price = safe_float(prev.get("p"), current)
            nxt_price = safe_float(nxt.get("p"), current)
            if prev_price:
                returns.append(abs((nxt_price - prev_price) / prev_price))
        volatility_proxy = mean(returns, 0.0)
        return {
            "current_price": current,
            "momentum_1h": round(momentum_1h, 4),
            "momentum_24h": round(momentum_24h, 4),
            "momentum_7d": round(momentum_7d, 4),
            "realized_drift": round(realized_drift, 4),
            "volatility_proxy": round(volatility_proxy, 4),
            "unusual_movement": abs(momentum_24h) > 0.08 or abs(momentum_1h) > 0.04,
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Price history fetch failed for market_id=%s", market_id)
        return {"current_price": None, "momentum_1h": 0.0, "momentum_24h": 0.0, "momentum_7d": 0.0, "realized_drift": 0.0, "volatility_proxy": 0.0, "unusual_movement": False}


def fetch_news_source(question):
    if not NEWS_API_KEY:
        return {"summary": "", "count": 0, "quality": SOURCE_WEIGHTS["reputable_media"], "recency_score": 0.0}
    try:
        query = " ".join(keyword_tokens(question)[:4]) or question
        date_from = (datetime.utcnow() - timedelta(days=21)).strftime("%Y-%m-%d")
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "pageSize": 5, "sortBy": "publishedAt", "language": "en", "from": date_from, "apiKey": NEWS_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        articles = response.json().get("articles", [])
        titles = [article.get("title") for article in articles if article.get("title")][:4]
        recency = 1.0 if titles else 0.0
        return {"summary": " | ".join(titles), "count": len(titles), "quality": SOURCE_WEIGHTS["reputable_media"], "recency_score": recency}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("News fetch failed for question=%s", question[:80])
        return {"summary": "", "count": 0, "quality": SOURCE_WEIGHTS["reputable_media"], "recency_score": 0.0}


def fetch_metaculus_source(question):
    if not METACULUS_API_KEY:
        return {"summary": "", "count": 0, "forecast": None, "quality": SOURCE_WEIGHTS["forecasting"]}
    try:
        query = " ".join(keyword_tokens(question)[:4]) or question
        response = requests.get(
            "https://www.metaculus.com/api2/questions/",
            params={"search": query, "status": "open", "limit": 5, "has_forecasts": "true"},
            headers={"Accept": "application/json", "Authorization": f"Token {METACULUS_API_KEY}"},
            timeout=REQUEST_TIMEOUT,
        )
        for item in response.json().get("results", []):
            latest = item.get("question", {}).get("aggregations", {}).get("recency_weighted", {}).get("latest", {})
            if isinstance(latest, dict) and latest.get("centers"):
                forecast = safe_float(latest["centers"][0])
                return {"summary": f"Metaculus: {item.get('title', '')[:60]} -> {round(forecast * 100)}%", "count": 1, "forecast": forecast, "quality": SOURCE_WEIGHTS["forecasting"]}
        return {"summary": "", "count": 0, "forecast": None, "quality": SOURCE_WEIGHTS["forecasting"]}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Metaculus fetch failed for question=%s", question[:80])
        return {"summary": "", "count": 0, "forecast": None, "quality": SOURCE_WEIGHTS["forecasting"]}


def fetch_wikipedia_source(question):
    try:
        query = " ".join(keyword_tokens(question)[:3]) or question
        response = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + query.replace(" ", "_"),
            headers={"User-Agent": "PolymarketBot/3.0"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return {"summary": "", "count": 0, "quality": SOURCE_WEIGHTS["official"]}
        extract = response.json().get("extract", "")
        return {"summary": extract[:260], "count": 1 if extract else 0, "quality": SOURCE_WEIGHTS["official"]}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Wikipedia fetch failed for question=%s", question[:80])
        return {"summary": "", "count": 0, "quality": SOURCE_WEIGHTS["official"]}


def fetch_reddit_source(question):
    try:
        query = " ".join(keyword_tokens(question)[:4]) or question
        response = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "sort": "new", "limit": 8, "t": "week"},
            headers={"User-Agent": "PolymarketBot/3.0"},
            timeout=REQUEST_TIMEOUT,
        )
        posts = response.json().get("data", {}).get("children", [])
        if not posts:
            return {"summary": "", "count": 0, "score": 0.0, "quality": SOURCE_WEIGHTS["crowd"]}
        titles = [post["data"].get("title", "") for post in posts[:4]]
        avg_score = mean([safe_float(post["data"].get("score")) for post in posts[:4]])
        crowd_score = clamp(avg_score / 30.0, -1.0, 1.0)
        return {"summary": " | ".join(titles), "count": len(titles), "score": crowd_score, "quality": SOURCE_WEIGHTS["crowd"]}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Reddit fetch failed for question=%s", question[:80])
        return {"summary": "", "count": 0, "score": 0.0, "quality": SOURCE_WEIGHTS["crowd"]}

# ── MEMORY / RESEARCH ENGINE ─────────────────────────────────
def get_current_lab_bets():
    current_lab_epoch = get_current_lab_epoch()
    return [bet for bet in get_all_bets(lab_epoch=current_lab_epoch) if bool(bet.get("active_lab", True))]


def get_legacy_bets():
    return [bet for bet in get_all_bets() if bet.get("lab_epoch") != get_current_lab_epoch() or not bool(bet.get("active_lab", True))]


def get_open_bets(bets=None):
    bets = bets if bets is not None else get_current_lab_bets()
    current_lab_epoch = get_current_lab_epoch()
    return [
        bet for bet in bets
        if bet.get("status") == "open"
        and bet.get("lab_epoch", current_lab_epoch) == current_lab_epoch
        and bool(bet.get("active_lab", True))
    ]


def compute_current_side_price(side, yes_price):
    return yes_price if side == "SI" else 1 - yes_price


def estimate_unrealized_pnl(bet):
    if bet.get("status") != "open":
        return 0.0
    entry_cost = compute_current_side_price(bet.get("side", "SI"), safe_float(bet.get("price_entry"), 0.5))
    current_cost = compute_current_side_price(bet.get("side", "SI"), safe_float(bet.get("price_current"), safe_float(bet.get("price_entry"), 0.5)))
    if entry_cost <= 0:
        return 0.0
    shares = safe_float(bet.get("amount"), 0.0) / entry_cost
    current_value = shares * current_cost
    return round(current_value - safe_float(bet.get("amount"), 0.0), 2)


def build_historical_analogs(question, category, thesis_type, all_bets):
    resolved = [bet for bet in all_bets if bet.get("status") in ("won", "lost")]
    analogs = [bet for bet in resolved if bet.get("category") == category or bet.get("thesis_type") == thesis_type]
    analogs = sorted(analogs, key=lambda bet: bet.get("created_at") or datetime.min.replace(tzinfo=timezone.utc))[-5:]
    if not analogs:
        return "Sin análogos previos"
    snippets = []
    for bet in analogs:
        snippets.append(f"{bet.get('status')} {bet.get('thesis_type', '?')} {round((bet.get('edge') or 0) * 100, 1)}pp")
    return " | ".join(snippets[:4])


def historical_bias_for_setup(category, thesis_type, trade_class, all_bets):
    resolved = [bet for bet in all_bets if bet.get("status") in ("won", "lost")]
    matching = [
        bet for bet in resolved
        if bet.get("category") == category or bet.get("thesis_type") == thesis_type or bet.get("trade_class") == trade_class
    ]
    if len(matching) < 3:
        return {"bias": 0.0, "winrate": None, "pnl_per_trade": 0.0, "sample": len(matching)}
    wins = sum(1 for bet in matching if bet.get("status") == "won")
    winrate = wins / len(matching)
    pnl_per_trade = mean([safe_float(bet.get("pnl"), 0.0) for bet in matching])
    bias = clamp((winrate - 0.5) * 0.5 + clamp(pnl_per_trade / 150.0, -0.2, 0.2), -0.25, 0.25)
    return {"bias": round(bias, 4), "winrate": round(winrate, 3), "pnl_per_trade": round(pnl_per_trade, 2), "sample": len(matching)}


def summarize_related_markets(base_market, markets):
    base_question = normalize_question(base_market.get("question", ""))
    category = detect_category(base_question)
    related = []
    for market in markets:
        if market.get("id") == base_market.get("id"):
            continue
        question = normalize_question(market.get("question", ""))
        overlap = top_overlap_terms(base_question, question)
        if detect_category(question) == category or len(overlap) >= 2:
            try:
                prob = get_yes_probability(market)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            related.append({"question": question[:70], "prob": prob, "overlap": overlap})
    related = sorted(related, key=lambda item: len(item["overlap"]), reverse=True)[:4]
    summary = " | ".join([f"{item['question']} ({round(item['prob'] * 100)}%)" for item in related])
    cluster_divergence = max([abs(item["prob"] - get_yes_probability(base_market)) for item in related], default=0.0)
    return summary or "Sin mercados claramente relacionados", round(cluster_divergence, 4)


def detect_contradictions(packet):
    contradictions = []
    if packet.get("external_forecast_prob") is not None and abs(packet["external_forecast_prob"] - packet["market_prob"]) > 0.10:
        contradictions.append("forecast_vs_market")
    if packet.get("crowd_signal_score", 0) > 0.35 and packet.get("momentum_24h", 0) < -0.04:
        contradictions.append("crowd_vs_price")
    if packet.get("orderbook_imbalance", 0) > 0.30 and packet.get("momentum_24h", 0) < -0.04:
        contradictions.append("orderbook_vs_price")
    if packet.get("spread", 1.0) > 0.05 and packet.get("source_quality_score", 0) < 0.45:
        contradictions.append("wide_spread_low_quality")
    return contradictions


def compute_source_diversity_score(news, metaculus, wiki, reddit):
    active_sources = sum(1 for source in (news, metaculus, wiki, reddit) if source.get("count"))
    return round(clamp(active_sources / 4.0, 0.0, 1.0), 4)


def build_missing_data_flags(packet):
    flags = []
    if packet.get("external_forecast_prob") is None:
        flags.append("no_external_forecast")
    if packet.get("factual_news_source") == "none":
        flags.append("no_factual_news")
    if packet.get("crowd_signal_summary") == "Sin crowd chatter relevante":
        flags.append("no_crowd_signal")
    if packet.get("bid_depth", 0) <= 0 or packet.get("ask_depth", 0) <= 0:
        flags.append("missing_orderbook_depth")
    if packet.get("current_price") is None:
        flags.append("missing_price_history")
    return flags


def build_contradiction_flags(packet):
    contradictions = detect_contradictions(packet)
    return {
        "contradictions": contradictions,
        "forecast_divergence_flag": "forecast_vs_market" in contradictions,
        "news_market_disagreement_flag": "crowd_vs_price" in contradictions or "orderbook_vs_price" in contradictions,
        "low_quality_evidence_flag": packet.get("source_quality_score", 0) < 0.45,
        "high_chatter_low_fact_flag": packet.get("chatter_dependency", 0) > 0.55 and packet.get("factual_strength", 0) < 0.35,
        "ambiguous_external_match_flag": packet.get("external_match_confidence", 0) < 0.45 and packet.get("external_forecast_prob") is not None,
        "microstructure_anomaly_flag": packet.get("microstructure_quality_score", 0) < 0.40 or packet.get("rare_flow", False),
    }


def compute_conclusion_reliability(packet, analysis_confidence=5.0):
    score = (
        packet.get("source_quality_score", 0.0) * 0.24
        + packet.get("source_diversity_score", 0.0) * 0.10
        + packet.get("factual_strength", 0.0) * 0.14
        + packet.get("final_evidence_strength", 0.0) * 0.18
        + packet.get("recency_score", 0.0) * 0.08
        + packet.get("external_match_confidence", 0.0) * 0.10
        + packet.get("microstructure_quality_score", 0.0) * 0.08
        + clamp(analysis_confidence / 10.0, 0.0, 1.0) * 0.10
        - packet.get("uncertainty_score", 0.0) * 0.14
        - min(packet.get("contradictions_found", 0), 4) * 0.05
        - min(len(packet.get("missing_data_flags", [])), 4) * 0.04
    )
    return round(clamp(score, 0.0, 1.0), 4)


def classify_horizon_bucket(days_left):
    if days_left <= 3:
        return "ultra_short"
    if days_left <= 14:
        return "short"
    if days_left <= 60:
        return "medium"
    return "long"


def compute_ease_of_win_score(packet, analysis, reliability, historical_bias):
    score = (
        reliability * 0.26
        + analysis.get("evidence_strength", 0.0) * 0.18
        + analysis.get("source_quality_score", 0.0) * 0.12
        + packet.get("factual_strength", 0.0) * 0.10
        + packet.get("market_learnability_score", 0.0) * 0.10
        + packet.get("microstructure_quality_score", 0.0) * 0.08
        + packet.get("external_match_confidence", 0.0) * 0.06
        + clamp(historical_bias, -0.25, 0.25) * 0.60
        - packet.get("uncertainty_score", 0.0) * 0.18
        - min(packet.get("contradictions_found", 0), 4) * 0.045
        - packet.get("chatter_dependency", 0.0) * 0.10
    )
    return round(clamp(score, 0.0, 1.0), 4)


def compute_capital_efficiency_score(candidate):
    packet = candidate["packet"]
    horizon_bucket = candidate.get("horizon_bucket") or classify_horizon_bucket(packet.get("days_left", 999))
    horizon_bonus = {"ultra_short": 0.22, "short": 0.16, "medium": 0.08, "long": -0.05}.get(horizon_bucket, 0.0)
    score = (
        candidate.get("learning_velocity_score", 0.0) * 0.28
        + candidate.get("ease_of_win_score", 0.0) * 0.20
        + candidate.get("opportunity_score", 0.0) * 0.22
        + candidate.get("market_learnability_score", 0.0) * 0.15
        + horizon_bonus
        - candidate.get("correlation_penalty", 0.0) * 0.18
    )
    return round(clamp(score, 0.0, 1.0), 4)


def classify_trade_class(reliability, opportunity_score, learning_velocity_score, ease_of_win_score):
    if reliability >= 0.70 and opportunity_score >= 0.62 and ease_of_win_score >= 0.60:
        return "core"
    if reliability >= 0.42 and opportunity_score >= 0.42:
        return "secondary"
    if learning_velocity_score >= 0.35 or opportunity_score >= 0.36:
        return "experimental"
    return "skip"


def assign_candidate_tier(candidate):
    reliability = candidate.get("conclusion_reliability_score", 0.0)
    opportunity = candidate.get("opportunity_score", 0.0)
    ease_of_win = candidate.get("ease_of_win_score", 0.0)
    learning_velocity = candidate.get("learning_velocity_score", 0.0)
    score = candidate.get("portfolio_priority_score", candidate.get("compound_score", 0.0))
    if score >= TIER_A_SCORE_FLOOR and reliability >= 0.68 and ease_of_win >= 0.58:
        return "TIER_A"
    if score >= TIER_B_SCORE_FLOOR and reliability >= 0.48 and opportunity >= 0.44:
        return "TIER_B"
    if score >= TIER_C_SCORE_FLOOR and (learning_velocity >= 0.35 or opportunity >= 0.38):
        return "TIER_C"
    return "TIER_D"


def obvious_enough_to_take(candidate):
    return (
        candidate.get("edge", 0.0) >= 0.06 and (
            candidate.get("portfolio_priority_score", 0.0) >= OBVIOUS_ENOUGH_SCORE
            or candidate.get("learning_velocity_score", 0.0) >= 0.68
            or candidate.get("ease_of_win_score", 0.0) >= 0.70
            or (
                candidate.get("mispricing_score", 0.0) >= 0.68
                and candidate.get("conclusion_reliability_score", 0.0) >= 0.45
            )
        )
    )


def build_research_packet(market, market_prob, all_markets, all_bets):
    semantics = extract_market_semantics(market.get("question", ""))
    question = semantics["normalized_question"]
    category = detect_category(question)
    price_data = fetch_price_history(market.get("id", ""))
    book_data = fetch_orderbook(market.get("id", ""))
    news = fetch_news_source(question)
    metaculus = fetch_metaculus_source(question)
    wiki = fetch_wikipedia_source(question)
    reddit = fetch_reddit_source(question)
    related_summary, cluster_divergence = summarize_related_markets(market, all_markets)
    forecast_divergence = abs((metaculus.get("forecast") or market_prob) - market_prob)
    thesis_type = detect_thesis_type(question, market_prob, {"external_forecast_divergence": forecast_divergence, "microstructure_dislocation_score": abs(book_data["orderbook_imbalance"]) + cluster_divergence, "crowd_signal_score": reddit.get("score", 0.0), "contradictions_found": 0})
    source_diversity_score = compute_source_diversity_score(news, metaculus, wiki, reddit)
    source_quality_score = clamp(mean([
        SOURCE_WEIGHTS["market_native"],
        news["quality"] if news["count"] else None,
        metaculus["quality"] if metaculus["count"] else None,
        wiki["quality"] if wiki["count"] else None,
        reddit["quality"] if reddit["count"] else None,
    ], 0.45), 0.0, 1.0)
    evidence_count = int(2 + news["count"] + metaculus["count"] + wiki["count"] + reddit["count"])
    recency_score = clamp(mean([news.get("recency_score"), 1.0 if abs(price_data["momentum_24h"]) > 0.02 else 0.5], 0.5), 0.0, 1.0)
    factual_strength = round(clamp(news["count"] * 0.12 + wiki["count"] * 0.18 + (0.18 if news.get("summary") else 0.0), 0.0, 1.0), 4)
    chatter_dependency = round(clamp((reddit["count"] * reddit["quality"]) / max(evidence_count, 1), 0.0, 1.0), 4)
    external_match_confidence = round(clamp((0.75 if metaculus.get("forecast") is not None else 0.0) + min(len(top_overlap_terms(question, metaculus.get("summary", ""))) * 0.05, 0.2), 0.0, 1.0), 4)
    microstructure_quality_score = round(clamp(book_data["liquidity_score"] * 0.45 + (1 - min(book_data["spread"], 0.08) / 0.08) * 0.30 + (1 - min(price_data["volatility_proxy"], 0.10) / 0.10) * 0.15 + (0.10 if not book_data["rare_flow"] else 0.0), 0.0, 1.0), 4)
    end_date = iso_to_datetime(market.get("endDate", market.get("end_date", "")))
    packet = {
        "market_id": market.get("id", ""),
        "market_question": question,
        "normalized_question": semantics["normalized_question"],
        "semantic_subject": semantics["subject"],
        "semantic_event": semantics["event"],
        "semantic_deadline": semantics["deadline"],
        "semantic_region": semantics["region"],
        "resolution_type": semantics["resolution_type"],
        "semantic_keywords": semantics["keywords"],
        "market_prob": round(market_prob, 4),
        "yes_price": round(market_prob, 4),
        "no_price": round(1 - market_prob, 4),
        "current_price": round(price_data["current_price"] if price_data["current_price"] is not None else market_prob, 4),
        "last_trade_price": book_data["last_trade_price"],
        "volume": round(safe_float(market.get("volume", 0)), 2),
        "liquidity_info": {"bid_depth": round(book_data["bid_depth"], 2), "ask_depth": round(book_data["ask_depth"], 2), "liquidity_score": book_data["liquidity_score"]},
        "spread": round(book_data["spread"], 4),
        "midpoint": round(book_data["midpoint"], 4),
        "best_bid": book_data["best_bid"],
        "best_ask": book_data["best_ask"],
        "orderbook_imbalance": round(book_data["orderbook_imbalance"], 4),
        "momentum_1h": round(price_data["momentum_1h"], 4),
        "momentum_24h": round(price_data["momentum_24h"], 4),
        "momentum_7d": round(price_data["momentum_7d"], 4),
        "realized_drift": round(price_data["realized_drift"], 4),
        "volatility_proxy": round(price_data["volatility_proxy"], 4),
        "unusual_movement_flags": ["sharp_intraday_move"] if price_data["unusual_movement"] else [],
        "spread_quality_bucket": book_data["spread_quality_bucket"],
        "related_markets_summary": related_summary,
        "topic_cluster": category,
        "external_forecast_summary": metaculus.get("summary") or "Sin forecast externo fuerte",
        "external_forecast_divergence": round(forecast_divergence, 4),
        "forecast_match_confidence": external_match_confidence,
        "external_match_confidence": external_match_confidence,
        "related_external_forecast_count": metaculus["count"],
        "factual_news_summary": (news.get("summary") or wiki.get("summary") or "Sin news factual fuerte")[:500],
        "factual_news_source": "news" if news.get("summary") else "wikipedia" if wiki.get("summary") else "none",
        "recent_news_headlines": news.get("summary", ""),
        "source_recency_distribution": {"news_recent": news.get("count", 0), "price_recent": 1 if price_data["unusual_movement"] else 0},
        "source_diversity_score": source_diversity_score,
        "official_source_hits": wiki["count"],
        "factual_strength": factual_strength,
        "crowd_signal_summary": reddit.get("summary") or "Sin crowd chatter relevante",
        "sentiment_bucket": "bullish" if reddit.get("score", 0) > 0.2 else "bearish" if reddit.get("score", 0) < -0.2 else "neutral",
        "hype_narrative_overshoot_flag": reddit.get("score", 0) > 0.45 and factual_strength < 0.35,
        "weak_signal_score": round(clamp(abs(reddit.get("score", 0.0)) * reddit["quality"], 0.0, 1.0), 4),
        "chatter_dependency": chatter_dependency,
        "source_quality_score": round(source_quality_score, 4),
        "evidence_count": evidence_count,
        "contradictions_found": 0,
        "recency_score": round(recency_score, 4),
        "uncertainty_score": 0.0,
        "market_native_weight": SOURCE_WEIGHTS["market_native"],
        "category": category,
        "historical_analogs_summary": build_historical_analogs(question, category, thesis_type, all_bets),
        "external_forecast_prob": metaculus.get("forecast"),
        "crowd_signal_score": round(reddit.get("score", 0.0), 4),
        "cluster_divergence": round(cluster_divergence, 4),
        "smart_money": book_data["smart_money"],
        "rare_flow": book_data["rare_flow"],
        "bid_depth": round(book_data["bid_depth"], 2),
        "ask_depth": round(book_data["ask_depth"], 2),
        "microstructure_dislocation_score": round(clamp(abs(book_data["orderbook_imbalance"]) + cluster_divergence - book_data["spread"], 0.0, 1.0), 4),
        "microstructure_quality_score": microstructure_quality_score,
        "thesis_type": thesis_type,
        "thesis_subtype_candidates": [thesis_type, "overreaction" if price_data["unusual_movement"] else "steady_state"],
        "time_to_resolution_hours": round(hours_between(datetime.now(timezone.utc), end_date), 2),
        "end_date": market.get("endDate", market.get("end_date", "")),
        "days_left": market.get("days_left", 0),
        "active": bool(market.get("active")),
        "closed": bool(market.get("closed")),
        "archived": bool(market.get("archived", False)),
    }
    contradiction_flags = build_contradiction_flags(packet)
    packet["contradictions_found"] = len(contradiction_flags["contradictions"])
    packet["contradiction_list"] = contradiction_flags["contradictions"]
    packet["contradiction_summary"] = ", ".join(contradiction_flags["contradictions"]) or "none"
    packet.update({key: value for key, value in contradiction_flags.items() if key != "contradictions"})
    packet["missing_data_flags"] = build_missing_data_flags(packet)
    packet["uncertainty_score"] = round(clamp(0.18 + (0.18 if packet["spread"] > 0.03 else 0) + packet["contradictions_found"] * 0.10 + len(packet["missing_data_flags"]) * 0.07 + (0.12 if packet["source_quality_score"] < 0.45 else 0) + (0.10 if packet["external_match_confidence"] < 0.45 and packet["external_forecast_prob"] is not None else 0), 0.0, 1.0), 4)
    packet["final_evidence_strength"] = round(clamp(packet["source_quality_score"] * 0.30 + packet["source_diversity_score"] * 0.12 + packet["factual_strength"] * 0.20 + packet["microstructure_quality_score"] * 0.12 + min(packet["evidence_count"], 8) * 0.03 + packet["recency_score"] * 0.08 - packet["uncertainty_score"] * 0.15 - packet["chatter_dependency"] * 0.08, 0.0, 1.0), 4)
    packet["mispricing_flags"] = detect_mispricing_patterns(question, market_prob, packet)
    packet["mispricing_score"] = round(clamp(len(packet["mispricing_flags"]) * 0.12 + packet["external_forecast_divergence"] * 1.1 + packet["microstructure_dislocation_score"] * 0.45 + packet["cluster_divergence"] * 0.8 + (0.10 if packet["hype_narrative_overshoot_flag"] else 0.0), 0.0, 1.0), 4)
    packet["learning_velocity_score"] = compute_learning_velocity_score(packet)
    packet["market_learnability_score"] = compute_market_learnability_score(packet)
    return packet


def extract_json_object(text):
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("JSON object not found")
    return json.loads(match.group())


def call_claude_json(model, prompt, max_tokens=400):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    text = response.json()["content"][0]["text"].strip()
    try:
        return extract_json_object(text)
    except ValueError:
        repair_prompt = f"Convierte esta salida a JSON válido sin cambiar meaning. Devuelve solo JSON.\n\n{text}"
        repair_response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 300, "messages": [{"role": "user", "content": repair_prompt}]},
            timeout=20,
        )
        repaired = repair_response.json()["content"][0]["text"].strip()
        return extract_json_object(repaired)


def heuristic_analysis(packet):
    market_prob = packet["market_prob"]
    external = packet.get("external_forecast_prob")
    forecast_anchor = external if external is not None else market_prob + packet.get("momentum_7d", 0) * 0.4 + packet.get("orderbook_imbalance", 0) * 0.12
    impossible_boost = -0.22 if packet["category"] == "weird_impossible" and market_prob > 0.35 else 0.0
    timeline_penalty = -0.08 if packet["thesis_type"] == "timeline too aggressive" and market_prob > 0.55 else 0.0
    micro_alpha = packet.get("microstructure_dislocation_score", 0) * (0.08 if packet.get("smart_money") == "buy" else -0.08 if packet.get("smart_money") == "sell" else 0.0)
    crowd_alpha = -packet.get("crowd_signal_score", 0) * 0.05 if packet["thesis_type"] == "crowd narrative overshoot" else packet.get("crowd_signal_score", 0) * 0.02
    real_prob = clamp((market_prob * 0.55) + (forecast_anchor * 0.30) + micro_alpha + crowd_alpha + impossible_boost + timeline_penalty, 0.02, 0.98)
    side = "SI" if real_prob > market_prob else "NO"
    confidence = int(round(clamp((packet["source_quality_score"] * 10) + (packet["evidence_count"] * 0.4) - (packet["uncertainty_score"] * 5), 3, 9)))
    external_divergence = abs(packet["external_forecast_prob"] - market_prob) * 0.8 if packet.get("external_forecast_prob") is not None else 0.0
    evidence_strength = round(
        clamp(
            0.20
            + packet["source_quality_score"] * 0.35
            + min(packet["evidence_count"], 8) * 0.04
            + external_divergence,
            0.0,
            1.0,
        ),
        4,
    )
    return {
        "real_prob": round(real_prob, 4),
        "side": side,
        "confidence": confidence,
        "thesis_type": packet["thesis_type"],
        "mispricing_type": packet["mispricing_flags"][0],
        "key_signal": packet["external_forecast_summary"] if packet.get("external_forecast_prob") is not None else packet["factual_news_summary"][:140],
        "market_quality": "high" if packet["microstructure_quality_score"] > 0.65 and packet["source_quality_score"] > 0.60 else "medium" if packet["source_quality_score"] > 0.40 else "low",
        "what_must_be_true": "La lectura de evidencia principal debe mantenerse hasta resolución",
        "what_would_invalidate_the_trade": "Nueva información oficial o giro fuerte de precios/flujo en contra",
        "main_risks": "Baja liquidez, narrativa equivocada o relación falsa entre señales",
        "source_quality_score": round(packet["source_quality_score"], 4),
        "evidence_strength": evidence_strength,
        "uncertainty_score": round(packet["uncertainty_score"], 4),
        "learning_velocity": packet["learning_velocity_score"],
        "market_learnability": packet["market_learnability_score"],
        "ease_of_win": round(clamp(packet["final_evidence_strength"] * 0.35 + packet["microstructure_quality_score"] * 0.15 + packet["source_quality_score"] * 0.20 + packet["market_learnability_score"] * 0.18 - packet["uncertainty_score"] * 0.18, 0.0, 1.0), 4),
        "market_horizon_bucket": classify_horizon_bucket(packet.get("days_left", 999)),
        "time_sensitivity": "alta" if packet["recency_score"] > 0.7 or abs(packet["momentum_24h"]) > 0.03 else "media",
        "recommended_aggression": "high" if confidence >= 8 and evidence_strength > 0.65 else "medium" if confidence >= 6 else "low",
        "short_reason": f"{packet['thesis_type']} con score de fuentes {round(packet['source_quality_score'] * 100)}%",
        "recommendation_strength": round(clamp(evidence_strength * 0.55 + packet["source_quality_score"] * 0.25 - packet["uncertainty_score"] * 0.20, 0.0, 1.0), 4),
        "core_vs_secondary_vs_exploratory": "core" if packet["learning_velocity_score"] >= 0.45 and packet["final_evidence_strength"] >= 0.55 else "secondary" if packet["final_evidence_strength"] >= 0.40 else "exploratory",
        "take_now_vs_watchlist": "take_now" if packet["final_evidence_strength"] >= 0.42 and packet["uncertainty_score"] <= 0.70 else "watchlist",
        "invalidation_condition": "Cambio factual relevante o price action que invalide la tesis en contra",
        "skip": packet["final_evidence_strength"] < 0.30 or packet["uncertainty_score"] > 0.75,
    }

# ── ANALYSIS / SCORING / PORTFOLIO ───────────────────────────
def get_performance_context():
    resolved = [bet for bet in get_current_lab_bets() if bet.get("status") in ("won", "lost")]
    if not resolved:
        return "Sin historial todavía. Priorizar evidencia fuerte, liquidez razonable y evitar narrativa sin respaldo."
    top_patterns = Counter([bet.get("thesis_type", "?") for bet in resolved if bet.get("status") == "won"]).most_common(3)
    weak_patterns = Counter([bet.get("thesis_type", "?") for bet in resolved if bet.get("status") == "lost"]).most_common(3)
    winrate = round(sum(1 for bet in resolved if bet.get("status") == "won") / len(resolved) * 100, 1)
    pnl = round(sum(safe_float(bet.get("pnl"), 0.0) for bet in resolved), 2)
    return f"Historial {len(resolved)} resueltas, win rate {winrate}%, PnL {pnl} USDC. Patrones fuertes: {top_patterns}. Patrones flojos: {weak_patterns}."


def fast_prefilter(candidates):
    if not candidates:
        return []
    ranked = sorted(candidates, key=lambda item: item["prefilter_score"], reverse=True)
    heuristic_top = ranked[:22]
    if not ANTHROPIC_API_KEY:
        return heuristic_top[:16]
    try:
        market_lines = "\n".join([f"{idx + 1}. {item['question']} | cat={item['packet']['category']} | vol={round(item['packet']['volume'])} | spread={round(item['packet']['spread'] * 100, 2)}% | mispricing={round(item['packet']['mispricing_score'] * 100)} | learn_vel={round(item['packet']['learning_velocity_score'] * 100)} | signal_q={round(item['packet']['source_quality_score'] * 100)}" for idx, item in enumerate(ranked[:28])])
        prompt = f"""Eres un prefilter de ideas para un portfolio de paper trading en Polymarket.
{get_performance_context()}
Selecciona hasta 16 ids con mejor potencial de mispricing ajustado por calidad de evidencia, liquidez, learning velocity y diversificación.
Descarta mercados con mala evidencia o demasiado ruido.
Devuelve solo JSON con formato {{"top":[1,2,3]}}.

Mercados:
{market_lines}
"""
        parsed = call_claude_json(FAST_MODEL, prompt, max_tokens=140)
        indices = [index - 1 for index in parsed.get("top", []) if 1 <= index <= len(ranked[:28])]
        if indices:
            return [ranked[index] for index in indices[:16]]
    except Exception:
        logger.exception("Fast prefilter failed")
    return heuristic_top[:16]


def analyze_candidate(candidate, all_bets):
    packet = candidate["packet"]
    if not ANTHROPIC_API_KEY:
        analysis = heuristic_analysis(packet)
    else:
        try:
            prompt = f"""Eres un analista disciplinado de mercados de predicción enfocado en detectar mercados mal priceados. Piensa en pricing, criterios de resolución, velocidad de aprendizaje, facilidad de ganar, calidad de evidencia y calibración. No adornes ni inventes. Si el caso no está listo para entrar, usa watchlist o skip.
Devuelve solo JSON válido con estas claves exactas:
real_prob, side, confidence, thesis_type, mispricing_type, key_signal, evidence_strength, source_quality_score, uncertainty_score, learning_velocity, market_learnability, ease_of_win, market_horizon_bucket, recommendation_strength, core_vs_secondary_vs_exploratory, take_now_vs_watchlist, what_must_be_true, what_would_invalidate_the_trade, main_risks, time_sensitivity, market_quality, invalidation_condition, short_reason, skip

Contexto del bot:
{get_performance_context()}

Research packet:
{json.dumps(packet, ensure_ascii=False)}
"""
            analysis = call_claude_json(STRONG_MODEL, prompt, max_tokens=450)
        except Exception:
            logger.exception("Claude strong analysis failed for %s", candidate["question"][:80])
            analysis = heuristic_analysis(packet)

    analysis.setdefault("real_prob", packet["market_prob"])
    analysis.setdefault("side", "SI" if analysis["real_prob"] > packet["market_prob"] else "NO")
    analysis.setdefault("confidence", 5)
    analysis.setdefault("thesis_type", packet["thesis_type"])
    analysis.setdefault("mispricing_type", packet["thesis_type"])
    analysis.setdefault("key_signal", packet["factual_news_summary"][:140])
    analysis.setdefault("market_quality", "medium")
    analysis.setdefault("what_must_be_true", "La señal principal no debe degradarse")
    analysis.setdefault("what_would_invalidate_the_trade", "Cambio fuerte de evidencia o precio")
    analysis.setdefault("main_risks", "Falsa lectura de señales")
    analysis.setdefault("source_quality_score", packet["source_quality_score"])
    analysis.setdefault("evidence_strength", packet.get("final_evidence_strength", clamp(packet["source_quality_score"] * 0.5 + min(packet["evidence_count"], 8) * 0.05 - packet["uncertainty_score"] * 0.2, 0.0, 1.0)))
    analysis.setdefault("uncertainty_score", packet["uncertainty_score"])
    analysis.setdefault("learning_velocity", packet["learning_velocity_score"])
    analysis.setdefault("market_learnability", packet["market_learnability_score"])
    analysis.setdefault("ease_of_win", clamp(packet["final_evidence_strength"] * 0.38 + packet["market_learnability_score"] * 0.20 + packet["microstructure_quality_score"] * 0.12 + packet["source_quality_score"] * 0.18 - packet["uncertainty_score"] * 0.18, 0.0, 1.0))
    analysis.setdefault("market_horizon_bucket", classify_horizon_bucket(packet.get("days_left", 999)))
    analysis.setdefault("time_sensitivity", "media")
    analysis.setdefault("recommended_aggression", "medium")
    analysis.setdefault("core_vs_secondary_vs_exploratory", "core" if packet["learning_velocity_score"] >= 0.45 and packet["final_evidence_strength"] >= 0.55 else "secondary" if packet["final_evidence_strength"] >= 0.40 else "exploratory")
    analysis.setdefault("take_now_vs_watchlist", "take_now" if packet["final_evidence_strength"] >= 0.42 and packet["uncertainty_score"] <= 0.70 else "watchlist")
    analysis.setdefault("short_reason", analysis["thesis_type"])
    analysis.setdefault("recommendation_strength", clamp(analysis["evidence_strength"] * 0.6 + analysis["source_quality_score"] * 0.25 - packet["uncertainty_score"] * 0.2, 0.0, 1.0))
    analysis.setdefault("invalidation_condition", analysis["what_would_invalidate_the_trade"])
    analysis.setdefault("skip", False)

    real_prob = clamp(safe_float(analysis["real_prob"]), 0.02, 0.98)
    analysis["real_prob"] = real_prob
    analysis["confidence"] = int(clamp(int(analysis["confidence"]), 1, 10))
    analysis["side"] = analysis.get("side", "SI" if real_prob > packet["market_prob"] else "NO")
    if analysis["side"] not in ("SI", "NO", "skip"):
        analysis["side"] = "SI" if real_prob > packet["market_prob"] else "NO"
    analysis["source_quality_score"] = round(clamp(safe_float(analysis["source_quality_score"]), 0.0, 1.0), 4)
    analysis["evidence_strength"] = round(clamp(safe_float(analysis["evidence_strength"]), 0.0, 1.0), 4)
    analysis["uncertainty_score"] = round(clamp(safe_float(analysis["uncertainty_score"]), 0.0, 1.0), 4)
    analysis["learning_velocity"] = round(clamp(safe_float(analysis["learning_velocity"]), 0.0, 1.0), 4)
    analysis["market_learnability"] = round(clamp(safe_float(analysis["market_learnability"]), 0.0, 1.0), 4)
    analysis["ease_of_win"] = round(clamp(safe_float(analysis["ease_of_win"]), 0.0, 1.0), 4)
    analysis["market_horizon_bucket"] = analysis["market_horizon_bucket"] if analysis["market_horizon_bucket"] in ("ultra_short", "short", "medium", "long") else classify_horizon_bucket(packet.get("days_left", 999))
    analysis["recommendation_strength"] = round(clamp(safe_float(analysis["recommendation_strength"]), 0.0, 1.0), 4)
    analysis["market_quality"] = analysis["market_quality"] if analysis["market_quality"] in ("high", "medium", "low") else "medium"
    analysis["core_vs_secondary_vs_exploratory"] = analysis["core_vs_secondary_vs_exploratory"] if analysis["core_vs_secondary_vs_exploratory"] in ("core", "secondary", "exploratory") else "exploratory"
    analysis["take_now_vs_watchlist"] = analysis["take_now_vs_watchlist"] if analysis["take_now_vs_watchlist"] in ("take_now", "watchlist") else "watchlist"
    analysis["skip"] = bool(analysis.get("skip")) or analysis["recommendation_strength"] < 0.25
    candidate["analysis"] = analysis
    candidate["edge"] = abs(real_prob - packet["market_prob"])
    candidate["side"] = analysis["side"]
    candidate["thesis_type"] = analysis["thesis_type"]
    candidate["conclusion_reliability_score"] = compute_conclusion_reliability(packet, analysis["confidence"])
    candidate["trade_class"] = analysis["core_vs_secondary_vs_exploratory"]
    memory = historical_bias_for_setup(packet["category"], analysis["thesis_type"], candidate["trade_class"], all_bets)
    candidate["memory"] = memory
    return candidate


def compute_candidate_score(candidate, open_bets):
    packet = candidate["packet"]
    analysis = candidate["analysis"]
    correlation_penalty = estimate_correlation_penalty(candidate, open_bets)
    liquidity_score = clamp((packet["volume"] / 25000.0), 0.0, 1.0)
    spread_score = clamp(1 - (packet["spread"] / 0.06), 0.0, 1.0)
    spread_penalty = clamp(packet["spread"] / 0.07, 0.0, 1.0)
    momentum_context = 1 - clamp(abs(packet["momentum_24h"]) * 4, 0.0, 0.4) + clamp(packet.get("cluster_divergence", 0) * 1.2, 0.0, 0.25)
    orderbook_quality = clamp(0.5 + abs(packet["orderbook_imbalance"]) * 0.4 + (0.15 if packet["smart_money"] != "none" else 0.0) - packet["spread"] * 2, 0.0, 1.0)
    mispricing_attractiveness = clamp(candidate["edge"] * 4 + packet.get("cluster_divergence", 0) * 1.4 + abs((packet.get("external_forecast_prob") or packet["market_prob"]) - packet["market_prob"]) * 1.4, 0.0, 1.0)
    historical_bias = candidate["memory"]["bias"]
    reliability = candidate.get("conclusion_reliability_score", compute_conclusion_reliability(packet, analysis["confidence"]))
    candidate["horizon_bucket"] = analysis.get("market_horizon_bucket", classify_horizon_bucket(packet.get("days_left", 999)))
    candidate["mispricing_score"] = round(clamp(packet.get("mispricing_score", 0.0) * 0.55 + mispricing_attractiveness * 0.45, 0.0, 1.0), 4)
    candidate["learning_velocity_score"] = round(clamp(packet.get("learning_velocity_score", 0.0) * 0.65 + analysis.get("learning_velocity", 0.0) * 0.35, 0.0, 1.0), 4)
    candidate["market_learnability_score"] = round(clamp(packet.get("market_learnability_score", 0.0) * 0.70 + analysis.get("market_learnability", 0.0) * 0.30, 0.0, 1.0), 4)
    candidate["ease_of_win_score"] = compute_ease_of_win_score(packet, analysis, reliability, historical_bias)
    candidate["liquidity_score"] = round(liquidity_score, 4)
    candidate["spread_penalty"] = round(spread_penalty, 4)
    candidate["historical_pattern_score"] = round(clamp(0.5 + historical_bias, 0.0, 1.0), 4)
    candidate["market_quality_score"] = round(clamp(orderbook_quality * 0.35 + spread_score * 0.20 + packet.get("microstructure_quality_score", 0.0) * 0.25 + packet.get("source_quality_score", 0.0) * 0.20, 0.0, 1.0), 4)
    candidate["opportunity_score"] = round(clamp(candidate["edge"] * 1.15 + candidate["mispricing_score"] * 0.35 + analysis["recommendation_strength"] * 0.25 + liquidity_score * 0.15, 0.0, 1.0), 4)
    candidate["capital_efficiency_score"] = compute_capital_efficiency_score(candidate)
    score = (
        candidate["opportunity_score"] * 1.35
        + reliability * 1.10
        + candidate["learning_velocity_score"] * 0.95
        + candidate["market_learnability_score"] * 0.75
        + candidate["ease_of_win_score"] * 1.05
        + candidate["capital_efficiency_score"] * 0.65
        + analysis["evidence_strength"] * 0.85
        + analysis["source_quality_score"] * 0.70
        + liquidity_score * 0.50
        + spread_score * 0.40
        + clamp(momentum_context, 0.0, 1.0) * 0.25
        + orderbook_quality * 0.35
        + historical_bias * 0.65
        - packet["uncertainty_score"] * 0.80
        - correlation_penalty * 0.85
    )
    candidate["compound_score"] = round(clamp(score / 6.8, 0.0, 1.0), 4)
    candidate["portfolio_priority_score"] = round(clamp(
        candidate["opportunity_score"] * 0.30
        + reliability * 0.22
        + candidate["learning_velocity_score"] * 0.12
        + candidate["ease_of_win_score"] * 0.16
        + candidate["capital_efficiency_score"] * 0.08
        + candidate["market_quality_score"] * 0.07
        + candidate["historical_pattern_score"] * 0.05
        - correlation_penalty * 0.12
        - spread_penalty * 0.08,
        0.0,
        1.0,
    ), 4)
    candidate["correlation_penalty"] = round(correlation_penalty, 4)
    candidate["conclusion_reliability_score"] = round(reliability, 4)
    candidate["trade_class"] = classify_trade_class(
        candidate["conclusion_reliability_score"],
        candidate["opportunity_score"],
        candidate["learning_velocity_score"],
        candidate["ease_of_win_score"],
    )
    candidate["tier"] = assign_candidate_tier(candidate)
    candidate["obvious_enough_to_take"] = obvious_enough_to_take(candidate)
    return candidate


def estimate_correlation_penalty(candidate, open_bets):
    if not open_bets:
        return 0.0
    packet = candidate["packet"]
    penalties = []
    for bet in open_bets:
        overlap = len(top_overlap_terms(packet["market_question"], bet.get("question", "")))
        same_category = bet.get("category") == packet["category"]
        same_thesis = bet.get("thesis_type") == candidate.get("thesis_type")
        same_side = bet.get("side") == candidate.get("side")
        penalty = (0.10 if same_category else 0.0) + (0.10 if same_thesis else 0.0) + (0.08 if same_side else 0.0) + min(overlap * 0.04, 0.20)
        penalties.append(penalty)
    return clamp(max(penalties), 0.0, 0.6)


def current_portfolio_snapshot(all_bets=None):
    bets = all_bets if all_bets is not None else get_all_bets()
    open_bets = get_open_bets(bets)
    free_balance = get_state("balance", get_paper_starting_balance())
    committed = sum(safe_float(bet.get("amount"), 0.0) for bet in open_bets)
    total_equity = free_balance + committed
    category_exposure = defaultdict(float)
    side_exposure = defaultdict(float)
    thesis_exposure = defaultdict(float)
    core_open = 0
    secondary_open = 0
    experimental_open = 0
    tier_exposure = defaultdict(float)
    horizon_exposure = defaultdict(float)
    for bet in open_bets:
        amount = safe_float(bet.get("amount"), 0.0)
        category_exposure[bet.get("category", "general")] += amount
        side_exposure[bet.get("side", "SI")] += amount
        thesis_exposure[bet.get("thesis_type", "unknown")] += amount
        tier_exposure[bet.get("tier", "TIER_C")] += amount
        horizon_exposure[bet.get("horizon_bucket", "medium")] += amount
        if bet.get("trade_class") == "experimental":
            experimental_open += 1
        elif bet.get("trade_class") == "secondary":
            secondary_open += 1
        else:
            core_open += 1
    return {
        "open_bets": open_bets,
        "free_balance": round(free_balance, 2),
        "committed": round(committed, 2),
        "total_equity": round(total_equity, 2),
        "exploration_capital_reserved": round(total_equity * EXPLORATION_CAPITAL_RESERVE_PCT, 2),
        "category_exposure": dict(category_exposure),
        "side_exposure": dict(side_exposure),
        "thesis_exposure": dict(thesis_exposure),
        "tier_exposure": dict(tier_exposure),
        "horizon_exposure": dict(horizon_exposure),
        "core_open": core_open,
        "secondary_open": secondary_open,
        "experimental_open": experimental_open,
        "core_budget": round(total_equity * CORE_BUDGET_PCT, 2),
        "secondary_budget": round(total_equity * SECONDARY_BUDGET_PCT, 2),
        "exploratory_budget": round(total_equity * EXPLORATORY_BUDGET_PCT, 2),
        "fast_feedback_budget": round(total_equity * FAST_FEEDBACK_BUDGET_PCT, 2),
        "long_dated_budget": round(total_equity * LONG_DATED_HIGH_CONVICTION_BUDGET_PCT, 2),
    }


def can_allocate(candidate, snapshot):
    total_equity = max(snapshot["total_equity"], 1.0)
    horizon_bucket = candidate.get("horizon_bucket", "medium")
    if len(snapshot["open_bets"]) >= MAX_OPEN_BETS:
        return False, "max_open_positions"
    if snapshot["committed"] / total_equity >= MAX_TOTAL_EXPOSURE_PCT:
        return False, "max_total_exposure"
    if snapshot["category_exposure"].get(candidate["packet"]["category"], 0.0) / total_equity >= MAX_CATEGORY_EXPOSURE_PCT:
        return False, "max_category_exposure"
    if snapshot["side_exposure"].get(candidate["side"], 0.0) / total_equity >= MAX_SIDE_EXPOSURE_PCT:
        return False, "max_side_exposure"
    if snapshot["thesis_exposure"].get(candidate["thesis_type"], 0.0) / total_equity >= MAX_THESIS_EXPOSURE_PCT:
        return False, "max_thesis_exposure"
    if horizon_bucket == "long" and snapshot["horizon_exposure"].get("long", 0.0) / total_equity >= LONG_DATED_HIGH_CONVICTION_BUDGET_PCT and candidate.get("tier") != "TIER_A":
        return False, "long_dated_budget_full"
    return True, "ok"


def size_bet(candidate, snapshot):
    analysis = candidate["analysis"]
    packet = candidate["packet"]
    edge = candidate["edge"]
    reliability = candidate.get("conclusion_reliability_score", 0.0)
    trade_class = candidate["trade_class"]
    tier = candidate.get("tier", "TIER_C")
    horizon_bucket = candidate.get("horizon_bucket", "medium")
    base_fraction = clamp(edge * 0.72 + analysis["evidence_strength"] * 0.05 + analysis["source_quality_score"] * 0.04 + reliability * 0.05, 0.005, CORE_MAX_FRACTION)
    aggression_multiplier = {"high": 1.35, "medium": 1.0, "low": 0.70}.get(analysis["recommended_aggression"], 1.0)
    quality_multiplier = 0.65 + analysis["source_quality_score"] * 0.55 + analysis["evidence_strength"] * 0.35
    liquidity_multiplier = clamp(0.55 + min(packet["volume"], 50000) / 50000.0, 0.55, 1.35)
    spread_multiplier = clamp(1.15 - packet["spread"] * 10, 0.45, 1.05)
    memory_multiplier = clamp(1.0 + candidate["memory"]["bias"], 0.70, 1.25)
    correlation_multiplier = clamp(1.0 - candidate["correlation_penalty"], 0.50, 1.0)
    long_dated_multiplier = 0.70 if packet.get("days_left", 999) > LONG_DATED_PENALTY_START_DAYS and candidate["edge"] < 0.14 else 1.0
    learning_multiplier = clamp(0.70 + candidate.get("learning_velocity_score", 0.0) * 0.40 + candidate.get("market_learnability_score", 0.0) * 0.25, 0.60, 1.35)
    ease_multiplier = clamp(0.75 + candidate.get("ease_of_win_score", 0.0) * 0.45, 0.65, 1.30)
    capital_efficiency_multiplier = clamp(0.75 + candidate.get("capital_efficiency_score", 0.0) * 0.40, 0.65, 1.20)
    tier_multiplier = {"TIER_A": 1.15, "TIER_B": 0.82, "TIER_C": 0.55}.get(tier, 0.40)
    horizon_multiplier = {"ultra_short": 0.88, "short": 1.00, "medium": 0.95, "long": 0.72}.get(horizon_bucket, 0.90)
    if trade_class == "secondary":
        base_fraction = min(base_fraction * 0.52, 0.065)
    elif trade_class == "experimental":
        base_fraction = min(base_fraction * 0.28, EXPERIMENTAL_MAX_FRACTION)
    final_fraction = clamp(base_fraction * aggression_multiplier * quality_multiplier * liquidity_multiplier * spread_multiplier * memory_multiplier * correlation_multiplier * long_dated_multiplier * learning_multiplier * ease_multiplier * capital_efficiency_multiplier * tier_multiplier * horizon_multiplier, 0.003, CORE_MAX_FRACTION if trade_class == "core" else 0.07 if trade_class == "secondary" else EXPERIMENTAL_MAX_FRACTION)
    usable_cash = snapshot["free_balance"]
    if trade_class == "core":
        usable_cash = max(0.0, snapshot["free_balance"] - max(0.0, snapshot["exploration_capital_reserved"] - snapshot["experimental_open"] * 20))
    elif trade_class == "secondary":
        usable_cash = min(snapshot["free_balance"], snapshot["secondary_budget"] + max(0.0, snapshot["free_balance"] * 0.12))
    else:
        usable_cash = min(snapshot["free_balance"], snapshot["exploration_capital_reserved"] + max(0.0, snapshot["free_balance"] * 0.08))
    if horizon_bucket in ("ultra_short", "short"):
        usable_cash = min(snapshot["free_balance"], usable_cash + snapshot["fast_feedback_budget"] * 0.20)
    if horizon_bucket == "long" and trade_class != "core":
        usable_cash *= 0.70
    amount = round(max(8.0 if trade_class == "experimental" else 14.0 if trade_class == "secondary" else 20.0, usable_cash * final_fraction), 2)
    amount = min(amount, snapshot["free_balance"] * (0.18 if trade_class == "core" else 0.10 if trade_class == "secondary" else 0.06))
    return amount, round(final_fraction, 4)


def select_portfolio(candidates, snapshot):
    selected = []
    watchlist = []
    rejected = []
    cycle_core = 0
    cycle_secondary = 0
    cycle_exploratory = 0
    for candidate in sorted(candidates, key=lambda item: (item.get("portfolio_priority_score", 0.0), item["compound_score"]), reverse=True):
        trade_class = candidate["trade_class"]
        tier = candidate.get("tier", "TIER_C")
        floor = TIER_A_SCORE_FLOOR if tier == "TIER_A" else TIER_B_SCORE_FLOOR if tier == "TIER_B" else EXPERIMENTAL_SCORE_FLOOR
        if candidate["analysis"].get("skip"):
            rejected.append((candidate, "llm_skip"))
            continue
        if trade_class == "skip" or tier == "TIER_D":
            rejected.append((candidate, "tier_skip"))
            continue
        if candidate["analysis"].get("take_now_vs_watchlist") == "watchlist" and len(watchlist) < WATCHLIST_LIMIT:
            candidate["selection_bucket"] = "watchlist_high_potential"
            watchlist.append(candidate)
            continue
        if candidate["portfolio_priority_score"] < floor and not candidate.get("obvious_enough_to_take"):
            if len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, "low_score"))
            continue
        min_reliability = 0.58 if trade_class == "core" else 0.40 if trade_class == "secondary" else 0.28
        if candidate.get("conclusion_reliability_score", 0.0) < min_reliability and not candidate.get("obvious_enough_to_take"):
            if len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, "low_reliability"))
            continue
        if candidate["edge"] < (MIN_EDGE_TO_BET if trade_class != "experimental" else 0.04) or candidate["analysis"]["confidence"] < (MIN_CONFIDENCE_TO_BET if trade_class == "core" else 4):
            rejected.append((candidate, "weak_edge_or_confidence"))
            continue
        if candidate["analysis"]["source_quality_score"] < (MIN_SOURCE_QUALITY_TO_BET if trade_class != "experimental" else 0.28) or candidate["analysis"]["evidence_strength"] < (MIN_EVIDENCE_STRENGTH_TO_BET if trade_class != "experimental" else 0.26):
            rejected.append((candidate, "low_evidence"))
            continue
        if len(selected) >= MAX_POSITIONS_PER_CYCLE:
            rejected.append((candidate, "cycle_limit"))
            continue
        if trade_class == "core" and cycle_core >= MAX_CORE_POSITIONS_PER_CYCLE:
            rejected.append((candidate, "core_cycle_limit"))
            continue
        if trade_class == "secondary" and cycle_secondary >= MAX_SECONDARY_POSITIONS_PER_CYCLE:
            if len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, "secondary_cycle_limit"))
            continue
        if trade_class == "experimental" and cycle_exploratory >= MAX_EXPLORATORY_POSITIONS_PER_CYCLE:
            rejected.append((candidate, "exploratory_cycle_limit"))
            continue
        allowed, reason = can_allocate(candidate, snapshot)
        if not allowed:
            if reason in ("max_category_exposure", "max_thesis_exposure", "long_dated_budget_full") and len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, reason))
            continue
        amount, kelly_f = size_bet(candidate, snapshot)
        if amount < 5:
            rejected.append((candidate, "size_too_small"))
            continue
        candidate["amount"] = amount
        candidate["kelly_f"] = kelly_f
        candidate["selection_bucket"] = "selected_now"
        selected.append(candidate)
        snapshot["free_balance"] = round(snapshot["free_balance"] - amount, 2)
        snapshot["committed"] += amount
        snapshot["open_bets"].append({"question": candidate["question"], "side": candidate["side"], "category": candidate["packet"]["category"], "thesis_type": candidate["thesis_type"], "amount": amount, "trade_class": trade_class, "tier": tier, "horizon_bucket": candidate.get("horizon_bucket", "medium")})
        snapshot["category_exposure"][candidate["packet"]["category"]] = snapshot["category_exposure"].get(candidate["packet"]["category"], 0.0) + amount
        snapshot["side_exposure"][candidate["side"]] = snapshot["side_exposure"].get(candidate["side"], 0.0) + amount
        snapshot["thesis_exposure"][candidate["thesis_type"]] = snapshot["thesis_exposure"].get(candidate["thesis_type"], 0.0) + amount
        snapshot["tier_exposure"][tier] = snapshot["tier_exposure"].get(tier, 0.0) + amount
        snapshot["horizon_exposure"][candidate.get("horizon_bucket", "medium")] = snapshot["horizon_exposure"].get(candidate.get("horizon_bucket", "medium"), 0.0) + amount
        if trade_class == "core":
            cycle_core += 1
        elif trade_class == "secondary":
            cycle_secondary += 1
        else:
            cycle_exploratory += 1
    return selected, watchlist, rejected

# ── EXECUTION / MONITOR / METRICS ────────────────────────────
def place_bet_from_candidate(candidate, cycle_id):
    packet = candidate["packet"]
    analysis = candidate["analysis"]
    amount = candidate["amount"]
    free_balance = get_state("balance", get_paper_starting_balance())
    if free_balance < amount:
        return None
    bet = {
        "id": str(uuid.uuid4()),
        "question": candidate["question"],
        "market_id": candidate["market_id"],
        "side": candidate["side"],
        "amount": amount,
        "prob_market": packet["market_prob"],
        "prob_claude": analysis["real_prob"],
        "edge": round(candidate["edge"], 4),
        "confidence": analysis["confidence"],
        "kelly_f": candidate["kelly_f"],
        "status": "open",
        "pnl": 0.0,
        "reasoning": analysis["short_reason"],
        "sources_used": ", ".join([name for name, present in [("news", packet.get("factual_news_source") == "news"), ("metaculus", packet.get("external_forecast_prob") is not None), ("wikipedia", packet.get("factual_news_source") == "wikipedia"), ("reddit", bool(packet["crowd_signal_summary"] and packet["crowd_signal_summary"] != "Sin crowd chatter relevante")), ("orderbook", True), ("price_history", True)] if present]),
        "price_entry": packet["current_price"],
        "price_current": packet["current_price"],
        "peak_return": 0.0,
        "take_profit_hit": False,
        "stop_loss_hit": False,
        "category": packet["category"],
        "thesis_type": analysis["thesis_type"],
        "mispricing_type": analysis["mispricing_type"],
        "trade_class": candidate["trade_class"],
        "tier": candidate.get("tier", "TIER_C"),
        "selection_bucket": candidate.get("selection_bucket", "selected_now"),
        "horizon_bucket": candidate.get("horizon_bucket", classify_horizon_bucket(packet.get("days_left", 999))),
        "strategy_version": get_current_strategy_version(),
        "lab_epoch": get_current_lab_epoch(),
        "active_lab": True,
        "source_quality_score": analysis["source_quality_score"],
        "source_diversity_score": packet["source_diversity_score"],
        "factual_strength": packet["factual_strength"],
        "chatter_dependency": packet["chatter_dependency"],
        "evidence_strength": analysis["evidence_strength"],
        "composite_score": candidate["compound_score"],
        "mispricing_score": candidate["mispricing_score"],
        "opportunity_score": candidate["opportunity_score"],
        "portfolio_priority_score": candidate.get("portfolio_priority_score", candidate["compound_score"]),
        "ease_of_win_score": candidate.get("ease_of_win_score", 0.0),
        "market_quality_score": candidate.get("market_quality_score", 0.0),
        "liquidity_score": candidate.get("liquidity_score", 0.0),
        "spread_penalty": candidate.get("spread_penalty", 0.0),
        "capital_efficiency_score": candidate.get("capital_efficiency_score", 0.0),
        "historical_pattern_score": candidate.get("historical_pattern_score", 0.0),
        "learning_velocity_score": candidate["learning_velocity_score"],
        "market_learnability_score": candidate["market_learnability_score"],
        "conclusion_reliability_score": candidate["conclusion_reliability_score"],
        "recommendation_strength": analysis["recommendation_strength"],
        "market_quality": analysis["market_quality"],
        "obvious_enough_to_take": candidate.get("obvious_enough_to_take", False),
        "external_match_confidence": packet["external_match_confidence"],
        "microstructure_quality_score": packet["microstructure_quality_score"],
        "recommended_aggression": analysis["recommended_aggression"],
        "what_must_be_true": analysis["what_must_be_true"],
        "what_would_invalidate_the_trade": analysis["what_would_invalidate_the_trade"],
        "invalidation_condition": analysis["what_would_invalidate_the_trade"],
        "main_risks": analysis["main_risks"],
        "key_signal": analysis["key_signal"],
        "research_packet": json.dumps(packet, ensure_ascii=False),
        "analysis_json": json.dumps(analysis, ensure_ascii=False),
        "research_summary_hash": hash_text(json.dumps({"question": candidate["question"], "signal": analysis["key_signal"], "thesis": analysis["thesis_type"], "sources": packet["source_quality_score"], "facts": packet["factual_news_summary"][:120]}, ensure_ascii=False)),
        "portfolio_cycle_id": cycle_id,
        "evidence_count": packet["evidence_count"],
        "contradictions_found": packet["contradictions_found"],
        "recency_score": packet["recency_score"],
        "uncertainty_score": packet["uncertainty_score"],
        "missing_data_flags": json.dumps(packet["missing_data_flags"], ensure_ascii=False),
        "market_prob_bucket": bucket_probability(packet["market_prob"]),
        "confidence_bucket": bucket_confidence(analysis["confidence"]),
        "edge_bucket": bucket_edge(candidate["edge"]),
        "time_to_resolution_hours": packet["time_to_resolution_hours"],
        "feedback_time_bucket": bucket_time_to_feedback(packet["time_to_resolution_hours"]),
        "resolved_reason": None,
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
    }
    if not save_bet(bet):
        return None
    set_state("balance", free_balance - amount)
    set_state("bets_placed", get_state("bets_placed", 0) + 1)
    set_state("total_edge", get_state("total_edge", 0) + candidate["edge"])
    timer = threading.Timer(INITIAL_RESOLUTION_CHECK_SECONDS, resolve_bet_real, args=[bet["id"]])
    timer.daemon = True
    timer.start()
    return bet


def close_bet(bet, current_yes_price, status, reason, take_profit=False, stop_loss=False):
    side_price = compute_current_side_price(bet["side"], current_yes_price)
    entry_cost = compute_current_side_price(bet["side"], safe_float(bet.get("price_entry"), current_yes_price))
    shares = safe_float(bet.get("amount"), 0.0) / max(entry_cost, 0.01)
    realized_value = round(shares * side_price * POLYMARKET_FEE_HAIRCUT, 2)
    pnl = round(realized_value - safe_float(bet.get("amount"), 0.0), 2)
    set_state("balance", get_state("balance", get_paper_starting_balance()) + max(realized_value, 0.0))
    if status == "won":
        set_state("won", get_state("won", 0) + 1)
    else:
        set_state("lost", get_state("lost", 0) + 1)
    update_bet_fields(bet["id"], {"price_current": current_yes_price, "status": status, "pnl": pnl, "resolved_reason": reason, "take_profit_hit": take_profit, "stop_loss_hit": stop_loss, "resolved_at": datetime.now(timezone.utc)})


def monitor_open_positions():
    for bet in get_open_bets():
        try:
            price_data = fetch_price_history(bet.get("market_id", ""))
            current_yes = price_data["current_price"] if price_data["current_price"] is not None else safe_float(bet.get("price_current"), safe_float(bet.get("price_entry"), 0.5))
            entry_side_price = compute_current_side_price(bet["side"], safe_float(bet.get("price_entry"), current_yes))
            current_side_price = compute_current_side_price(bet["side"], current_yes)
            price_move = (current_side_price - entry_side_price) / max(entry_side_price, 0.01)
            peak_return = max(safe_float(bet.get("peak_return"), 0.0), price_move)
            update_bet_fields(bet["id"], {"price_current": current_yes, "peak_return": round(peak_return, 4)})
            if price_move >= TAKE_PROFIT_THRESHOLD:
                close_bet(bet, current_yes, "won", "take_profit", take_profit=True)
            elif peak_return >= TAKE_PROFIT_THRESHOLD and price_move <= peak_return - TRAILING_STOP_GIVEBACK:
                close_bet(bet, current_yes, "won" if price_move > 0 else "lost", "trailing_exit")
            elif price_move <= -STOP_LOSS_THRESHOLD:
                close_bet(bet, current_yes, "lost", "stop_loss", stop_loss=True)
        except Exception:
            logger.exception("Monitor failed for bet id=%s", bet.get("id"))


def resolve_bet_real(bet_id):
    bet = next((item for item in get_all_bets() if item["id"] == bet_id), None)
    if not bet or bet.get("status") != "open":
        return
    try:
        response = requests.get(f"{GAMMA_API}/markets/{bet.get('market_id', '')}", timeout=REQUEST_TIMEOUT)
        market = response.json()
        if market.get("resolved") or market.get("closed"):
            winner = market.get("winner", "")
            outcomes = market.get("outcomes", ["Yes", "No"])
            won = winner == outcomes[0] if bet["side"] == "SI" else (winner == outcomes[1] if len(outcomes) > 1 else False)
            resolved_yes_price = 1.0 if winner == outcomes[0] else 0.0 if len(outcomes) > 1 and winner == outcomes[1] else safe_float(bet.get("price_current"), safe_float(bet.get("price_entry"), 0.5))
            close_bet(bet, resolved_yes_price, "won" if won else "lost", "real_resolution")
            return
        timer = threading.Timer(RESOLUTION_RETRY_SECONDS, resolve_bet_real, args=[bet_id])
        timer.daemon = True
        timer.start()
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Real resolution failed for bet id=%s", bet_id)


def run_bot_cycle():
    cycle_id = str(uuid.uuid4())
    markets = fetch_active_markets()
    all_bets = get_current_lab_bets()
    open_bets = get_open_bets(all_bets)
    now_utc = datetime.now(timezone.utc)
    candidates = []
    for market in markets:
        try:
            supported, market_prob = detect_market_supported(market, now_utc)
            if not supported:
                continue
            question = normalize_question(market.get("question", ""))[:120]
            if any(question == bet.get("question", "") for bet in open_bets):
                continue
            packet = build_research_packet(market, market_prob, markets, all_bets)
            prefilter_score = clamp(packet["source_quality_score"] * 0.22 + packet["final_evidence_strength"] * 0.18 + packet["mispricing_score"] * 0.28 + packet["learning_velocity_score"] * 0.18 + packet["market_learnability_score"] * 0.10 + (packet["volume"] / 50000.0) * 0.12 - packet["uncertainty_score"] * 0.18, 0.0, 1.0)
            candidates.append({"question": question, "market_id": market.get("id", ""), "market": market, "packet": packet, "prefilter_score": round(prefilter_score, 4)})
        except Exception:
            logger.exception("Candidate build failed for market=%s", market.get("id", "?"))

    shortlist = fast_prefilter(candidates)
    analyzed = [compute_candidate_score(analyze_candidate(candidate, all_bets), open_bets) for candidate in shortlist]
    snapshot = current_portfolio_snapshot(all_bets)
    selected, watchlist, rejected = select_portfolio(analyzed, snapshot)
    placed = []
    for candidate in selected:
        bet = place_bet_from_candidate(candidate, cycle_id)
        if bet:
            placed.append(bet)
    LAST_CYCLE_DATA["cycle_id"] = cycle_id
    LAST_CYCLE_DATA["candidates"] = [
        {
            "question": candidate["question"],
            "market_id": candidate["market_id"],
            "prefilter_score": candidate["prefilter_score"],
            "category": candidate["packet"]["category"],
            "source_quality_score": candidate["packet"]["source_quality_score"],
            "evidence_strength": candidate["packet"]["final_evidence_strength"],
            "contradictions_found": candidate["packet"]["contradictions_found"],
            "uncertainty_score": candidate["packet"]["uncertainty_score"],
            "thesis_type": candidate["packet"]["thesis_type"],
            "mispricing_flags": candidate["packet"]["mispricing_flags"],
            "learning_velocity_score": candidate["packet"]["learning_velocity_score"],
            "market_learnability_score": candidate["packet"]["market_learnability_score"],
            "horizon_bucket": classify_horizon_bucket(candidate["packet"].get("days_left", 999)),
        }
        for candidate in candidates[:40]
    ]
    LAST_CYCLE_DATA["shortlist"] = [
        {
            "question": candidate["question"],
            "edge": round(candidate["edge"], 4),
            "compound_score": candidate["compound_score"],
            "opportunity_score": candidate["opportunity_score"],
            "mispricing_score": candidate["mispricing_score"],
            "learning_velocity_score": candidate["learning_velocity_score"],
            "market_learnability_score": candidate["market_learnability_score"],
            "ease_of_win_score": candidate["ease_of_win_score"],
            "portfolio_priority_score": candidate["portfolio_priority_score"],
            "conclusion_reliability_score": candidate["conclusion_reliability_score"],
            "trade_class": candidate["trade_class"],
            "tier": candidate["tier"],
            "horizon_bucket": candidate["horizon_bucket"],
            "obvious_enough_to_take": candidate["obvious_enough_to_take"],
            "category": candidate["packet"]["category"],
            "thesis_type": candidate["thesis_type"],
            "analysis": candidate["analysis"],
            "packet": candidate["packet"],
        }
        for candidate in analyzed
    ]
    LAST_CYCLE_DATA["selected"] = [
        {
            "question": candidate["question"],
            "trade_class": candidate["trade_class"],
            "tier": candidate.get("tier"),
            "horizon_bucket": candidate.get("horizon_bucket"),
            "amount": candidate.get("amount", 0),
            "edge": round(candidate["edge"], 4),
            "compound_score": candidate["compound_score"],
            "opportunity_score": candidate["opportunity_score"],
            "portfolio_priority_score": candidate["portfolio_priority_score"],
            "reliability": candidate["conclusion_reliability_score"],
            "reason": candidate["analysis"]["short_reason"],
        }
        for candidate in selected
    ]
    LAST_CYCLE_DATA["watchlist"] = [
        {
            "question": candidate["question"],
            "trade_class": candidate["trade_class"],
            "tier": candidate.get("tier"),
            "horizon_bucket": candidate.get("horizon_bucket"),
            "edge": round(candidate.get("edge", 0.0), 4),
            "portfolio_priority_score": candidate.get("portfolio_priority_score"),
            "opportunity_score": candidate.get("opportunity_score"),
            "reliability": candidate.get("conclusion_reliability_score"),
            "reason": candidate["analysis"].get("short_reason"),
            "selection_bucket": candidate.get("selection_bucket", "watchlist_high_potential"),
        }
        for candidate in watchlist
    ]
    LAST_CYCLE_DATA["rejected"] = [
        {
            "question": candidate["question"],
            "reason": reason,
            "trade_class": candidate.get("trade_class"),
            "tier": candidate.get("tier"),
            "horizon_bucket": candidate.get("horizon_bucket"),
            "edge": round(candidate.get("edge", 0.0), 4),
            "score": candidate.get("portfolio_priority_score", candidate.get("compound_score")),
            "reliability": candidate.get("conclusion_reliability_score"),
        }
        for candidate, reason in rejected[:40]
    ]
    LAST_CYCLE_DATA["summary"] = build_cycle_summary(len(candidates), len(shortlist), selected, watchlist, rejected)
    LAST_CYCLE_DATA["blockers"] = LAST_CYCLE_DATA["summary"].get("blockers", {})
    set_state("cycles_run", get_state("cycles_run", 0) + 1)
    set_state("markets_analyzed_last_cycle", len(candidates))
    set_state("discarded_low_evidence_last_cycle", sum(1 for _, reason in rejected if reason in ("low_evidence", "weak_edge_or_confidence", "low_score")))
    set_state("discarded_correlation_last_cycle", sum(1 for _, reason in rejected if "exposure" in reason or reason == "max_open_positions"))
    set_state("passed_to_portfolio_last_cycle", len(placed))
    set_state("watchlist_last_cycle", len(watchlist))
    set_state("selected_core_last_cycle", sum(1 for candidate in selected if candidate.get("trade_class") == "core"))
    set_state("selected_secondary_last_cycle", sum(1 for candidate in selected if candidate.get("trade_class") == "secondary"))
    set_state("selected_exploratory_last_cycle", sum(1 for candidate in selected if candidate.get("trade_class") == "experimental"))
    return {"cycle_id": cycle_id, "analyzed": len(candidates), "shortlisted": len(shortlist), "selected": len(selected), "watchlist": len(watchlist), "placed": placed, "rejected": rejected}


def aggregate_metrics():
    bets = get_current_lab_bets()
    legacy_bets = get_legacy_bets()
    open_bets = get_open_bets(bets)
    realized = [bet for bet in bets if bet.get("status") in ("won", "lost")]
    realized_pnl = round(sum(safe_float(bet.get("pnl"), 0.0) for bet in realized), 2)
    unrealized_pnl = round(sum(estimate_unrealized_pnl(bet) for bet in open_bets), 2)
    snapshot = current_portfolio_snapshot(bets)
    by_category = defaultdict(float)
    by_thesis = defaultdict(float)
    by_trade_class = defaultdict(float)
    by_tier = defaultdict(float)
    confidence_stats = defaultdict(lambda: {"won": 0, "total": 0})
    edge_stats = defaultdict(lambda: {"won": 0, "total": 0})
    source_quality_stats = defaultdict(lambda: {"won": 0, "total": 0})
    evidence_stats = defaultdict(lambda: {"won": 0, "total": 0})
    contradiction_stats = defaultdict(lambda: {"won": 0, "total": 0})
    exploratory_stats = defaultdict(lambda: {"won": 0, "total": 0})
    learning_velocity_stats = defaultdict(lambda: {"won": 0, "total": 0})
    time_bucket_stats = defaultdict(lambda: {"won": 0, "total": 0})
    mispricing_stats = defaultdict(lambda: {"won": 0, "total": 0, "pnl": 0.0})
    early_feedback_count = 0
    capital_reused_early = 0.0
    hold_hours = []
    for bet in realized:
        pnl = safe_float(bet.get("pnl"), 0.0)
        by_category[bet.get("category", "general")] += pnl
        by_thesis[bet.get("thesis_type", "unknown")] += pnl
        by_trade_class[bet.get("trade_class", "core")] += pnl
        by_tier[bet.get("tier", "TIER_C")] += pnl
        confidence_bucket = bet.get("confidence_bucket") or bucket_confidence(int(bet.get("confidence") or 5))
        edge_bucket_name = bet.get("edge_bucket") or bucket_edge(safe_float(bet.get("edge"), 0.0))
        source_bucket = "high" if safe_float(bet.get("source_quality_score"), 0.0) >= 0.7 else "mid" if safe_float(bet.get("source_quality_score"), 0.0) >= 0.45 else "low"
        evidence_bucket = "high" if safe_float(bet.get("evidence_strength"), 0.0) >= 0.7 else "mid" if safe_float(bet.get("evidence_strength"), 0.0) >= 0.45 else "low"
        contradiction_bucket = "high" if int(bet.get("contradictions_found") or 0) >= 3 else "mid" if int(bet.get("contradictions_found") or 0) >= 1 else "low"
        trade_class_bucket = bet.get("trade_class", "core")
        learning_bucket = "high" if safe_float(bet.get("learning_velocity_score"), 0.0) >= 0.7 else "mid" if safe_float(bet.get("learning_velocity_score"), 0.0) >= 0.45 else "low"
        time_bucket = bet.get("feedback_time_bucket") or bucket_time_to_feedback(safe_float(bet.get("time_to_resolution_hours"), 9999))
        mispricing_type = bet.get("mispricing_type", "unknown")
        confidence_stats[confidence_bucket]["total"] += 1
        edge_stats[edge_bucket_name]["total"] += 1
        source_quality_stats[source_bucket]["total"] += 1
        evidence_stats[evidence_bucket]["total"] += 1
        contradiction_stats[contradiction_bucket]["total"] += 1
        exploratory_stats[trade_class_bucket]["total"] += 1
        learning_velocity_stats[learning_bucket]["total"] += 1
        time_bucket_stats[time_bucket]["total"] += 1
        mispricing_stats[mispricing_type]["total"] += 1
        mispricing_stats[mispricing_type]["pnl"] += pnl
        if bet.get("status") == "won":
            confidence_stats[confidence_bucket]["won"] += 1
            edge_stats[edge_bucket_name]["won"] += 1
            source_quality_stats[source_bucket]["won"] += 1
            evidence_stats[evidence_bucket]["won"] += 1
            contradiction_stats[contradiction_bucket]["won"] += 1
            exploratory_stats[trade_class_bucket]["won"] += 1
            learning_velocity_stats[learning_bucket]["won"] += 1
            time_bucket_stats[time_bucket]["won"] += 1
            mispricing_stats[mispricing_type]["won"] += 1
        created = bet.get("created_at")
        resolved_at = bet.get("resolved_at")
        if created and resolved_at:
            hold_hours.append(hours_between(created, resolved_at))
        if bet.get("resolved_reason") in ("take_profit", "stop_loss", "trailing_exit"):
            early_feedback_count += 1
            capital_reused_early += safe_float(bet.get("amount"), 0.0)
    top_winning_patterns = Counter({key: round(value, 2) for key, value in by_thesis.items() if value > 0}).most_common(3)
    top_losing_patterns = Counter({key: round(abs(value), 2) for key, value in by_thesis.items() if value < 0}).most_common(3)
    overlap_concentration = round(max(snapshot["category_exposure"].values(), default=0.0) / max(snapshot["committed"], 1.0), 4) if snapshot["committed"] else 0.0
    return {
        "balance": snapshot["free_balance"],
        "capital_committed": snapshot["committed"],
        "capital_free": snapshot["free_balance"],
        "portfolio_exposure": round(snapshot["committed"] / max(snapshot["total_equity"], 1.0), 4),
        "portfolio_exposure_by_category": {k: round(v, 2) for k, v in snapshot["category_exposure"].items()},
        "portfolio_exposure_by_thesis_type": {k: round(v, 2) for k, v in snapshot["thesis_exposure"].items()},
        "portfolio_exposure_by_side": {k: round(v, 2) for k, v in snapshot["side_exposure"].items()},
        "portfolio_exposure_by_tier": {k: round(v, 2) for k, v in snapshot["tier_exposure"].items()},
        "portfolio_exposure_by_horizon": {k: round(v, 2) for k, v in snapshot["horizon_exposure"].items()},
        "open": len(open_bets),
        "open_current_lab": len(open_bets),
        "legacy_trades_archived": len(legacy_bets),
        "won": int(get_state("won", 0)),
        "lost": int(get_state("lost", 0)),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": round(realized_pnl + unrealized_pnl, 2),
        "pnl_by_category": {k: round(v, 2) for k, v in by_category.items()},
        "pnl_by_thesis_type": {k: round(v, 2) for k, v in by_thesis.items()},
        "pnl_by_trade_class": {k: round(v, 2) for k, v in by_trade_class.items()},
        "pnl_by_tier": {k: round(v, 2) for k, v in by_tier.items()},
        "winrate_by_confidence_bucket": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in confidence_stats.items()},
        "winrate_by_edge_bucket": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in edge_stats.items()},
        "winrate_by_source_quality": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in source_quality_stats.items()},
        "winrate_by_evidence_strength": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in evidence_stats.items()},
        "winrate_by_contradiction_level": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in contradiction_stats.items()},
        "winrate_core_vs_exploratory": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in exploratory_stats.items()},
        "winrate_by_learning_velocity": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in learning_velocity_stats.items()},
        "winrate_by_time_to_resolution_bucket": {k: f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—" for k, v in time_bucket_stats.items()},
        "performance_by_mispricing_type": {k: {"winrate": f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—", "pnl": round(v['pnl'], 2)} for k, v in mispricing_stats.items()},
        "average_hold_time_hours": round(mean(hold_hours), 2),
        "average_time_to_feedback_hours": round(mean(hold_hours), 2),
        "early_feedback_pct": round((early_feedback_count / max(1, len(realized))) * 100, 1),
        "capital_reused_by_early_closure": round(capital_reused_early, 2),
        "pnl_per_day_proxy": round(realized_pnl / max(1.0, mean(hold_hours, 24.0) / 24.0), 2),
        "top_winning_patterns": top_winning_patterns,
        "top_losing_patterns": top_losing_patterns,
        "markets_analyzed_last_cycle": int(get_state("markets_analyzed_last_cycle", 0)),
        "discarded_low_evidence_last_cycle": int(get_state("discarded_low_evidence_last_cycle", 0)),
        "discarded_correlation_last_cycle": int(get_state("discarded_correlation_last_cycle", 0)),
        "passed_to_portfolio_last_cycle": int(get_state("passed_to_portfolio_last_cycle", 0)),
        "positions_per_cycle_last": int(get_state("passed_to_portfolio_last_cycle", 0)),
        "watchlist_last_cycle": int(get_state("watchlist_last_cycle", 0)),
        "selected_core_last_cycle": int(get_state("selected_core_last_cycle", 0)),
        "selected_secondary_last_cycle": int(get_state("selected_secondary_last_cycle", 0)),
        "selected_exploratory_last_cycle": int(get_state("selected_exploratory_last_cycle", 0)),
        "selection_mix_last_cycle": {
            "selected": int(get_state("passed_to_portfolio_last_cycle", 0)),
            "watchlist": int(get_state("watchlist_last_cycle", 0)),
            "rejected": max(0, int(get_state("markets_analyzed_last_cycle", 0)) - int(get_state("watchlist_last_cycle", 0)) - int(get_state("passed_to_portfolio_last_cycle", 0))),
        },
        "current_lab_epoch": get_current_lab_epoch(),
        "current_strategy_version": get_current_strategy_version(),
        "paper_starting_balance": get_paper_starting_balance(),
        "average_bets_per_cycle": round(int(get_state("bets_placed", 0)) / max(1, int(get_state("cycles_run", 0))), 2),
        "core_open": snapshot["core_open"],
        "secondary_open": snapshot["secondary_open"],
        "experimental_open": snapshot["experimental_open"],
        "coverage_breadth": len(snapshot["category_exposure"]),
        "overlap_concentration": overlap_concentration,
        "capital_efficiency": round((realized_pnl + unrealized_pnl) / max(snapshot["committed"], 1.0), 4) if snapshot["committed"] else 0.0,
    }


@app.route("/bot-bet", methods=["POST"])
def bot_bet():
    try:
        result = run_bot_cycle()
        placed = result["placed"]
        summary = LAST_CYCLE_DATA.get("summary", {})
        if not placed:
            return jsonify({"message": summary.get("headline", f"Sin trades nuevos. Analizados {result['analyzed']}, shortlist {result['shortlisted']}, watchlist {result.get('watchlist', 0)}."), "reasoning": " | ".join(f"{key}: {value}" for key, value in list(summary.get("blockers", {}).items())[:3]), "placed": 0, "cycle_id": result["cycle_id"]})
        return jsonify({"message": summary.get("headline", f"Portfolio actualizado: {len(placed)} trades nuevos."), "reasoning": "; ".join([bet.get("reasoning", "") for bet in placed[:4]]), "placed": len(placed), "cycle_id": result["cycle_id"]})
    except Exception as exc:
        logger.exception("bot cycle failed")
        return jsonify({"message": f"Error: {exc}", "reasoning": ""}), 500


@app.route("/monitor", methods=["POST"])
def manual_monitor():
    threading.Thread(target=monitor_open_positions, daemon=True).start()
    return jsonify({"ok": True, "message": "Monitor ejecutado"})


@app.route("/metrics")
def metrics():
    return jsonify(aggregate_metrics())


@app.route("/markets")
def markets_preview():
    try:
        markets = fetch_active_markets(MARKETS_PREVIEW_LIMIT)
        preview = []
        for market in markets[:MARKETS_PREVIEW_LIMIT]:
            if not market.get("active") or market.get("closed"):
                continue
            try:
                prob = get_yes_probability(market)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            preview.append({"question": normalize_question(market.get("question", ""))[:90], "prob": round(prob * 100), "volume": f"${round(safe_float(market.get('volume', 0)) / 1000)}K vol"})
        return jsonify(preview)
    except Exception:
        logger.exception("markets preview failed")
        return jsonify([])


@app.route("/bets")
def bets_endpoint():
    result = []
    for bet in get_current_lab_bets()[:24]:
        pnl = safe_float(bet.get("pnl"), 0.0)
        result.append({
            "question": bet.get("question"),
            "side": bet.get("side"),
            "amount": round(safe_float(bet.get("amount"), 0.0), 2),
            "pnl": pnl,
            "pnl_text": "—" if bet.get("status") == "open" else f"{('+' if pnl > 0 else '')}{round(pnl, 2)} USDC",
            "price_entry": round(safe_float(bet.get("price_entry"), 0.0), 3),
            "price_current": round(safe_float(bet.get("price_current"), 0.0), 3),
            "status": bet.get("status"),
            "status_text": {"open": "abierta", "won": "ganada", "lost": "perdida", "lab_reset_archived": "archivada"}.get(bet.get("status"), bet.get("status")),
            "edge": round(safe_float(bet.get("edge"), 0.0) * 100, 1),
            "confidence": bet.get("confidence", 0),
            "source_quality": round(safe_float(bet.get("source_quality_score"), 0.0) * 100, 1),
            "source_diversity": round(safe_float(bet.get("source_diversity_score"), 0.0) * 100, 1),
            "factual_strength": round(safe_float(bet.get("factual_strength"), 0.0) * 100, 1),
            "evidence_strength": round(safe_float(bet.get("evidence_strength"), 0.0) * 100, 1),
            "score": round(safe_float(bet.get("composite_score"), 0.0) * 100, 1),
            "opportunity_score": round(safe_float(bet.get("opportunity_score"), 0.0) * 100, 1),
            "portfolio_priority_score": round(safe_float(bet.get("portfolio_priority_score"), 0.0) * 100, 1),
            "mispricing_score": round(safe_float(bet.get("mispricing_score"), 0.0) * 100, 1),
            "ease_of_win": round(safe_float(bet.get("ease_of_win_score"), 0.0) * 100, 1),
            "learning_velocity": round(safe_float(bet.get("learning_velocity_score"), 0.0) * 100, 1),
            "market_learnability": round(safe_float(bet.get("market_learnability_score"), 0.0) * 100, 1),
            "reliability": round(safe_float(bet.get("conclusion_reliability_score"), 0.0) * 100, 1),
            "contradictions": int(bet.get("contradictions_found") or 0),
            "uncertainty": round(safe_float(bet.get("uncertainty_score"), 0.0) * 100, 1),
            "category": bet.get("category", "general"),
            "thesis_type": bet.get("thesis_type", "?"),
            "mispricing_type": bet.get("mispricing_type", "?"),
            "trade_class": bet.get("trade_class", "core"),
            "tier": bet.get("tier", "TIER_C"),
            "selection_bucket": bet.get("selection_bucket", "selected_now"),
            "strategy_version": bet.get("strategy_version", "legacy"),
            "lab_epoch": bet.get("lab_epoch", "legacy"),
            "key_signal": bet.get("key_signal", ""),
            "invalidation_condition": bet.get("invalidation_condition", ""),
            "time_bucket": bet.get("feedback_time_bucket", ""),
            "horizon_bucket": bet.get("horizon_bucket", ""),
            "reasoning": bet.get("reasoning", ""),
            "prob_market": safe_float(bet.get("prob_market"), 0.0),
        })
    return jsonify(result)


@app.route("/performance")
def performance():
    return jsonify(aggregate_metrics())


@app.route("/research-preview")
def research_preview():
    preview = []
    for item in LAST_CYCLE_DATA["shortlist"][:8]:
        packet = item.get("packet", {})
        preview.append({
            "question": item.get("question"),
            "category": item.get("category"),
            "thesis_type": item.get("thesis_type"),
            "source_quality_score": packet.get("source_quality_score"),
            "source_diversity_score": packet.get("source_diversity_score"),
            "factual_strength": packet.get("factual_strength"),
            "mispricing_flags": packet.get("mispricing_flags"),
            "mispricing_score": packet.get("mispricing_score"),
            "learning_velocity_score": packet.get("learning_velocity_score"),
            "market_learnability_score": packet.get("market_learnability_score"),
            "external_match_confidence": packet.get("external_match_confidence"),
            "microstructure_quality_score": packet.get("microstructure_quality_score"),
            "contradiction_summary": packet.get("contradiction_summary"),
            "missing_data_flags": packet.get("missing_data_flags"),
            "final_evidence_strength": packet.get("final_evidence_strength"),
            "research_packet": packet,
        })
    return jsonify({"cycle_id": LAST_CYCLE_DATA["cycle_id"], "items": preview})


@app.route("/candidate-scores")
def candidate_scores():
    return jsonify({
        "cycle_id": LAST_CYCLE_DATA["cycle_id"],
        "candidates": LAST_CYCLE_DATA["candidates"],
        "shortlist": LAST_CYCLE_DATA["shortlist"],
        "selected": LAST_CYCLE_DATA["selected"],
        "selected_now": LAST_CYCLE_DATA["selected"],
        "watchlist": LAST_CYCLE_DATA["watchlist"],
        "watchlist_high_potential": LAST_CYCLE_DATA["watchlist"],
        "rejected": LAST_CYCLE_DATA["rejected"],
        "rejected_low_quality": LAST_CYCLE_DATA["rejected"],
        "summary": LAST_CYCLE_DATA["summary"],
        "blockers": LAST_CYCLE_DATA["blockers"],
    })


@app.route("/watchlist")
def watchlist_endpoint():
    return jsonify({"cycle_id": LAST_CYCLE_DATA["cycle_id"], "items": LAST_CYCLE_DATA["watchlist"]})


@app.route("/legacy-summary")
def legacy_summary():
    legacy_bets = get_legacy_bets()
    return jsonify({
        "current_lab_epoch": get_current_lab_epoch(),
        "legacy_trades": len(legacy_bets),
        "legacy_open_like": sum(1 for bet in legacy_bets if bet.get("status") in ("open", "lab_reset_archived")),
        "legacy_by_status": dict(Counter(bet.get("status", "unknown") for bet in legacy_bets)),
        "legacy_by_strategy_version": dict(Counter(bet.get("strategy_version", "legacy") for bet in legacy_bets)),
    })


@app.route("/portfolio-debug")
def portfolio_debug():
    snapshot = current_portfolio_snapshot()
    return jsonify({
        "current_lab_epoch": get_current_lab_epoch(),
        "current_strategy_version": get_current_strategy_version(),
        "core_open": snapshot["core_open"],
        "secondary_open": snapshot["secondary_open"],
        "experimental_open": snapshot["experimental_open"],
        "legacy_trades_archived": len(get_legacy_bets()),
        "exposure_by_category": snapshot["category_exposure"],
        "exposure_by_thesis": snapshot["thesis_exposure"],
        "exposure_by_horizon": snapshot["horizon_exposure"],
        "exposure_by_tier": snapshot["tier_exposure"],
    })


@app.route("/analysis-debug")
def analysis_debug():
    debug_items = []
    for item in LAST_CYCLE_DATA["shortlist"][:10]:
        debug_items.append({
            "question": item.get("question"),
            "edge": item.get("edge"),
            "compound_score": item.get("compound_score"),
            "portfolio_priority_score": item.get("portfolio_priority_score"),
            "tier": item.get("tier"),
            "horizon_bucket": item.get("horizon_bucket"),
            "conclusion_reliability_score": item.get("conclusion_reliability_score"),
            "analysis": item.get("analysis"),
            "research_packet": item.get("packet"),
        })
    return jsonify({"cycle_id": LAST_CYCLE_DATA["cycle_id"], "items": debug_items})


def bet_loop():
    while True:
        time.sleep(BET_LOOP_INTERVAL_SECONDS)
        try:
            with app.test_request_context():
                bot_bet()
        except Exception:
            logger.exception("bet_loop failed")


def monitor_loop():
    while True:
        time.sleep(MONITOR_LOOP_INTERVAL_SECONDS)
        try:
            monitor_open_positions()
        except Exception:
            logger.exception("monitor_loop failed")


def start_background_loops():
    global BACKGROUND_LOOPS_STARTED
    if not ENABLE_BACKGROUND_LOOPS:
        logger.info("Background loops disabled; set ENABLE_BACKGROUND_LOOPS=true to enable them")
        return False
    with BACKGROUND_LOOPS_LOCK:
        if BACKGROUND_LOOPS_STARTED:
            return False
        threading.Thread(target=bet_loop, daemon=True, name="bet-loop").start()
        threading.Thread(target=monitor_loop, daemon=True, name="monitor-loop").start()
        BACKGROUND_LOOPS_STARTED = True
        return True

# ── DASHBOARD / MISC ENDPOINTS ───────────────────────────────
HTML = """<!DOCTYPE html>
<html>
<head>
<title>Polymarket Research Lab</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#080b11;--panel:#101620;--panel-soft:#141c28;--line:#242f3d;--text:#edf2f7;--muted:#8b96a8;--soft:#b9c2cf;--accent:#87e7c0;--accent-2:#8dbbff;--warn:#f0ce7a;--danger:#ff8b8b}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,rgba(83,118,173,.18),transparent 30%),linear-gradient(180deg,#070a10,#0b1017);color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}
.app-shell{max-width:1360px;margin:0 auto;padding:28px 20px 42px}
.topbar{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:20px}
.title-block h1{margin:0;font-size:30px;letter-spacing:-.04em}
.title-block p{margin:10px 0 0;color:var(--muted);max-width:760px;line-height:1.55}
.pill-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.pill{padding:8px 12px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.03);font-size:12px;color:var(--soft)}
.actions{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}
.btn{padding:10px 14px;border-radius:12px;border:1px solid var(--line);background:var(--panel);color:var(--text);cursor:pointer;font-weight:700}
.btn:hover{transform:translateY(-1px)}
.btn-primary{background:linear-gradient(135deg,#97e6c4,#63ceb0);color:#06130d;border-color:transparent}
.btn-secondary{background:linear-gradient(135deg,#9dc5ff,#7194f5);color:#0a1120;border-color:transparent}
.btn-danger{background:linear-gradient(135deg,#ff9c9c,#ff7676);color:#260808;border-color:transparent}
.dashboard{display:grid;grid-template-columns:2fr 1fr;gap:18px}
.column{display:flex;flex-direction:column;gap:18px}
.panel{background:linear-gradient(180deg,rgba(18,24,33,.98),rgba(14,19,27,.98));border:1px solid var(--line);border-radius:22px;padding:18px}
.hero{display:grid;grid-template-columns:1.3fr .9fr;gap:16px}
.hero-card,.stat,.mini-stat,.trade-card,.watch-card{background:var(--panel-soft);border:1px solid rgba(255,255,255,.05);border-radius:18px}
.hero-card{padding:20px}
.eyebrow,.section-kicker{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted)}
.hero-value{font-size:34px;letter-spacing:-.05em;margin-top:10px}
.hero-copy{margin-top:10px;color:var(--soft);font-size:14px;line-height:1.55}
.status-strip{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-top:16px;padding-top:14px;border-top:1px solid rgba(255,255,255,.06)}
.status-badge,.badge{display:inline-flex;align-items:center;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:700;border:1px solid rgba(255,255,255,.06);background:#1b2230;color:#d1dae5}
.status-badge{padding:8px 12px;color:var(--accent);background:rgba(135,231,192,.08);border-color:rgba(135,231,192,.2)}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat{padding:16px}
.stat-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em}
.stat-value{margin-top:9px;font-size:28px;letter-spacing:-.04em}
.stat-note{margin-top:8px;color:var(--soft);font-size:12px;line-height:1.45}
.positive{color:var(--accent)}.negative{color:var(--danger)}.neutral{color:var(--soft)}
.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:14px}
.section-title{font-size:18px;font-weight:700;letter-spacing:-.02em}
.section-sub{margin-top:4px;color:var(--muted);font-size:13px}
.cycle-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:14px}
.mini-stat{padding:14px}
.mini-stat strong{display:block;font-size:22px;margin-top:6px}
.message-card{padding:16px;border-radius:16px;background:rgba(135,231,192,.08);border:1px solid rgba(135,231,192,.14);color:#e4faf1;line-height:1.6}
.split{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.list{display:grid;gap:12px}
.trade-card,.watch-card{padding:16px}
.trade-top,.watch-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.trade-q,.watch-q{font-size:15px;font-weight:700;line-height:1.45}
.badge-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.core{background:rgba(135,231,192,.12);color:#90e8c7}.secondary{background:rgba(141,187,255,.14);color:#a3caff}.experimental{background:rgba(240,206,122,.15);color:#f1d891}
.trade-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}
.meta-box{padding:10px 12px;border-radius:14px;background:#0f151f;border:1px solid rgba(255,255,255,.04)}
.meta-box span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.11em;margin-bottom:6px}
.meta-box strong{font-size:13px;color:var(--text);line-height:1.45}
.trade-foot,.watch-foot{margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.05);font-size:13px;color:var(--soft);line-height:1.55}
.reason-list,.metric-list{display:grid;gap:8px}
.reason-item,.metric-item{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px;color:var(--soft)}
.reason-item:last-child,.metric-item:last-child{border-bottom:none}
.empty{padding:28px 18px;border-radius:18px;border:1px dashed rgba(255,255,255,.08);text-align:center;color:var(--muted);background:rgba(255,255,255,.02)}
details{border-top:1px solid rgba(255,255,255,.06);padding-top:14px}
details:first-of-type{border-top:none;padding-top:0}
summary{cursor:pointer;font-weight:700}
.summary-copy{margin-top:10px;font-size:13px;color:var(--soft);line-height:1.6}
@media(max-width:1180px){.dashboard,.hero,.split{grid-template-columns:1fr}.stat-grid{grid-template-columns:repeat(2,1fr)}.cycle-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.app-shell{padding:18px 14px 28px}.topbar{flex-direction:column}.actions{justify-content:flex-start}.stat-grid,.cycle-grid,.trade-grid,.split{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app-shell">
  <div class="topbar">
    <div class="title-block">
      <h1>Polymarket Research Lab</h1>
      <p>Dashboard operativo para entender rápido el estado del laboratorio, el capital, las oportunidades detectadas y el comportamiento del bot en el último ciclo.</p>
      <div class="pill-row">
        <div class="pill" id="lab-pill">Lab activo: —</div>
        <div class="pill" id="strategy-pill">Strategy: —</div>
        <div class="pill" id="bankroll-pill">Bankroll inicial: —</div>
        <div class="pill" id="legacy-pill">Legacy archivado: —</div>
      </div>
    </div>
    <div class="actions">
      <button class="btn" onclick="loadAll()">Actualizar</button>
      <button class="btn" onclick="doMonitor()">Monitor</button>
      <button class="btn btn-primary" onclick="runCycle()">Correr ciclo</button>
      <button class="btn btn-secondary" onclick="fundPaper()">Fund paper</button>
      <button class="btn btn-danger" onclick="resetLab()">Reset lab</button>
    </div>
  </div>

  <div class="dashboard">
    <div class="column">
      <div class="panel hero">
        <div class="hero-card">
          <div class="eyebrow">Estado general</div>
          <div class="hero-value" id="bot-status">Bot listo</div>
          <div class="hero-copy" id="bot-reasoning">Esperando datos del laboratorio actual.</div>
          <div class="status-strip">
            <div>
              <div class="eyebrow">Último ciclo</div>
              <div class="hero-copy" id="cycle-message">Todavía no hay resumen del último ciclo.</div>
            </div>
            <div class="status-badge" id="live-tag">En espera</div>
          </div>
        </div>
        <div class="hero-card">
          <div class="eyebrow">Salud del laboratorio</div>
          <div class="hero-value" id="health-score">0%</div>
          <div class="hero-copy" id="health-summary">Sin datos todavía para evaluar throughput, coverage y uso del capital.</div>
        </div>
      </div>

      <div class="stat-grid">
        <div class="stat"><div class="stat-label">Capital libre</div><div class="stat-value" id="capital-free">$0</div><div class="stat-note">Caja disponible para nuevas entradas.</div></div>
        <div class="stat"><div class="stat-label">Capital comprometido</div><div class="stat-value" id="capital-committed">$0</div><div class="stat-note">Capital hoy desplegado en trades abiertos.</div></div>
        <div class="stat"><div class="stat-label">Exposure</div><div class="stat-value" id="portfolio-exposure">0%</div><div class="stat-note">Uso actual del capital del lab.</div></div>
        <div class="stat"><div class="stat-label">PnL total</div><div class="stat-value" id="total-pnl">0</div><div class="stat-note">Realizado + unrealized del epoch activo.</div></div>
        <div class="stat"><div class="stat-label">Trades activos</div><div class="stat-value" id="open-trades">0</div><div class="stat-note">Posiciones abiertas del portfolio actual.</div></div>
        <div class="stat"><div class="stat-label">Mix operativo</div><div class="stat-value" id="core-exp">0 / 0 / 0</div><div class="stat-note">Core / Secondary / Exploratory.</div></div>
        <div class="stat"><div class="stat-label">Último ciclo</div><div class="stat-value" id="cycle-stats">0 / 0</div><div class="stat-note">Analizados / enviados a portfolio.</div></div>
        <div class="stat"><div class="stat-label">Watchlist</div><div class="stat-value" id="watchlist-count">0</div><div class="stat-note">Prometedoras pero todavía sin entrada.</div></div>
      </div>

      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Último ciclo</div>
            <div class="section-title">Qué hizo el bot</div>
            <div class="section-sub">Resumen claro del escaneo, la selección y los motivos de no entrada.</div>
          </div>
        </div>
        <div class="cycle-grid">
          <div class="mini-stat"><div class="eyebrow">Analizados</div><strong id="cycle-analyzed">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Shortlist</div><strong id="cycle-shortlist">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Portfolio</div><strong id="cycle-selected">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Watchlist</div><strong id="cycle-watchlist">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Rechazados</div><strong id="cycle-rejected">0</strong></div>
        </div>
        <div class="split">
          <div class="panel" style="padding:14px">
            <div class="section-kicker">Mix del ciclo</div>
            <div class="metric-list" id="cycle-mix"><div class="metric-item"><span>Sin datos</span><strong>—</strong></div></div>
          </div>
          <div class="panel" style="padding:14px">
            <div class="section-kicker">Motivos de no entrada</div>
            <div class="reason-list" id="blockers"><div class="reason-item"><span>Sin bloqueos todavía</span><strong>—</strong></div></div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Portfolio actual</div>
            <div class="section-title">Trades abiertos</div>
            <div class="section-sub">Visión clara del capital desplegado, calidad de cada trade y su invalidación.</div>
          </div>
        </div>
        <div class="list" id="bets"><div class="empty">Todavía no hay trades en este laboratorio.</div></div>
      </div>
    </div>

    <div class="column">
      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Watchlist</div>
            <div class="section-title">Candidatos prometedores</div>
            <div class="section-sub">Para distinguir si no apostó porque no encontró nada o porque todavía está esperando mejor entrada.</div>
          </div>
        </div>
        <div class="list" id="watchlist"><div class="empty">No hay candidatos en watchlist en este ciclo.</div></div>
      </div>

      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Salud y métricas</div>
            <div class="section-title">Resumen del laboratorio</div>
            <div class="section-sub">Primero lo importante; abajo el detalle más técnico cuando haga falta.</div>
          </div>
        </div>
        <details open><summary>Performance summary</summary><div class="summary-copy" id="perf-summary">Cargando…</div></details>
        <details><summary>Portfolio mix</summary><div class="summary-copy" id="mix-summary">Cargando…</div></details>
        <details><summary>Learning metrics</summary><div class="summary-copy" id="learning-summary">Cargando…</div></details>
        <details><summary>Winning / losing patterns</summary><div class="summary-copy" id="pattern-summary">Cargando…</div></details>
        <details><summary>Debug summary</summary><div class="summary-copy" id="debug-summary">Cargando…</div></details>
      </div>
    </div>
  </div>
</div>
<script>
function money(value){return '$'+Math.round(value||0).toLocaleString('en-US')}
function pct(value){return Math.round((value||0)*100)+'%'}
function metricClass(value){return value>0?'positive':value<0?'negative':'neutral'}
function titleCase(value){return (value||'—').replaceAll('_',' ')}
function objectLines(obj, empty='—'){const entries=Object.entries(obj||{});if(!entries.length)return empty;return entries.map(([k,v])=>`${titleCase(k)}: ${typeof v==='object'?JSON.stringify(v):v}`).join('<br>')}
async function postJson(url,payload){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})});return res.json()}

function setValue(id,text,raw){const el=document.getElementById(id);el.textContent=text;if(raw!==undefined){el.className=(el.className.includes('hero-value')?'hero-value ':'stat-value ')+metricClass(raw)}}

function renderTradeCard(b){return `<div class='trade-card'><div class='trade-top'><div><div class='trade-q'>${b.question}</div><div class='badge-row'><span class='badge ${b.trade_class}'>${b.trade_class}</span><span class='badge'>${b.tier}</span><span class='badge'>${b.horizon_bucket||'—'}</span><span class='badge'>${b.category}</span></div></div><div class='badge'>${b.status_text}</div></div><div class='trade-grid'><div class='meta-box'><span>Posición</span><strong>${b.side} · ${money(b.amount)}</strong></div><div class='meta-box'><span>PnL</span><strong class='${metricClass(b.pnl||0)}'>${b.pnl_text}</strong></div><div class='meta-box'><span>Entry / Current</span><strong>${b.price_entry||0} / ${b.price_current||0}</strong></div><div class='meta-box'><span>Edge / Confidence</span><strong>${b.edge}pp · ${b.confidence}/10</strong></div><div class='meta-box'><span>Reliability / Ease</span><strong>${b.reliability}% · ${b.ease_of_win}%</strong></div><div class='meta-box'><span>Priority / Bucket</span><strong>${b.portfolio_priority_score}% · ${titleCase(b.selection_bucket)}</strong></div></div><div class='trade-foot'><strong>Señal clave:</strong> ${b.key_signal||'—'}<br><strong>Invalidación:</strong> ${b.invalidation_condition||'—'}<br><strong>Racional:</strong> ${b.reasoning||'—'}</div></div>`}
function renderWatchCard(item){return `<div class='watch-card'><div class='watch-top'><div><div class='watch-q'>${item.question}</div><div class='badge-row'><span class='badge ${item.trade_class||'watch'}'>${item.trade_class||'watchlist'}</span><span class='badge'>${item.tier||'—'}</span><span class='badge'>${item.horizon_bucket||'—'}</span></div></div></div><div class='trade-grid'><div class='meta-box'><span>Priority</span><strong>${Math.round((item.portfolio_priority_score||0)*100)}%</strong></div><div class='meta-box'><span>Opportunity</span><strong>${Math.round((item.opportunity_score||0)*100)}%</strong></div><div class='meta-box'><span>Reliability</span><strong>${Math.round((item.reliability||0)*100)}%</strong></div><div class='meta-box'><span>Estado</span><strong>${titleCase(item.selection_bucket||'watchlist_high_potential')}</strong></div></div><div class='watch-foot'>${item.reason||'Necesita un poco más de prioridad o espacio en portfolio antes de entrar.'}</div></div>`}

async function loadMetrics(){const d=await fetch('/metrics').then(r=>r.json());document.getElementById('lab-pill').textContent=`Lab activo: ${d.current_lab_epoch||'—'}`;document.getElementById('strategy-pill').textContent=`Strategy: ${d.current_strategy_version||'—'}`;document.getElementById('bankroll-pill').textContent=`Bankroll inicial: ${money(d.paper_starting_balance)}`;document.getElementById('legacy-pill').textContent=`Legacy archivado: ${d.legacy_trades_archived||0}`;setValue('capital-free',money(d.capital_free),d.capital_free);setValue('capital-committed',money(d.capital_committed),-d.capital_committed);setValue('portfolio-exposure',pct(d.portfolio_exposure),(d.portfolio_exposure||0)<0.55?1:-1);setValue('total-pnl',(d.total_pnl>=0?'+':'')+Math.round(d.total_pnl||0),d.total_pnl||0);document.getElementById('open-trades').textContent=d.open_current_lab||0;document.getElementById('core-exp').textContent=`${d.core_open||0} / ${d.secondary_open||0} / ${d.experimental_open||0}`;document.getElementById('cycle-stats').textContent=`${d.markets_analyzed_last_cycle||0} / ${d.positions_per_cycle_last||0}`;document.getElementById('watchlist-count').textContent=d.watchlist_last_cycle||0;const health=Math.min(100,Math.round((1-(d.overlap_concentration||0))*25 + (1-Math.abs((d.portfolio_exposure||0)-0.42))*25 + Math.min((d.positions_per_cycle_last||0)/10,1)*20 + Math.min((d.watchlist_last_cycle||0)/8,1)*10 + Math.min((d.coverage_breadth||0)/6,1)*20));setValue('health-score',health+'%',health-50);document.getElementById('health-summary').textContent=`Capital libre ${money(d.capital_free)} · comprometido ${money(d.capital_committed)} · ${d.open_current_lab||0} trades abiertos · avg bets/cycle ${d.average_bets_per_cycle||0}.`;document.getElementById('perf-summary').innerHTML=`PnL total <strong>${money(d.total_pnl)}</strong>. Realizado <strong>${money(d.realized_pnl)}</strong>, unrealized <strong>${money(d.unrealized_pnl)}</strong>. Hold medio <strong>${d.average_hold_time_hours||0}h</strong> y feedback temprano en <strong>${d.early_feedback_pct||0}%</strong> de los trades cerrados.`;document.getElementById('mix-summary').innerHTML=`Exposure por categoría:<br>${objectLines(d.portfolio_exposure_by_category,'Todavía no hay exposición activa.')}<br><br>Exposure por horizon:<br>${objectLines(d.portfolio_exposure_by_horizon,'Todavía no hay posiciones abiertas.')}`;document.getElementById('learning-summary').innerHTML=`Winrate por learning velocity:<br>${objectLines(d.winrate_by_learning_velocity,'Aún no hay historial suficiente.')}<br><br>Winrate por time bucket:<br>${objectLines(d.winrate_by_time_to_resolution_bucket,'Aún no hay buckets suficientes.')}`;document.getElementById('pattern-summary').innerHTML=`Top winning patterns: ${JSON.stringify(d.top_winning_patterns||[])}<br>Top losing patterns: ${JSON.stringify(d.top_losing_patterns||[])}<br><br>PnL por tier:<br>${objectLines(d.pnl_by_tier,'Todavía no hay PnL por tier.')}`;document.getElementById('debug-summary').innerHTML=`Legacy archivados: <strong>${d.legacy_trades_archived||0}</strong><br>Descartados por evidencia: <strong>${d.discarded_low_evidence_last_cycle||0}</strong><br>Descartados por correlación/exposure: <strong>${d.discarded_correlation_last_cycle||0}</strong><br>Selected / watchlist / rejected: <strong>${(d.selection_mix_last_cycle||{}).selected||0}</strong> / <strong>${(d.selection_mix_last_cycle||{}).watchlist||0}</strong> / <strong>${(d.selection_mix_last_cycle||{}).rejected||0}</strong>`}
async function loadCycle(){const d=await fetch('/candidate-scores').then(r=>r.json());const s=d.summary||{};document.getElementById('cycle-message').textContent=s.headline||'Todavía no hay resumen del último ciclo.';document.getElementById('cycle-analyzed').textContent=s.analyzed||0;document.getElementById('cycle-shortlist').textContent=s.shortlist||0;document.getElementById('cycle-selected').textContent=s.selected||0;document.getElementById('cycle-watchlist').textContent=s.watchlist||0;document.getElementById('cycle-rejected').textContent=s.rejected||0;document.getElementById('cycle-mix').innerHTML=`<div class='metric-item'><span>Core</span><strong>${s.core_selected||0}</strong></div><div class='metric-item'><span>Secondary</span><strong>${s.secondary_selected||0}</strong></div><div class='metric-item'><span>Exploratory</span><strong>${s.exploratory_selected||0}</strong></div>`;const blockers=Object.entries(d.blockers||{});document.getElementById('blockers').innerHTML=blockers.length?blockers.map(([k,v])=>`<div class='reason-item'><span>${titleCase(k)}</span><strong>${v}</strong></div>`).join(''):"<div class='reason-item'><span>No hubo bloqueos relevantes en el último ciclo.</span><strong>OK</strong></div>";document.getElementById('watchlist').innerHTML=(d.watchlist||[]).length?(d.watchlist||[]).slice(0,8).map(renderWatchCard).join(''):"<div class='empty'>No hay candidatos en watchlist en este ciclo.</div>";document.getElementById('live-tag').textContent=(s.selected||0)>0?'Operando':(s.watchlist||0)>0?'Observando':'En espera';document.getElementById('bot-status').textContent=(s.selected||0)>0?'Bot operando':(s.watchlist||0)>0?'Bot viendo oportunidades':'Bot en espera';document.getElementById('bot-reasoning').textContent=s.headline||'Todavía no hay actividad reciente suficiente.'}
async function loadBets(){const d=await fetch('/bets').then(r=>r.json());document.getElementById('bets').innerHTML=d.length?d.map(renderTradeCard).join(''):"<div class='empty'>Todavía no hay trades en este laboratorio.</div>"}
async function runCycle(){document.getElementById('bot-status').textContent='Corriendo ciclo';document.getElementById('bot-reasoning').textContent='Investigando mercados, armando ranking y evaluando entradas.';const d=await fetch('/bot-bet',{method:'POST'}).then(r=>r.json());document.getElementById('bot-status').textContent=d.placed?'Bot operando':'Bot en espera';document.getElementById('bot-reasoning').textContent=d.message||d.reasoning||'';await loadAll()}
async function doMonitor(){document.getElementById('bot-status').textContent='Monitoreando portfolio';const d=await fetch('/monitor',{method:'POST'}).then(r=>r.json());document.getElementById('bot-reasoning').textContent=d.message||'Monitor ejecutado';await loadAll()}
async function resetLab(){if(!confirm('Esto archivará el laboratorio actual y arrancará uno nuevo. ¿Continuar?'))return;const balance=prompt('Balance inicial del nuevo lab','50000');const d=await postJson('/lab-reset',{balance:Number(balance||50000)});document.getElementById('bot-status').textContent=d.ok?'Lab reseteado':'Error al resetear';document.getElementById('bot-reasoning').textContent=d.message||d.error||'';await loadAll()}
async function fundPaper(){const amount=prompt('Capital paper a agregar','10000');if(!amount)return;const d=await postJson('/fund-paper',{amount:Number(amount)});document.getElementById('bot-status').textContent=d.ok?'Capital agregado':'No se pudo agregar capital';document.getElementById('bot-reasoning').textContent=d.message||d.error||'';await loadAll()}
async function loadAll(){await Promise.all([loadMetrics(),loadCycle(),loadBets()])}
loadAll();setInterval(loadAll,12000)
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/setup-db")
def setup_db():
    ok = init_db()
    return jsonify({"ok": ok, "message": "Base de datos inicializada y migrada" if ok else "No se pudo inicializar la base de datos"}), (200 if ok else 500)


@app.route("/clear-open", methods=["POST"])
def clear_open():
    try:
        current_epoch = get_current_lab_epoch()
        open_bets = get_open_bets()
        refund = round(sum(safe_float(bet.get("amount"), 0.0) for bet in open_bets), 2)
        if open_bets:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE bets
                        SET status='lab_reset_archived',
                            active_lab=FALSE,
                            selection_bucket='legacy_archive',
                            resolved_reason='clear_open_archive',
                            resolved_at=NOW()
                        WHERE lab_epoch=%s AND status='open'
                        """,
                        (current_epoch,),
                    )
            set_state("balance", get_state("balance", get_paper_starting_balance()) + refund)
        return jsonify({"ok": True, "message": f"Se archivaron {len(open_bets)} apuestas abiertas del lab actual y se devolvieron ${refund} al balance operativo", "lab_epoch": current_epoch, "refund": refund})
    except Exception as exc:
        logger.exception("clear_open failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/lab-reset", methods=["POST"])
def lab_reset():
    try:
        payload = request.get_json(silent=True) or {}
        requested_balance = safe_float(payload.get("balance", request.args.get("balance", get_paper_starting_balance())), get_paper_starting_balance())
        result = archive_current_lab_and_reset(balance=requested_balance)
        return jsonify({
            "ok": True,
            "message": f"Lab reseteado. Epoch anterior {result['previous_lab_epoch']} archivado; nuevo epoch {result['lab_epoch']} con balance ${round(result['balance'], 2)}.",
            "archived_total": result["archived_total"],
            "archived_open": result["archived_open"],
            "refund": result["refund"],
            "current_lab_epoch": result["lab_epoch"],
            "strategy_version": CURRENT_STRATEGY_VERSION,
        })
    except Exception as exc:
        logger.exception("lab_reset failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/fund-paper", methods=["POST"])
def fund_paper():
    try:
        payload = request.get_json(silent=True) or {}
        amount = safe_float(payload.get("amount", request.args.get("amount", 0.0)), 0.0)
        if amount <= 0:
            return jsonify({"ok": False, "error": "amount debe ser > 0"}), 400
        new_balance = round(get_state("balance", get_paper_starting_balance()) + amount, 2)
        set_state("balance", new_balance)
        return jsonify({"ok": True, "message": f"Se agregaron ${round(amount, 2)} al bankroll paper.", "amount_added": round(amount, 2), "new_balance": new_balance, "current_lab_epoch": get_current_lab_epoch()})
    except Exception as exc:
        logger.exception("fund_paper failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/debug")
def debug():
    try:
        markets = fetch_active_markets()
        now_utc = datetime.now(timezone.utc)
        supported = 0
        examples = []
        for market in markets:
            try:
                ok, prob = detect_market_supported(market, now_utc)
                if ok:
                    supported += 1
                    if len(examples) < 5:
                        examples.append({"question": market.get("question", "")[:70], "prob": round(prob * 100), "volume": round(safe_float(market.get("volume", 0)))})
            except Exception:
                continue
        return jsonify({"total": len(markets), "supported": supported, "examples": examples, "lab_mode": RESEARCH_LAB_MODE})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/test-metaculus")
def test_metaculus():
    return jsonify(fetch_metaculus_source("Will Viktor Orban remain Prime Minister of Hungary"))


@app.route("/test-wiki")
def test_wiki():
    return jsonify(fetch_wikipedia_source("Will Viktor Orban remain Prime Minister of Hungary"))


if __name__ == "__main__":
    start_background_loops()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
