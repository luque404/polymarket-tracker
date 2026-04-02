
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
from flask import Flask, jsonify, render_template_string, request, url_for
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
RUNNER_AUTONOMOUS = os.environ.get("RUNNER_AUTONOMOUS", "true").lower() == "true"

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
BET_LOOP_INTERVAL_SECONDS = int(os.environ.get("BET_LOOP_INTERVAL_SECONDS", "180"))
MONITOR_LOOP_INTERVAL_SECONDS = 3600
INITIAL_RESOLUTION_CHECK_SECONDS = 3600
RESOLUTION_RETRY_SECONDS = 7200
RUNNER_HEARTBEAT_SECONDS = int(os.environ.get("RUNNER_HEARTBEAT_SECONDS", str(max(15, min(60, BET_LOOP_INTERVAL_SECONDS // 3 or 15)))))
RUNNER_LEASE_SECONDS = int(os.environ.get("RUNNER_LEASE_SECONDS", str(max(180, BET_LOOP_INTERVAL_SECONDS * 3))))
RUNNER_STALE_AFTER_SECONDS = int(os.environ.get("RUNNER_STALE_AFTER_SECONDS", str(max(600, BET_LOOP_INTERVAL_SECONDS * 4))))
RUNNER_CYCLE_LOCK_TIMEOUT_SECONDS = int(os.environ.get("RUNNER_CYCLE_LOCK_TIMEOUT_SECONDS", str(max(300, BET_LOOP_INTERVAL_SECONDS * 4))))
RUNNER_WATCHDOG_INTERVAL_SECONDS = int(os.environ.get("RUNNER_WATCHDOG_INTERVAL_SECONDS", "30"))
MARKETS_FETCH_LIMIT = 500
MARKETS_PREVIEW_LIMIT = 20
MAX_OPEN_BETS = 140
MAX_POSITIONS_PER_CYCLE = 24
MAX_CORE_POSITIONS_PER_CYCLE = 6
MAX_SECONDARY_POSITIONS_PER_CYCLE = 10
MAX_EXPLORATORY_POSITIONS_PER_CYCLE = 12
MAX_TOTAL_EXPOSURE_PCT = 0.85
MAX_CATEGORY_EXPOSURE_PCT = 0.20
MAX_SIDE_EXPOSURE_PCT = 0.42
MAX_THESIS_EXPOSURE_PCT = 0.20
MIN_MARKET_PROB = 0.08
MAX_MARKET_PROB = 0.92
MIN_MARKET_VOLUME = 20
MAX_DAYS_TO_RESOLUTION = 365
MIN_DAYS_TO_RESOLUTION = 1
MIN_COMPOUND_SCORE = 0.42
MIN_EDGE_TO_BET = 0.04
MIN_CONFIDENCE_TO_BET = 4
MIN_SOURCE_QUALITY_TO_BET = 0.28
MIN_EVIDENCE_STRENGTH_TO_BET = 0.28
TAKE_PROFIT_THRESHOLD = 0.18
STOP_LOSS_THRESHOLD = 0.22
TRAILING_STOP_GIVEBACK = 0.10
CORE_MAX_FRACTION = 0.14
EXPERIMENTAL_MAX_FRACTION = 0.025
EXPERIMENTAL_SCORE_FLOOR = 0.22
EXPLORATION_CAPITAL_RESERVE_PCT = 0.24
LONG_DATED_PENALTY_START_DAYS = 75
FAST_FEEDBACK_DAYS = 28
POLYMARKET_FEE_HAIRCUT = 0.95
WATCHLIST_LIMIT = 20
TIER_A_SCORE_FLOOR = 0.61
TIER_B_SCORE_FLOOR = 0.44
TIER_C_SCORE_FLOOR = 0.26
OBVIOUS_ENOUGH_SCORE = 0.38
CORE_BUDGET_PCT = 0.32
SECONDARY_BUDGET_PCT = 0.30
EXPLORATORY_BUDGET_PCT = 0.18
FAST_FEEDBACK_BUDGET_PCT = 0.26
LONG_DATED_HIGH_CONVICTION_BUDGET_PCT = 0.18
CORE_RELATIVE_PROMOTION_SCORE = 0.78
CORE_RELATIVE_FLOOR = 0.60
SECONDARY_RELATIVE_FLOOR = 0.34
EXPLORATORY_RELATIVE_FLOOR = 0.16
TARGET_CORE_OPEN_SHARE = 0.18
TARGET_EXPLORATORY_OPEN_SHARE = 0.22
MIN_CORE_PER_CYCLE_IF_AVAILABLE = 2
MIN_EXPLORATORY_PER_CYCLE_IF_AVAILABLE = 2
RUNNER_PROCESS_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

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
    "obvious_trade_override": "BOOLEAN DEFAULT FALSE",
    "obvious_trade_reasons": "TEXT",
    "relative_rank_score": "REAL DEFAULT 0",
    "quality_rank_pct": "REAL DEFAULT 0",
    "conviction_rank_pct": "REAL DEFAULT 0",
    "learnability_rank_pct": "REAL DEFAULT 0",
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
    "recent_candidate_cache": "{}",
    "runner_enabled": "true" if ENABLE_BACKGROUND_LOOPS else "false",
    "runner_last_heartbeat": "",
    "runner_health_state": "stopped",
    "runner_leader_id": "",
    "last_cycle_started_at": "",
    "last_cycle_finished_at": "",
    "last_cycle_status": "never",
    "last_cycle_duration_ms": "0",
    "last_cycle_error": "",
    "last_cycle_analyzed": "0",
    "last_cycle_shortlist": "0",
    "last_cycle_selected": "0",
    "last_cycle_watchlist": "0",
    "last_cycle_rejected": "0",
    "last_successful_cycle_at": "",
    "runner_cycle_lock_owner": "",
    "runner_cycle_lock_until": "",
    "runner_last_autostart_at": "",
    "runner_last_autostart_reason": "",
    "runner_auto_recovered_at": "",
    "runner_auto_recovered_reason": "",
    "runner_auto_recovery_count": "0",
}

RUNNER_CYCLES_SCHEMA = {
    "id": "TEXT PRIMARY KEY",
    "trigger": "TEXT",
    "started_at": "TIMESTAMPTZ DEFAULT NOW()",
    "finished_at": "TIMESTAMPTZ",
    "status": "TEXT DEFAULT 'started'",
    "duration_ms": "INTEGER DEFAULT 0",
    "analyzed": "INTEGER DEFAULT 0",
    "shortlist": "INTEGER DEFAULT 0",
    "selected": "INTEGER DEFAULT 0",
    "watchlist": "INTEGER DEFAULT 0",
    "rejected": "INTEGER DEFAULT 0",
    "obvious_selected": "INTEGER DEFAULT 0",
    "error_text": "TEXT",
    "summary_json": "TEXT",
}

BACKGROUND_LOOPS_LOCK = threading.Lock()
BACKGROUND_LOOPS_STARTED = False
BET_LOOP_THREAD = None
MONITOR_LOOP_THREAD = None
RUNNER_WATCHDOG_THREAD = None
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
                ensure_table_columns(cur, "runner_cycles", RUNNER_CYCLES_SCHEMA)
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


def set_state_values(mapping):
    if not DATABASE_URL or not mapping:
        return False
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                for key, value in mapping.items():
                    cur.execute(
                        "INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                        (key, "" if value is None else str(value)),
                    )
        return True
    except psycopg2.Error:
        logger.exception("Failed to set state values")
        return False


def utc_now():
    return datetime.now(timezone.utc)


def to_iso(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def format_age_seconds(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m" if rem < 30 else f"{minutes}m {rem}s"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins}m"
    days, hrs = divmod(hours, 24)
    return f"{days}d {hrs}h"


def is_runner_enabled():
    return get_state_text("runner_enabled", "false").lower() == "true"


def set_runner_enabled(enabled):
    set_state("runner_enabled", "true" if enabled else "false")
    if not enabled:
        set_state_values({
            "runner_health_state": "stopped",
            "runner_leader_id": "",
            "runner_last_heartbeat": "",
        })


def should_run_background_loops():
    return ENABLE_BACKGROUND_LOOPS or RUNNER_AUTONOMOUS


def claim_runner_leader(force=False):
    if not DATABASE_URL:
        return False
    now = utc_now()
    now_iso = to_iso(now)
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM state WHERE key IN ('runner_leader_id','runner_last_heartbeat') FOR UPDATE")
                rows = {key: value for key, value in cur.fetchall()}
                leader_id = rows.get("runner_leader_id", "")
                heartbeat = iso_to_datetime(rows.get("runner_last_heartbeat", ""))
                lease_expired = not heartbeat or (now - heartbeat).total_seconds() > RUNNER_LEASE_SECONDS
                if force or not leader_id or leader_id == RUNNER_PROCESS_ID or lease_expired:
                    cur.execute(
                        "INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                        ("runner_leader_id", RUNNER_PROCESS_ID),
                    )
                    cur.execute(
                        "INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                        ("runner_last_heartbeat", now_iso),
                    )
                    return True
                return False
    except psycopg2.Error:
        logger.exception("Failed to claim runner leader")
        return False


def heartbeat_runner(force_claim=False):
    if force_claim and not claim_runner_leader(force=True):
        return False
    leader_id = get_state_text("runner_leader_id", "")
    if leader_id and leader_id != RUNNER_PROCESS_ID and not force_claim:
        return False
    now = utc_now()
    return set_state_values({
        "runner_leader_id": RUNNER_PROCESS_ID,
        "runner_last_heartbeat": to_iso(now),
    })


def acquire_cycle_lock():
    if not DATABASE_URL:
        return False, "db_unavailable"
    now = utc_now()
    until = now + timedelta(seconds=RUNNER_CYCLE_LOCK_TIMEOUT_SECONDS)
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM state WHERE key IN ('runner_cycle_lock_owner','runner_cycle_lock_until') FOR UPDATE")
                rows = {key: value for key, value in cur.fetchall()}
                owner = rows.get("runner_cycle_lock_owner", "")
                lock_until = iso_to_datetime(rows.get("runner_cycle_lock_until", ""))
                if owner and owner != RUNNER_PROCESS_ID and lock_until and lock_until > now:
                    return False, owner
                cur.execute(
                    "INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                    ("runner_cycle_lock_owner", RUNNER_PROCESS_ID),
                )
                cur.execute(
                    "INSERT INTO state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                    ("runner_cycle_lock_until", to_iso(until)),
                )
        return True, "ok"
    except psycopg2.Error:
        logger.exception("Failed to acquire cycle lock")
        return False, "lock_error"


def release_cycle_lock():
    if not DATABASE_URL:
        return False
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM state WHERE key='runner_cycle_lock_owner' FOR UPDATE")
                row = cur.fetchone()
                if row and row[0] == RUNNER_PROCESS_ID:
                    cur.execute("UPDATE state SET value='' WHERE key='runner_cycle_lock_owner'")
                    cur.execute("UPDATE state SET value='' WHERE key='runner_cycle_lock_until'")
        return True
    except psycopg2.Error:
        logger.exception("Failed to release cycle lock")
        return False


def cycle_due():
    if not is_runner_enabled():
        return False
    now = utc_now()
    last_finished = iso_to_datetime(get_state_text("last_cycle_finished_at", ""))
    last_started = iso_to_datetime(get_state_text("last_cycle_started_at", ""))
    reference = last_finished or last_started
    if not reference:
        return True
    return (now - reference).total_seconds() >= BET_LOOP_INTERVAL_SECONDS


def save_runner_cycle_row(cycle_id, trigger, started_at):
    if not DATABASE_URL:
        return False
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runner_cycles (id, trigger, started_at, status)
                    VALUES (%s, %s, %s, 'started')
                    ON CONFLICT (id) DO UPDATE SET trigger=EXCLUDED.trigger, started_at=EXCLUDED.started_at, status='started'
                    """,
                    (cycle_id, trigger, started_at),
                )
        return True
    except psycopg2.Error:
        logger.exception("Failed to save runner cycle row id=%s", cycle_id)
        return False


def finalize_runner_cycle_row(cycle_id, status, finished_at, duration_ms, result=None, error_text=""):
    result = result or {}
    summary = LAST_CYCLE_DATA.get("summary", {})
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE runner_cycles
                    SET finished_at=%s,
                        status=%s,
                        duration_ms=%s,
                        analyzed=%s,
                        shortlist=%s,
                        selected=%s,
                        watchlist=%s,
                        rejected=%s,
                        obvious_selected=%s,
                        error_text=%s,
                        summary_json=%s
                    WHERE id=%s
                    """,
                    (
                        finished_at,
                        status,
                        int(duration_ms),
                        int(result.get("analyzed", 0)),
                        int(result.get("shortlisted", 0)),
                        int(result.get("selected", 0)),
                        int(result.get("watchlist", 0)),
                        len(result.get("rejected", [])) if isinstance(result.get("rejected"), list) else int(result.get("rejected", 0)),
                        int(summary.get("obvious_selected", 0)),
                        (error_text or "")[:1000],
                        json.dumps(summary, ensure_ascii=False),
                        cycle_id,
                    ),
                )
        return True
    except psycopg2.Error:
        logger.exception("Failed to finalize runner cycle row id=%s", cycle_id)
        return False


def execute_bot_cycle(trigger="manual"):
    started_at = utc_now()
    cycle_id = str(uuid.uuid4())
    heartbeat_runner(force_claim=(trigger == "auto"))
    locked, lock_reason = acquire_cycle_lock()
    if not locked:
        set_state_values({
            "last_cycle_status": "skipped",
            "last_cycle_error": f"cycle_lock_busy:{lock_reason}",
            "runner_health_state": "healthy" if is_runner_enabled() else "stopped",
        })
        return {
            "cycle_id": cycle_id,
            "analyzed": 0,
            "shortlisted": 0,
            "selected": 0,
            "watchlist": 0,
            "placed": [],
            "rejected": [],
            "skipped": True,
            "skip_reason": "cycle_lock_busy",
        }
    save_runner_cycle_row(cycle_id, trigger, started_at)
    set_state_values({
        "last_cycle_started_at": to_iso(started_at),
        "last_cycle_status": "running",
        "last_cycle_error": "",
        "runner_health_state": "healthy",
    })
    logger.info("Runner cycle start trigger=%s cycle_id=%s leader=%s", trigger, cycle_id, RUNNER_PROCESS_ID)
    try:
        result = run_bot_cycle(cycle_id=cycle_id)
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        set_state_values({
            "last_cycle_finished_at": to_iso(finished_at),
            "last_cycle_status": "success",
            "last_cycle_duration_ms": duration_ms,
            "last_cycle_error": "",
            "last_cycle_analyzed": result.get("analyzed", 0),
            "last_cycle_shortlist": result.get("shortlisted", 0),
            "last_cycle_selected": result.get("selected", 0),
            "last_cycle_watchlist": result.get("watchlist", 0),
            "last_cycle_rejected": len(result.get("rejected", [])),
            "last_successful_cycle_at": to_iso(finished_at),
            "runner_health_state": "healthy",
        })
        finalize_runner_cycle_row(cycle_id, "success", finished_at, duration_ms, result=result)
        logger.info(
            "Runner cycle success trigger=%s cycle_id=%s duration_ms=%s analyzed=%s shortlist=%s selected=%s watchlist=%s rejected=%s obvious=%s",
            trigger,
            cycle_id,
            duration_ms,
            result.get("analyzed", 0),
            result.get("shortlisted", 0),
            result.get("selected", 0),
            result.get("watchlist", 0),
            len(result.get("rejected", [])),
            LAST_CYCLE_DATA.get("summary", {}).get("obvious_selected", 0),
        )
        return result
    except Exception as exc:
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        error_text = f"{type(exc).__name__}: {exc}"
        set_state_values({
            "last_cycle_finished_at": to_iso(finished_at),
            "last_cycle_status": "error",
            "last_cycle_duration_ms": duration_ms,
            "last_cycle_error": error_text[:1000],
            "last_cycle_analyzed": 0,
            "last_cycle_shortlist": 0,
            "last_cycle_selected": 0,
            "last_cycle_watchlist": 0,
            "last_cycle_rejected": 0,
            "runner_health_state": "delayed",
        })
        finalize_runner_cycle_row(cycle_id, "error", finished_at, duration_ms, error_text=error_text)
        logger.exception("Runner cycle failed trigger=%s cycle_id=%s", trigger, cycle_id)
        raise
    finally:
        heartbeat_runner()
        release_cycle_lock()


def get_recent_runner_cycles(limit=20):
    if not DATABASE_URL:
        return []
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM runner_cycles ORDER BY started_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
        return [dict(row) for row in rows]
    except psycopg2.Error:
        logger.exception("Failed to fetch runner cycles")
        return []


def build_runner_status():
    now = utc_now()
    last_started = iso_to_datetime(get_state_text("last_cycle_started_at", ""))
    last_finished = iso_to_datetime(get_state_text("last_cycle_finished_at", ""))
    last_success = iso_to_datetime(get_state_text("last_successful_cycle_at", ""))
    last_heartbeat = iso_to_datetime(get_state_text("runner_last_heartbeat", ""))
    runner_enabled = is_runner_enabled()
    if not runner_enabled:
        health = "stopped"
    elif not last_heartbeat:
        health = "stale"
    else:
        age = (now - last_heartbeat).total_seconds()
        if age <= RUNNER_HEARTBEAT_SECONDS * 2:
            health = "healthy"
        elif age <= RUNNER_STALE_AFTER_SECONDS:
            health = "delayed"
        else:
            health = "stale"
    if get_state_text("last_cycle_status", "never") == "error" and health == "healthy":
        health = "delayed"
    set_state("runner_health_state", health)
    recent_cycles = get_recent_runner_cycles(limit=30)
    cutoff = now - timedelta(hours=1)
    cycles_last_hour = sum(1 for item in recent_cycles if item.get("started_at") and item["started_at"] >= cutoff)
    recent_successes = [item for item in recent_cycles if item.get("status") == "success"][:5]
    zero_entry_streak = 0
    for item in recent_successes:
        if int(item.get("selected") or 0) == 0:
            zero_entry_streak += 1
        else:
            break
    serialized_recent_cycles = []
    for item in recent_cycles[:10]:
        serialized_recent_cycles.append({
            **item,
            "started_at": to_iso(item.get("started_at")),
            "finished_at": to_iso(item.get("finished_at")),
        })
    last_error = get_state_text("last_cycle_error", "")
    if not runner_enabled:
        summary = "Bot detenido."
    elif health == "healthy" and last_success:
        summary = f"Bot funcionando. Último análisis hace {format_age_seconds((now - last_success).total_seconds())}."
    elif health == "delayed" and last_started:
        summary = f"Bot lento. Último análisis hace {format_age_seconds((now - last_started).total_seconds())}."
    else:
        reference = last_started or last_success
        summary = f"Bot frenado. No hubo análisis recientes." if not reference else f"Bot frenado. No hubo análisis hace {format_age_seconds((now - reference).total_seconds())}."
    if last_error and get_state_text("last_cycle_status", "") == "error":
        summary = f"{summary} El último análisis falló: {last_error[:160]}"
    elif zero_entry_streak >= 3:
        summary = f"{summary} El bot está funcionando, pero no encontró apuestas en los últimos {zero_entry_streak} análisis."
    return {
        "runner_enabled": runner_enabled,
        "runner_autonomous": RUNNER_AUTONOMOUS,
        "runner_process_id": RUNNER_PROCESS_ID,
        "runner_leader_id": get_state_text("runner_leader_id", ""),
        "runner_last_heartbeat": to_iso(last_heartbeat),
        "runner_health_state": health,
        "runner_stale_after_seconds": RUNNER_STALE_AFTER_SECONDS,
        "runner_last_autostart_at": get_state_text("runner_last_autostart_at", ""),
        "runner_last_autostart_reason": get_state_text("runner_last_autostart_reason", ""),
        "runner_auto_recovered_at": get_state_text("runner_auto_recovered_at", ""),
        "runner_auto_recovered_reason": get_state_text("runner_auto_recovered_reason", ""),
        "runner_auto_recovery_count": int(get_state("runner_auto_recovery_count", 0)),
        "last_cycle_started_at": to_iso(last_started),
        "last_cycle_finished_at": to_iso(last_finished),
        "last_cycle_status": get_state_text("last_cycle_status", "never"),
        "last_cycle_duration_ms": int(get_state("last_cycle_duration_ms", 0)),
        "last_cycle_error": last_error,
        "last_cycle_analyzed": int(get_state("last_cycle_analyzed", 0)),
        "last_cycle_shortlist": int(get_state("last_cycle_shortlist", 0)),
        "last_cycle_selected": int(get_state("last_cycle_selected", 0)),
        "last_cycle_watchlist": int(get_state("last_cycle_watchlist", 0)),
        "last_cycle_rejected": int(get_state("last_cycle_rejected", 0)),
        "last_successful_cycle_at": to_iso(last_success),
        "cycles_last_hour": cycles_last_hour,
        "runner_summary": summary,
        "recent_cycles": serialized_recent_cycles,
    }


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
    obvious_count = sum(1 for item in selected if item.get("obvious_trade_override"))
    reason_counts = Counter(reason for _, reason in rejected)
    top_blockers = dict(reason_counts.most_common(6))
    if selected:
        headline = f"Se hicieron {len(selected)} apuestas: {core_count} fuertes, {secondary_count} buenas y {exploratory_count} de exploración."
    elif watchlist:
        top_reason = next(iter(top_blockers), "no eran lo suficientemente buenas")
        readable_reason = {
            "duplicate_semantic_overlap": "eran muy parecidas a otras apuestas",
            "tier_skip": "no eran lo suficientemente buenas",
            "low_reliability": "había poca confianza",
            "low_score": "no parecían una buena apuesta",
        }.get(top_reason, "todavía no era momento de apostar")
        headline = f"Revisó {analyzed_count} mercados. Encontró {len(watchlist)} oportunidades, pero no hizo apuestas porque {readable_reason}."
    elif shortlist_count:
        top_reason = next(iter(top_blockers), "faltó una oportunidad clara")
        readable_reason = {
            "duplicate_semantic_overlap": "muy parecidas a otras apuestas",
            "tier_skip": "no eran lo suficientemente buenas",
            "low_reliability": "había poca confianza",
            "low_score": "faltó una oportunidad clara",
        }.get(top_reason, "faltó una oportunidad clara")
        headline = f"Revisó {analyzed_count} mercados. {shortlist_count} quedaron preseleccionadas, pero no hizo apuestas porque {readable_reason}."
    else:
        headline = f"Revisó {analyzed_count} mercados y no encontró oportunidades lo suficientemente buenas."
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
        "obvious_selected": obvious_count,
        "watchlist_core_like": sum(1 for item in watchlist if item.get("trade_class") == "core"),
        "watchlist_exploratory_like": sum(1 for item in watchlist if item.get("trade_class") == "experimental"),
        "blockers": top_blockers,
    }


def get_recent_candidate_cache():
    return safe_json_loads(get_state_text("recent_candidate_cache", "{}"), {})


def set_recent_candidate_cache(cache):
    set_state("recent_candidate_cache", json.dumps(cache))


def candidate_identity_keys(candidate):
    packet = candidate["packet"]
    question = normalize_question(candidate.get("question", packet.get("market_question", ""))).lower()
    semantic_key = "|".join([
        packet.get("category", ""),
        packet.get("semantic_subject", ""),
        packet.get("semantic_event", ""),
        packet.get("semantic_deadline", "") or "",
        candidate.get("side", ""),
    ]).lower()
    return {
        "market_id": candidate.get("market_id") or packet.get("market_id", ""),
        "question_key": hash_text(question),
        "semantic_key": hash_text(semantic_key),
    }


def is_duplicate_or_near_duplicate(candidate, existing_bets, selected):
    identity = candidate_identity_keys(candidate)
    packet = candidate["packet"]
    for bet in list(existing_bets) + list(selected):
        if identity["market_id"] and identity["market_id"] == bet.get("market_id"):
            return True, "duplicate_market_id"
        other_question = normalize_question(bet.get("question", "")).lower()
        if other_question and hash_text(other_question) == identity["question_key"]:
            return True, "duplicate_question"
        other_packet = safe_json_loads(bet.get("research_packet"), {}) if isinstance(bet, dict) else {}
        other_semantic_key = hash_text(
            "|".join([
                bet.get("category", other_packet.get("category", "")),
                other_packet.get("semantic_subject", ""),
                other_packet.get("semantic_event", ""),
                other_packet.get("semantic_deadline", "") or "",
                bet.get("side", ""),
            ]).lower()
        ) if (bet.get("category") or other_packet) else ""
        overlap_terms = top_overlap_terms(packet.get("market_question", ""), bet.get("question", ""))
        overlap = len(overlap_terms)
        same_category = bet.get("category") == packet.get("category")
        same_side = bet.get("side") == candidate.get("side")
        same_thesis = bet.get("thesis_type") == candidate.get("thesis_type")
        same_semantic_key = bool(identity["semantic_key"] and other_semantic_key and identity["semantic_key"] == other_semantic_key)
        strong_overlap = overlap >= 8
        very_strong_overlap = overlap >= 10
        semantically_same_trade = same_side and same_semantic_key and overlap >= 4
        near_identical_surface = same_side and same_category and same_thesis and strong_overlap
        broad_clone = same_side and very_strong_overlap and (same_category or same_thesis)
        if semantically_same_trade or near_identical_surface or broad_clone:
            logger.info(
                "Duplicate overlap blocked market_id=%s against=%s overlap=%s same_semantic=%s same_category=%s same_thesis=%s same_side=%s terms=%s",
                candidate.get("market_id"),
                bet.get("market_id"),
                overlap,
                same_semantic_key,
                same_category,
                same_thesis,
                same_side,
                ",".join(overlap_terms[:8]),
            )
            return True, "duplicate_semantic_overlap"
        if overlap >= 5 and same_side and (same_category or same_thesis):
            logger.info(
                "Duplicate overlap allowed market_id=%s against=%s overlap=%s same_semantic=%s same_category=%s same_thesis=%s same_side=%s terms=%s",
                candidate.get("market_id"),
                bet.get("market_id"),
                overlap,
                same_semantic_key,
                same_category,
                same_thesis,
                same_side,
                ",".join(overlap_terms[:8]),
            )
    return False, "ok"


def seen_recently(candidate, cooldown_seconds=5400):
    cache = get_recent_candidate_cache()
    identity = candidate_identity_keys(candidate)
    now_ts = time.time()
    keys = [identity["market_id"], identity["question_key"], identity["semantic_key"]]
    for key in keys:
        if not key:
            continue
        last_seen = safe_float(cache.get(key), 0.0)
        if last_seen and now_ts - last_seen < cooldown_seconds:
            return True
    return False


def mark_candidate_seen(candidate):
    cache = get_recent_candidate_cache()
    identity = candidate_identity_keys(candidate)
    now_ts = time.time()
    for key in [identity["market_id"], identity["question_key"], identity["semantic_key"]]:
        if key:
            cache[key] = now_ts
    pruned = {k: v for k, v in cache.items() if now_ts - safe_float(v, 0.0) < 86400}
    set_recent_candidate_cache(pruned)


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
    if reliability >= 0.58 and opportunity_score >= 0.52 and ease_of_win_score >= 0.56:
        return "core"
    if reliability >= 0.31 and opportunity_score >= 0.33:
        return "secondary"
    if learning_velocity_score >= 0.20 or opportunity_score >= 0.24 or ease_of_win_score >= 0.34:
        return "experimental"
    return "skip"


def assign_candidate_tier(candidate):
    reliability = candidate.get("conclusion_reliability_score", 0.0)
    opportunity = candidate.get("opportunity_score", 0.0)
    ease_of_win = candidate.get("ease_of_win_score", 0.0)
    learning_velocity = candidate.get("learning_velocity_score", 0.0)
    edge = candidate.get("edge", 0.0)
    score = candidate.get("portfolio_priority_score", candidate.get("compound_score", 0.0))
    if score >= TIER_A_SCORE_FLOOR and reliability >= 0.58 and ease_of_win >= 0.52:
        return "TIER_A"
    if score >= TIER_B_SCORE_FLOOR and reliability >= 0.34 and opportunity >= 0.32:
        return "TIER_B"
    if score >= TIER_C_SCORE_FLOOR and (learning_velocity >= 0.20 or opportunity >= 0.24 or ease_of_win >= 0.42):
        return "TIER_C"
    if edge >= 0.05 and (opportunity >= 0.20 or ease_of_win >= 0.38 or learning_velocity >= 0.26):
        return "TIER_C"
    return "TIER_D"


def obvious_enough_to_take(candidate):
    return (
        candidate.get("edge", 0.0) >= 0.045 and (
            candidate.get("portfolio_priority_score", 0.0) >= OBVIOUS_ENOUGH_SCORE
            or candidate.get("learning_velocity_score", 0.0) >= 0.68
            or candidate.get("ease_of_win_score", 0.0) >= 0.62
            or (
                candidate.get("mispricing_score", 0.0) >= 0.58
                and candidate.get("conclusion_reliability_score", 0.0) >= 0.34
            )
        )
    )


def detect_obvious_trade_setup(candidate):
    packet = candidate["packet"]
    question = (candidate.get("question") or packet.get("market_question") or "").lower()
    reasons = []
    if "before gta" in question or "gta vi" in question or "gta 6" in question:
        reasons.append("before_gta_deadline")
    if packet.get("resolution_type") == "deadline" and packet.get("market_prob", 0.0) >= 0.62 and candidate.get("ease_of_win_score", 0.0) >= 0.54:
        reasons.append("absurd_deadline_pricing")
    if packet.get("category") == "weird_impossible" and packet.get("market_prob", 0.0) >= 0.18:
        reasons.append("impossible_event_pricing")
    if packet.get("category") in ("celebrities", "product_launches") and candidate.get("mispricing_score", 0.0) >= 0.58 and candidate.get("ease_of_win_score", 0.0) >= 0.52:
        reasons.append("repeat_disappointment_pattern")
    if candidate.get("edge", 0.0) >= 0.09 and candidate.get("ease_of_win_score", 0.0) >= 0.58 and packet.get("uncertainty_score", 0.0) <= 0.56:
        reasons.append("simple_structural_edge")
    if packet.get("external_forecast_divergence", 0.0) >= 0.14 and packet.get("external_match_confidence", 0.0) >= 0.55:
        reasons.append("strong_forecast_gap")
    override = len(reasons) >= 1 and candidate.get("mispricing_score", 0.0) >= 0.48
    return override, reasons[:3]


def apply_relative_ranks(candidates):
    if not candidates:
        return candidates
    total = len(candidates)

    def assign_percentile(items, key_name, source_key):
        ordered = sorted(items, key=lambda item: item.get(source_key, 0.0), reverse=True)
        for index, item in enumerate(ordered):
            pct = 1.0 if total == 1 else 1.0 - (index / (total - 1))
            item[key_name] = round(clamp(pct, 0.0, 1.0), 4)

    assign_percentile(candidates, "quality_rank_pct", "portfolio_priority_score")
    assign_percentile(candidates, "conviction_rank_pct", "conclusion_reliability_score")
    assign_percentile(candidates, "learnability_rank_pct", "market_learnability_score")

    for candidate in candidates:
        relative_score = clamp(
            candidate.get("quality_rank_pct", 0.0) * 0.42
            + candidate.get("conviction_rank_pct", 0.0) * 0.30
            + candidate.get("learnability_rank_pct", 0.0) * 0.16
            + candidate.get("ease_of_win_score", 0.0) * 0.12,
            0.0,
            1.0,
        )
        candidate["relative_rank_score"] = round(relative_score, 4)
        if candidate.get("obvious_trade_override") and relative_score >= 0.66 and candidate.get("conclusion_reliability_score", 0.0) >= 0.40:
            candidate["trade_class"] = "core"
            candidate["tier"] = "TIER_A"
        elif relative_score >= 0.82 and candidate.get("conclusion_reliability_score", 0.0) >= 0.46:
            candidate["trade_class"] = "core"
            candidate["tier"] = "TIER_A"
        elif relative_score >= 0.45 and candidate.get("trade_class") == "experimental" and candidate.get("conclusion_reliability_score", 0.0) >= 0.28:
            candidate["trade_class"] = "secondary"
            candidate["tier"] = "TIER_B"
        elif relative_score <= 0.20 and candidate.get("trade_class") == "secondary" and candidate.get("market_learnability_score", 0.0) >= 0.42:
            candidate["trade_class"] = "experimental"
            candidate["tier"] = "TIER_C"
    return candidates


def rebalance_trade_mix(candidates, snapshot):
    if not candidates:
        return candidates

    ranked = sorted(candidates, key=lambda item: (
        item.get("relative_rank_score", 0.0),
        item.get("portfolio_priority_score", 0.0),
        item.get("ease_of_win_score", 0.0),
    ), reverse=True)
    total = len(ranked)
    open_total = max(1, len(snapshot.get("open_bets", [])))
    need_core = snapshot.get("core_open", 0) / open_total < TARGET_CORE_OPEN_SHARE
    need_exploratory = snapshot.get("experimental_open", 0) / open_total < TARGET_EXPLORATORY_OPEN_SHARE
    top_core_window = max(MIN_CORE_PER_CYCLE_IF_AVAILABLE, min(4, total // 3 if total >= 6 else total))

    for index, candidate in enumerate(ranked):
        relative = candidate.get("relative_rank_score", 0.0)
        reliability = candidate.get("conclusion_reliability_score", 0.0)
        ease = candidate.get("ease_of_win_score", 0.0)
        learnability = candidate.get("market_learnability_score", 0.0)
        learning_velocity = candidate.get("learning_velocity_score", 0.0)
        obvious = candidate.get("obvious_trade_override", False)

        if index < top_core_window and relative >= CORE_RELATIVE_FLOOR and reliability >= 0.40 and ease >= 0.46:
            candidate["trade_class"] = "core" if (relative >= CORE_RELATIVE_PROMOTION_SCORE or obvious or need_core) else candidate.get("trade_class", "secondary")
            if candidate["trade_class"] == "core":
                candidate["tier"] = "TIER_A" if relative >= 0.84 or obvious else "TIER_B"
                continue

        if candidate.get("trade_class") == "secondary":
            if relative < SECONDARY_RELATIVE_FLOOR and learnability >= 0.46:
                candidate["trade_class"] = "experimental"
                candidate["tier"] = "TIER_C"
            elif need_exploratory and learnability >= 0.54 and learning_velocity >= 0.42 and reliability <= 0.45:
                candidate["trade_class"] = "experimental"
                candidate["tier"] = "TIER_C"
        elif candidate.get("trade_class") == "experimental":
            if relative >= 0.48 and reliability >= 0.30 and ease >= 0.40:
                candidate["trade_class"] = "secondary"
                candidate["tier"] = "TIER_B"
            elif relative < EXPLORATORY_RELATIVE_FLOOR and not obvious:
                candidate["trade_class"] = "skip"
                candidate["tier"] = "TIER_D"

    return ranked


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
        + candidate["learning_velocity_score"] * 0.10
        + candidate["ease_of_win_score"] * 0.22
        + candidate["capital_efficiency_score"] * 0.08
        + candidate["market_quality_score"] * 0.05
        + candidate["historical_pattern_score"] * 0.07
        - correlation_penalty * 0.08
        - spread_penalty * 0.05,
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
    candidate["obvious_trade_override"], candidate["obvious_trade_reasons"] = detect_obvious_trade_setup(candidate)
    if candidate["obvious_trade_override"]:
        candidate["portfolio_priority_score"] = round(clamp(candidate["portfolio_priority_score"] + 0.10, 0.0, 1.0), 4)
        candidate["opportunity_score"] = round(clamp(candidate["opportunity_score"] + 0.06, 0.0, 1.0), 4)
        candidate["trade_class"] = "core" if candidate["ease_of_win_score"] >= 0.63 and candidate["conclusion_reliability_score"] >= 0.38 else "secondary" if candidate["conclusion_reliability_score"] >= 0.26 else "experimental"
        candidate["tier"] = "TIER_A" if candidate["ease_of_win_score"] >= 0.72 else "TIER_B"
    return candidate


def estimate_correlation_penalty(candidate, open_bets):
    if not open_bets:
        return 0.0
    packet = candidate["packet"]
    penalties = []
    for bet in open_bets:
        if candidate.get("market_id") and candidate.get("market_id") == bet.get("market_id"):
            penalties.append(0.95)
            continue
        overlap = len(top_overlap_terms(packet["market_question"], bet.get("question", "")))
        same_category = bet.get("category") == packet["category"]
        same_thesis = bet.get("thesis_type") == candidate.get("thesis_type")
        same_side = bet.get("side") == candidate.get("side")
        penalty = (0.12 if same_category else 0.0) + (0.12 if same_thesis else 0.0) + (0.10 if same_side else 0.0) + min(overlap * 0.05, 0.26)
        penalties.append(penalty)
    return clamp(max(penalties), 0.0, 0.95)


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
    if candidate.get("obvious_trade_override") and len(snapshot["open_bets"]) < MAX_OPEN_BETS:
        return True, "obvious_override"
    if len(snapshot["open_bets"]) >= MAX_OPEN_BETS:
        return False, "max_open_positions"
    if snapshot["committed"] / total_equity >= MAX_TOTAL_EXPOSURE_PCT:
        return False, "max_total_exposure"
    if snapshot["category_exposure"].get(candidate["packet"]["category"], 0.0) / total_equity >= MAX_CATEGORY_EXPOSURE_PCT and not candidate.get("obvious_trade_override"):
        return False, "max_category_exposure"
    if snapshot["side_exposure"].get(candidate["side"], 0.0) / total_equity >= MAX_SIDE_EXPOSURE_PCT:
        return False, "max_side_exposure"
    if snapshot["thesis_exposure"].get(candidate["thesis_type"], 0.0) / total_equity >= MAX_THESIS_EXPOSURE_PCT and not candidate.get("obvious_trade_override"):
        return False, "max_thesis_exposure"
    if horizon_bucket == "long" and snapshot["horizon_exposure"].get("long", 0.0) / total_equity >= LONG_DATED_HIGH_CONVICTION_BUDGET_PCT and candidate.get("tier") != "TIER_A" and not candidate.get("obvious_trade_override"):
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
    if candidate.get("obvious_trade_override"):
        long_dated_multiplier = 0.88 if horizon_bucket == "long" else max(long_dated_multiplier, 1.0)
    tier_multiplier = {"TIER_A": 1.20, "TIER_B": 0.92, "TIER_C": 0.68}.get(tier, 0.48)
    horizon_multiplier = {"ultra_short": 0.95, "short": 1.05, "medium": 1.00, "long": 0.82}.get(horizon_bucket, 0.94)
    relative_multiplier = clamp(0.78 + candidate.get("relative_rank_score", 0.0) * 0.42, 0.72, 1.32)
    if trade_class == "core":
        base_fraction = min(base_fraction * (1.08 + candidate.get("relative_rank_score", 0.0) * 0.18), CORE_MAX_FRACTION)
    elif trade_class == "secondary":
        base_fraction = min(base_fraction * 0.52, 0.065)
    elif trade_class == "experimental":
        base_fraction = min(base_fraction * 0.28, EXPERIMENTAL_MAX_FRACTION)
    final_fraction = clamp(base_fraction * aggression_multiplier * quality_multiplier * liquidity_multiplier * spread_multiplier * memory_multiplier * correlation_multiplier * long_dated_multiplier * learning_multiplier * ease_multiplier * capital_efficiency_multiplier * tier_multiplier * horizon_multiplier * relative_multiplier, 0.003, CORE_MAX_FRACTION if trade_class == "core" else 0.09 if trade_class == "secondary" else EXPERIMENTAL_MAX_FRACTION)
    usable_cash = snapshot["free_balance"]
    if trade_class == "core":
        usable_cash = max(0.0, snapshot["free_balance"] - max(0.0, snapshot["exploration_capital_reserved"] - snapshot["experimental_open"] * 20))
    elif trade_class == "secondary":
        usable_cash = min(snapshot["free_balance"], snapshot["secondary_budget"] + max(0.0, snapshot["free_balance"] * 0.18))
    else:
        usable_cash = min(snapshot["free_balance"], snapshot["exploration_capital_reserved"] + max(0.0, snapshot["free_balance"] * 0.14))
    if horizon_bucket in ("ultra_short", "short"):
        usable_cash = min(snapshot["free_balance"], usable_cash + snapshot["fast_feedback_budget"] * 0.28)
    if horizon_bucket == "long" and trade_class != "core" and not candidate.get("obvious_trade_override"):
        usable_cash *= 0.82
    amount = round(max(12.0 if trade_class == "experimental" else 20.0 if trade_class == "secondary" else 34.0, usable_cash * final_fraction), 2)
    amount = min(amount, snapshot["free_balance"] * (0.22 if trade_class == "core" else 0.11 if trade_class == "secondary" else 0.05))
    return amount, round(final_fraction, 4)


def select_portfolio(candidates, snapshot):
    selected = []
    watchlist = []
    rejected = []
    cycle_core = 0
    cycle_secondary = 0
    cycle_exploratory = 0
    cycle_category_counts = Counter()
    cycle_thesis_counts = Counter()
    desired_core = min(MAX_CORE_POSITIONS_PER_CYCLE, max(MIN_CORE_PER_CYCLE_IF_AVAILABLE, round(MAX_POSITIONS_PER_CYCLE * 0.22)))
    desired_exploratory = min(MAX_EXPLORATORY_POSITIONS_PER_CYCLE, max(MIN_EXPLORATORY_PER_CYCLE_IF_AVAILABLE, round(MAX_POSITIONS_PER_CYCLE * 0.25)))
    for candidate in sorted(candidates, key=lambda item: (item.get("portfolio_priority_score", 0.0), item["compound_score"]), reverse=True):
        trade_class = candidate["trade_class"]
        tier = candidate.get("tier", "TIER_C")
        obvious_override = candidate.get("obvious_trade_override", False)
        floor = TIER_A_SCORE_FLOOR if tier == "TIER_A" else TIER_B_SCORE_FLOOR if tier == "TIER_B" else EXPERIMENTAL_SCORE_FLOOR
        if candidate["analysis"].get("skip") and not obvious_override:
            rejected.append((candidate, "llm_skip"))
            continue
        is_dup, dup_reason = is_duplicate_or_near_duplicate(candidate, snapshot["open_bets"], selected)
        if is_dup:
            rejected.append((candidate, dup_reason))
            continue
        if seen_recently(candidate) and not obvious_override:
            rejected.append((candidate, "recently_evaluated"))
            continue
        rescued_from_tier_skip = False
        edge = candidate.get("edge", 0.0)
        opportunity = candidate.get("opportunity_score", 0.0)
        reliability = candidate.get("conclusion_reliability_score", 0.0)
        ease = candidate.get("ease_of_win_score", 0.0)
        learn = candidate.get("learning_velocity_score", 0.0)
        if trade_class == "skip" and edge >= 0.035 and (
            opportunity >= 0.32
            or ease >= 0.36
            or learn >= 0.28
        ):
            rescued_from_tier_skip = True
            candidate["trade_class"] = trade_class = "experimental" if reliability < 0.32 else "secondary"
        if tier == "TIER_D" and (
            opportunity >= 0.60
            or (trade_class in ("secondary", "experimental") and edge >= 0.035)
            or (edge >= 0.05 and (ease >= 0.38 or learn >= 0.30))
        ):
            rescued_from_tier_skip = True
            candidate["tier"] = tier = "TIER_C"
        if rescued_from_tier_skip:
            logger.info(
                "Tier skip rescue market_id=%s edge=%.4f priority=%.4f reliability=%.4f opportunity=%.4f ease=%.4f learn=%.4f trade_class=%s tier=%s",
                candidate.get("market_id"),
                edge,
                candidate.get("portfolio_priority_score", 0.0),
                reliability,
                opportunity,
                ease,
                learn,
                trade_class,
                tier,
            )
        hard_bad_opportunity = edge < 0.025 and opportunity < 0.22 and ease < 0.30 and learn < 0.22
        if trade_class == "skip" or (tier == "TIER_D" and hard_bad_opportunity):
            logger.info(
                "Tier skip blocked market_id=%s edge=%.4f priority=%.4f reliability=%.4f opportunity=%.4f ease=%.4f learn=%.4f trade_class=%s tier=%s rescued=%s",
                candidate.get("market_id"),
                edge,
                candidate.get("portfolio_priority_score", 0.0),
                reliability,
                opportunity,
                ease,
                learn,
                trade_class,
                tier,
                rescued_from_tier_skip,
            )
            rejected.append((candidate, "tier_skip"))
            continue
        if candidate["analysis"].get("take_now_vs_watchlist") == "watchlist" and len(watchlist) < WATCHLIST_LIMIT and not obvious_override and candidate.get("portfolio_priority_score", 0.0) < floor + 0.06:
            candidate["selection_bucket"] = "watchlist_high_potential"
            watchlist.append(candidate)
            continue
        same_category_count = cycle_category_counts[candidate["packet"]["category"]]
        same_thesis_count = cycle_thesis_counts[candidate["thesis_type"]]
        if same_category_count >= 3 and same_thesis_count >= 2 and not obvious_override:
            candidate["selection_bucket"] = "watchlist_high_potential"
            watchlist.append(candidate)
            continue
        if trade_class == "secondary" and cycle_core < desired_core and candidate.get("relative_rank_score", 0.0) >= 0.72 and candidate.get("conclusion_reliability_score", 0.0) >= 0.42:
            trade_class = candidate["trade_class"] = "core"
            candidate["tier"] = "TIER_A" if candidate.get("relative_rank_score", 0.0) >= 0.82 or obvious_override else "TIER_B"
            tier = candidate["tier"]
            floor = TIER_A_SCORE_FLOOR if tier == "TIER_A" else TIER_B_SCORE_FLOOR
        elif trade_class == "secondary" and cycle_exploratory < desired_exploratory and candidate.get("market_learnability_score", 0.0) >= 0.58 and candidate.get("conclusion_reliability_score", 0.0) <= 0.40:
            trade_class = candidate["trade_class"] = "experimental"
            candidate["tier"] = "TIER_C"
            tier = "TIER_C"
            floor = EXPERIMENTAL_SCORE_FLOOR
        if candidate["portfolio_priority_score"] < floor and not candidate.get("obvious_enough_to_take") and not obvious_override:
            if len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, "low_score"))
            continue
        min_reliability = 0.46 if trade_class == "core" else 0.30 if trade_class == "secondary" else 0.18
        if candidate.get("conclusion_reliability_score", 0.0) < min_reliability and not candidate.get("obvious_enough_to_take") and not obvious_override:
            if len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, "low_reliability"))
            continue
        min_edge = 0.034 if trade_class == "core" else 0.028 if trade_class == "secondary" else 0.02
        min_conf = 4 if trade_class == "core" else 3 if trade_class == "secondary" else 2
        if (candidate["edge"] < min_edge or candidate["analysis"]["confidence"] < min_conf) and not obvious_override:
            rejected.append((candidate, "weak_edge_or_confidence"))
            continue
        min_source = 0.22 if trade_class == "core" else 0.18 if trade_class == "secondary" else 0.12
        min_evidence = 0.22 if trade_class == "core" else 0.18 if trade_class == "secondary" else 0.12
        if (candidate["analysis"]["source_quality_score"] < min_source or candidate["analysis"]["evidence_strength"] < min_evidence) and not obvious_override:
            rejected.append((candidate, "low_evidence"))
            continue
        if len(selected) >= MAX_POSITIONS_PER_CYCLE and not obvious_override:
            rejected.append((candidate, "cycle_limit"))
            continue
        if trade_class == "core" and cycle_core >= MAX_CORE_POSITIONS_PER_CYCLE and not obvious_override:
            rejected.append((candidate, "core_cycle_limit"))
            continue
        if trade_class == "secondary" and cycle_secondary >= MAX_SECONDARY_POSITIONS_PER_CYCLE and not obvious_override:
            if len(watchlist) < WATCHLIST_LIMIT:
                candidate["selection_bucket"] = "watchlist_high_potential"
                watchlist.append(candidate)
            else:
                rejected.append((candidate, "secondary_cycle_limit"))
            continue
        if trade_class == "experimental" and cycle_exploratory >= MAX_EXPLORATORY_POSITIONS_PER_CYCLE and not obvious_override:
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
        cycle_category_counts[candidate["packet"]["category"]] += 1
        cycle_thesis_counts[candidate["thesis_type"]] += 1
        mark_candidate_seen(candidate)
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
        "obvious_trade_override": candidate.get("obvious_trade_override", False),
        "obvious_trade_reasons": json.dumps(candidate.get("obvious_trade_reasons", []), ensure_ascii=False),
        "relative_rank_score": candidate.get("relative_rank_score", 0.0),
        "quality_rank_pct": candidate.get("quality_rank_pct", 0.0),
        "conviction_rank_pct": candidate.get("conviction_rank_pct", 0.0),
        "learnability_rank_pct": candidate.get("learnability_rank_pct", 0.0),
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


def run_bot_cycle(cycle_id=None):
    cycle_id = cycle_id or str(uuid.uuid4())
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
    snapshot = current_portfolio_snapshot(all_bets)
    analyzed = [compute_candidate_score(analyze_candidate(candidate, all_bets), open_bets) for candidate in shortlist]
    analyzed = apply_relative_ranks(analyzed)
    analyzed = rebalance_trade_mix(analyzed, snapshot)
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
            "relative_rank_score": candidate.get("relative_rank_score", 0.0),
            "quality_rank_pct": candidate.get("quality_rank_pct", 0.0),
            "conviction_rank_pct": candidate.get("conviction_rank_pct", 0.0),
            "learnability_rank_pct": candidate.get("learnability_rank_pct", 0.0),
            "trade_class": candidate["trade_class"],
            "tier": candidate["tier"],
            "horizon_bucket": candidate["horizon_bucket"],
            "obvious_enough_to_take": candidate["obvious_enough_to_take"],
            "obvious_trade_override": candidate.get("obvious_trade_override", False),
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
            "obvious_trade_override": candidate.get("obvious_trade_override", False),
            "obvious_trade_reasons": candidate.get("obvious_trade_reasons", []),
            "amount": candidate.get("amount", 0),
            "edge": round(candidate["edge"], 4),
            "compound_score": candidate["compound_score"],
            "opportunity_score": candidate["opportunity_score"],
            "portfolio_priority_score": candidate["portfolio_priority_score"],
            "reliability": candidate["conclusion_reliability_score"],
            "relative_rank_score": candidate.get("relative_rank_score", 0.0),
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
            "obvious_trade_override": candidate.get("obvious_trade_override", False),
            "edge": round(candidate.get("edge", 0.0), 4),
            "portfolio_priority_score": candidate.get("portfolio_priority_score"),
            "opportunity_score": candidate.get("opportunity_score"),
            "reliability": candidate.get("conclusion_reliability_score"),
            "relative_rank_score": candidate.get("relative_rank_score", 0.0),
            "learnability": candidate.get("market_learnability_score", 0.0),
            "ease_of_win": candidate.get("ease_of_win_score", 0.0),
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
            "obvious_trade_override": candidate.get("obvious_trade_override", False),
            "edge": round(candidate.get("edge", 0.0), 4),
            "score": candidate.get("portfolio_priority_score", candidate.get("compound_score")),
            "reliability": candidate.get("conclusion_reliability_score"),
            "relative_rank_score": candidate.get("relative_rank_score", 0.0),
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
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_opened = [bet for bet in bets if bet.get("created_at") and bet.get("created_at") >= recent_cutoff]
    realized_pnl = round(sum(safe_float(bet.get("pnl"), 0.0) for bet in realized), 2)
    unrealized_pnl = round(sum(estimate_unrealized_pnl(bet) for bet in open_bets), 2)
    snapshot = current_portfolio_snapshot(bets)
    by_category = defaultdict(float)
    by_thesis = defaultdict(float)
    by_trade_class = defaultdict(float)
    by_tier = defaultdict(float)
    open_count_by_bucket = defaultdict(int)
    open_amount_by_bucket = defaultdict(float)
    open_quality_by_bucket = defaultdict(list)
    open_reliability_by_bucket = defaultdict(list)
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
    obvious_stats = defaultdict(lambda: {"won": 0, "total": 0, "pnl": 0.0})

    for bet in open_bets:
        bucket = bet.get("trade_class", "core")
        amount = safe_float(bet.get("amount"), 0.0)
        open_count_by_bucket[bucket] += 1
        open_amount_by_bucket[bucket] += amount
        open_quality_by_bucket[bucket].append(safe_float(bet.get("portfolio_priority_score"), 0.0))
        open_reliability_by_bucket[bucket].append(safe_float(bet.get("conclusion_reliability_score"), 0.0))

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
        obvious_bucket = "obvious" if bet.get("obvious_trade_override") else "non_obvious"
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
        obvious_stats[obvious_bucket]["total"] += 1
        obvious_stats[obvious_bucket]["pnl"] += pnl
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
            obvious_stats[obvious_bucket]["won"] += 1
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
    runner_status = build_runner_status()
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
        "open_count_by_bucket": dict(open_count_by_bucket),
        "open_amount_by_bucket": {k: round(v, 2) for k, v in open_amount_by_bucket.items()},
        "average_size_by_bucket": {k: round(open_amount_by_bucket[k] / max(1, open_count_by_bucket[k]), 2) for k in open_count_by_bucket},
        "average_priority_by_bucket": {k: round(mean(values) * 100, 1) for k, values in open_quality_by_bucket.items()},
        "average_reliability_by_bucket": {k: round(mean(values) * 100, 1) for k, values in open_reliability_by_bucket.items()},
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
        "performance_by_obviousness": {k: {"winrate": f"{round(v['won'] / v['total'] * 100)}% ({v['total']})" if v['total'] else "—", "pnl": round(v['pnl'], 2)} for k, v in obvious_stats.items()},
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
        "obvious_trades_last_cycle": LAST_CYCLE_DATA.get("summary", {}).get("obvious_selected", 0),
        "selection_mix_last_cycle": {
            "selected": int(get_state("passed_to_portfolio_last_cycle", 0)),
            "watchlist": int(get_state("watchlist_last_cycle", 0)),
            "rejected": max(0, int(get_state("markets_analyzed_last_cycle", 0)) - int(get_state("watchlist_last_cycle", 0)) - int(get_state("passed_to_portfolio_last_cycle", 0))),
        },
        "current_lab_epoch": get_current_lab_epoch(),
        "current_strategy_version": get_current_strategy_version(),
        "paper_starting_balance": get_paper_starting_balance(),
        "average_bets_per_cycle": round(int(get_state("bets_placed", 0)) / max(1, int(get_state("cycles_run", 0))), 2),
        "trades_last_hour": len(recent_opened),
        "cycles_last_hour": runner_status["cycles_last_hour"],
        "core_open": snapshot["core_open"],
        "secondary_open": snapshot["secondary_open"],
        "experimental_open": snapshot["experimental_open"],
        "coverage_breadth": len(snapshot["category_exposure"]),
        "overlap_concentration": overlap_concentration,
        "capital_efficiency": round((realized_pnl + unrealized_pnl) / max(snapshot["committed"], 1.0), 4) if snapshot["committed"] else 0.0,
        **runner_status,
    }


@app.route("/bot-bet", methods=["POST"])
def bot_bet():
    try:
        result = execute_bot_cycle(trigger="manual")
        placed = result["placed"]
        summary = LAST_CYCLE_DATA.get("summary", {})
        if result.get("skipped"):
            return jsonify({"message": "Ciclo omitido por lock activo. Otro runner ya está ejecutando.", "reasoning": result.get("skip_reason", ""), "placed": 0, "cycle_id": result["cycle_id"], "skipped": True})
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


@app.route("/runner-status")
def runner_status():
    return jsonify(build_runner_status())


@app.route("/runner-start", methods=["POST"])
def runner_start():
    set_runner_enabled(True)
    started = ensure_runner_autonomous(reason="manual_start") or claim_runner_leader(force=True)
    heartbeat_runner(force_claim=True)
    return jsonify({"ok": True, "started": bool(started), "message": "Runner habilitado.", "runner": build_runner_status()})


@app.route("/runner-stop", methods=["POST"])
def runner_stop():
    set_runner_enabled(False)
    release_cycle_lock()
    return jsonify({"ok": True, "message": "Runner detenido.", "runner": build_runner_status()})


@app.route("/runner-restart", methods=["POST"])
def runner_restart():
    set_runner_enabled(True)
    release_cycle_lock()
    started = ensure_runner_autonomous(reason="manual_restart")
    claim_runner_leader(force=True)
    heartbeat_runner(force_claim=True)
    return jsonify({"ok": True, "started": bool(started), "message": "Runner reiniciado.", "runner": build_runner_status()})


@app.route("/runner-debug")
def runner_debug():
    status = build_runner_status()
    return jsonify({
        **status,
        "bet_loop_interval_seconds": BET_LOOP_INTERVAL_SECONDS,
        "runner_heartbeat_seconds": RUNNER_HEARTBEAT_SECONDS,
        "runner_lease_seconds": RUNNER_LEASE_SECONDS,
        "runner_cycle_lock_timeout_seconds": RUNNER_CYCLE_LOCK_TIMEOUT_SECONDS,
    })


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
            "obvious_trade_override": bool(bet.get("obvious_trade_override")),
            "relative_rank_score": round(safe_float(bet.get("relative_rank_score"), 0.0) * 100, 1),
            "quality_rank_pct": round(safe_float(bet.get("quality_rank_pct"), 0.0) * 100, 1),
            "conviction_rank_pct": round(safe_float(bet.get("conviction_rank_pct"), 0.0) * 100, 1),
            "learnability_rank_pct": round(safe_float(bet.get("learnability_rank_pct"), 0.0) * 100, 1),
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
        "obvious_selected": [item for item in LAST_CYCLE_DATA["selected"] if item.get("obvious_trade_override")],
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
            "relative_rank_score": item.get("relative_rank_score"),
            "quality_rank_pct": item.get("quality_rank_pct"),
            "conviction_rank_pct": item.get("conviction_rank_pct"),
            "learnability_rank_pct": item.get("learnability_rank_pct"),
            "tier": item.get("tier"),
            "horizon_bucket": item.get("horizon_bucket"),
            "conclusion_reliability_score": item.get("conclusion_reliability_score"),
            "analysis": item.get("analysis"),
            "research_packet": item.get("packet"),
        })
    return jsonify({"cycle_id": LAST_CYCLE_DATA["cycle_id"], "items": debug_items})


def bet_loop():
    while True:
        try:
            if not is_runner_enabled():
                set_state("runner_health_state", "stopped")
                time.sleep(RUNNER_HEARTBEAT_SECONDS)
                continue
            if claim_runner_leader():
                heartbeat_runner()
                if cycle_due():
                    with app.app_context():
                        execute_bot_cycle(trigger="auto")
                else:
                    set_state("runner_health_state", "healthy")
            time.sleep(RUNNER_HEARTBEAT_SECONDS)
        except Exception:
            logger.exception("bet_loop failed")
            set_state_values({
                "runner_health_state": "delayed",
                "last_cycle_status": "error",
                "last_cycle_error": "bet_loop_failed",
            })
            time.sleep(RUNNER_HEARTBEAT_SECONDS)


def monitor_loop():
    while True:
        time.sleep(MONITOR_LOOP_INTERVAL_SECONDS)
        try:
            monitor_open_positions()
        except Exception:
            logger.exception("monitor_loop failed")


def watchdog_loop():
    while True:
        try:
            ensure_runner_autonomous(reason="watchdog")
            time.sleep(RUNNER_WATCHDOG_INTERVAL_SECONDS)
        except Exception:
            logger.exception("runner watchdog failed")
            time.sleep(RUNNER_WATCHDOG_INTERVAL_SECONDS)


def record_runner_autostart(reason, recovered=False):
    now_iso = to_iso(utc_now())
    payload = {
        "runner_last_autostart_at": now_iso,
        "runner_last_autostart_reason": reason,
    }
    if recovered:
        payload["runner_auto_recovered_at"] = now_iso
        payload["runner_auto_recovered_reason"] = reason
        payload["runner_auto_recovery_count"] = int(get_state("runner_auto_recovery_count", 0)) + 1
    set_state_values(payload)


def ensure_runner_autonomous(reason="autostart"):
    global BACKGROUND_LOOPS_STARTED, BET_LOOP_THREAD, MONITOR_LOOP_THREAD, RUNNER_WATCHDOG_THREAD
    if not should_run_background_loops():
        return False
    recovered = False
    with BACKGROUND_LOOPS_LOCK:
        if not is_runner_enabled():
            logger.warning("Runner enabled flag was false; auto-recovering it reason=%s", reason)
            set_runner_enabled(True)
            recovered = True
        bet_alive = BET_LOOP_THREAD is not None and BET_LOOP_THREAD.is_alive()
        monitor_alive = MONITOR_LOOP_THREAD is not None and MONITOR_LOOP_THREAD.is_alive()
        watchdog_alive = RUNNER_WATCHDOG_THREAD is not None and RUNNER_WATCHDOG_THREAD.is_alive()
        if not bet_alive:
            BET_LOOP_THREAD = threading.Thread(target=bet_loop, daemon=True, name="bet-loop")
            BET_LOOP_THREAD.start()
            recovered = True
        if not monitor_alive:
            MONITOR_LOOP_THREAD = threading.Thread(target=monitor_loop, daemon=True, name="monitor-loop")
            MONITOR_LOOP_THREAD.start()
            recovered = True
        if not watchdog_alive:
            RUNNER_WATCHDOG_THREAD = threading.Thread(target=watchdog_loop, daemon=True, name="runner-watchdog")
            RUNNER_WATCHDOG_THREAD.start()
            recovered = True
        if recovered:
            claim_runner_leader(force=True)
            heartbeat_runner(force_claim=True)
            BACKGROUND_LOOPS_STARTED = True
            recovery_reason = f"{reason}:{'recovered' if bet_alive or monitor_alive or watchdog_alive else 'autostart'}"
            record_runner_autostart(recovery_reason, recovered=True)
            logger.info(
                "Runner autonomous start/recovery completed reason=%s bet_alive_before=%s monitor_alive_before=%s watchdog_alive_before=%s",
                reason,
                bet_alive,
                monitor_alive,
                watchdog_alive,
            )
        elif not BACKGROUND_LOOPS_STARTED:
            BACKGROUND_LOOPS_STARTED = True
    return recovered


def start_background_loops():
    if not should_run_background_loops():
        logger.info("Background loops disabled by config")
        return False
    return ensure_runner_autonomous(reason="start_background_loops")

# ── DASHBOARD / MISC ENDPOINTS ───────────────────────────────
HTML = """<!DOCTYPE html>
<html>
<head>
<title>Polymarket Bot 404</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#050705;--bg2:#0c100d;--panel:#111411;--panel-soft:#171c18;--line:#29412d;--line-2:#4b3566;--text:#eef5ee;--muted:#b2beb2;--soft:#d6dfd6;--accent:#8cff64;--accent-2:#9e5cff;--accent-3:#65d7c8;--warn:#e7d36d;--danger:#ff7d89;--shadow-hard:0 0 0 1px rgba(0,0,0,.72),0 10px 24px rgba(0,0,0,.45);--glow-green:0 0 10px rgba(140,255,100,.15);--glow-violet:0 0 10px rgba(158,92,255,.12)}
*{box-sizing:border-box}
body{margin:0;color:var(--text);font-family:"Segoe UI",Tahoma,Arial,sans-serif;background-color:var(--bg);background-image:linear-gradient(rgba(120,255,120,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(120,255,120,.02) 1px,transparent 1px),linear-gradient(180deg,rgba(255,255,255,.025) 0%,rgba(255,255,255,0) 8%,rgba(0,0,0,0) 92%,rgba(255,255,255,.02) 100%),radial-gradient(circle at top,rgba(158,92,255,.08),transparent 24%);background-size:28px 28px,28px 28px,100% 100%,100% 100%}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:repeating-linear-gradient(180deg,rgba(255,255,255,.015) 0px,rgba(255,255,255,.015) 1px,transparent 2px,transparent 4px);mix-blend-mode:screen;opacity:.18}
.app-shell{max-width:1360px;margin:0 auto;padding:28px 20px 42px}
.topbar{display:flex;justify-content:space-between;gap:28px;align-items:flex-start;margin-bottom:24px}
.logo-lockup{display:flex;align-items:flex-start}
.logo-image{display:block;width:min(560px,42vw);min-width:260px;height:auto;object-fit:contain;filter:drop-shadow(0 0 18px rgba(101,215,200,.12))}
.pill-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.pill{padding:8px 13px;border-radius:2px;border:1px solid rgba(140,255,100,.22);background:rgba(14,19,14,.95);box-shadow:inset 0 0 0 1px rgba(255,255,255,.04);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text);font-family:Consolas,"Lucida Console","Courier New",monospace}
.actions{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}
.btn{padding:12px 15px;border-radius:2px;border:1px solid rgba(140,255,100,.22);background:#121712;color:var(--text);cursor:pointer;font-weight:700;text-transform:uppercase;letter-spacing:.14em;font-size:11px;box-shadow:var(--shadow-hard);clip-path:polygon(0 0,94% 0,100% 100%,6% 100%);font-family:Consolas,"Lucida Console","Courier New",monospace}
.btn:hover{background:#172018;color:#f0fff0;box-shadow:0 0 0 1px rgba(140,255,100,.18),0 0 12px rgba(140,255,100,.08)}
.btn-primary{background:#1b2418;color:#f3ff7a;border-color:rgba(243,229,45,.35)}
.btn-secondary{background:#16131f;color:#d4b7ff;border-color:rgba(158,92,255,.32)}
.btn-danger{background:#211216;color:#ffc1c7;border-color:rgba(255,125,137,.32)}
.dashboard{display:flex;flex-direction:column;gap:18px}
.column{display:flex;flex-direction:column;gap:18px}
.top-priority,.mid-grid,.bottom-grid{display:grid;gap:18px}
.top-priority{grid-template-columns:1.45fr .95fr}
.mid-grid{grid-template-columns:1.1fr .9fr}
.bottom-grid{grid-template-columns:1fr 1fr}
.panel{position:relative;background:linear-gradient(180deg,rgba(18,22,18,.98),rgba(10,13,10,.98));border:1px solid rgba(91,120,91,.36);border-radius:2px;padding:22px;box-shadow:var(--shadow-hard);overflow:hidden}
.panel:before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(90deg,transparent 0,rgba(140,255,100,.03) 46%,rgba(158,92,255,.03) 54%,transparent 100%);opacity:.4}
.hero{display:grid;grid-template-columns:1.3fr .9fr;gap:16px}
.hero-card,.stat,.mini-stat,.trade-card,.watch-card{position:relative;background:linear-gradient(180deg,rgba(22,27,22,.96),rgba(12,15,12,.96));border:1px solid rgba(83,113,83,.34);border-radius:2px;clip-path:polygon(0 0,98% 0,100% 14px,100% 100%,2% 100%,0 calc(100% - 14px))}
.hero-card{padding:24px}
.eyebrow,.section-kicker{font-size:11px;text-transform:uppercase;letter-spacing:.2em;color:#c1d2c1;font-family:Consolas,"Lucida Console","Courier New",monospace}
.hero-value{font-size:32px;letter-spacing:.02em;line-height:1.05;margin-top:10px;font-family:"Segoe UI",Tahoma,Arial,sans-serif;font-weight:800;text-transform:uppercase;font-variant-numeric:tabular-nums}
.hero-copy{margin-top:14px;color:var(--text);font-size:15px;line-height:1.7;font-weight:500}
.status-strip{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-top:16px;padding-top:14px;border-top:1px solid rgba(140,255,100,.12)}
.status-badge,.badge{display:inline-flex;align-items:center;padding:6px 10px;border-radius:2px;font-size:11px;font-weight:700;border:1px solid rgba(140,255,100,.16);background:#141914;color:#e2ebe2;text-transform:uppercase;letter-spacing:.08em;font-family:Consolas,"Lucida Console","Courier New",monospace}
.status-badge{padding:8px 12px;color:var(--accent);background:rgba(140,255,100,.06);border-color:rgba(140,255,100,.26);box-shadow:var(--glow-green)}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.top-stat-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.stat{padding:18px}
.top-stat{padding:20px;min-height:140px}
.stat-label{font-size:11px;color:#d2ddd2;text-transform:uppercase;letter-spacing:.14em;font-family:Consolas,"Lucida Console","Courier New",monospace}
.stat-value{margin-top:10px;font-size:25px;letter-spacing:.01em;line-height:1.1;font-family:"Segoe UI",Tahoma,Arial,sans-serif;font-weight:800;font-variant-numeric:tabular-nums}
.stat-note{margin-top:10px;color:var(--text);font-size:13px;line-height:1.4}
.positive{color:var(--accent)}.negative{color:var(--danger)}.neutral{color:var(--soft)}
.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid rgba(140,255,100,.1)}
.section-title{font-size:20px;font-weight:800;letter-spacing:.02em;text-transform:uppercase;color:#f1f6f1}
.section-sub{margin-top:5px;color:var(--text);font-size:13px}
.cycle-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:14px}
.mini-stat{padding:16px}
.mini-stat strong{display:block;font-size:21px;line-height:1.1;margin-top:8px;font-family:"Segoe UI",Tahoma,Arial,sans-serif;font-weight:800;font-variant-numeric:tabular-nums}
.message-card{padding:16px;border-radius:2px;background:rgba(140,255,100,.06);border:1px solid rgba(140,255,100,.18);color:#e4faf1;line-height:1.6}
.split{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.list{display:grid;gap:12px}
.compact-list{display:grid;gap:10px}
.trade-card,.watch-card{padding:16px}
.trade-top,.watch-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.trade-q,.watch-q{font-size:15px;font-weight:800;line-height:1.5;text-transform:uppercase;color:#f1f6f1}
.badge-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.core{background:rgba(140,255,100,.12);color:#d5ff9d}.secondary{background:rgba(158,92,255,.12);color:#d7bcff}.experimental{background:rgba(101,215,200,.12);color:#b9fff1}
.trade-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}
.meta-box{padding:12px 14px;border-radius:2px;background:#0d110d;border:1px solid rgba(83,113,83,.26)}
.meta-box span{display:block;color:#d0dbd0;font-size:11px;text-transform:uppercase;letter-spacing:.13em;margin-bottom:6px;font-family:Consolas,"Lucida Console","Courier New",monospace}
.meta-box strong{font-size:14px;color:var(--text);line-height:1.5;font-weight:700}
.trade-foot,.watch-foot{margin-top:14px;padding-top:14px;border-top:1px solid rgba(140,255,100,.08);font-size:13px;color:var(--text);line-height:1.65}
.reason-list,.metric-list{display:grid;gap:8px}
.reason-item,.metric-item{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid rgba(140,255,100,.08);font-size:13px;color:var(--text)}
.reason-item:last-child,.metric-item:last-child{border-bottom:none}
.empty{padding:30px 20px;border-radius:2px;border:1px dashed rgba(140,255,100,.18);text-align:center;color:var(--text);background:rgba(255,255,255,.02)}
details{border-top:1px solid rgba(140,255,100,.08);padding-top:14px}
details:first-of-type{border-top:none;padding-top:0}
summary{cursor:pointer;font-weight:700;color:#eef5ee;text-transform:uppercase;letter-spacing:.1em;font-family:Consolas,"Lucida Console","Courier New",monospace}
.summary-copy{margin-top:10px;font-size:13px;color:var(--text);line-height:1.7}
@media(max-width:1180px){.top-priority,.mid-grid,.bottom-grid,.hero,.split{grid-template-columns:1fr}.top-stat-grid,.stat-grid{grid-template-columns:repeat(2,1fr)}.cycle-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.app-shell{padding:18px 14px 28px}.topbar{flex-direction:column}.actions{justify-content:flex-start}.logo-image{width:min(92vw,430px);min-width:0}.top-stat-grid,.stat-grid,.cycle-grid,.trade-grid,.split{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app-shell">
  <div class="topbar">
    <div class="title-block">
      <div class="logo-lockup" aria-label="Polymarket Bot 404">
        <img class="logo-image" src="{{ logo_url }}" alt="Polymarket Bot 404">
      </div>
      <div class="pill-row">
        <div class="pill" id="lab-pill">Lab activo: —</div>
        <div class="pill" id="strategy-pill">Versión: —</div>
        <div class="pill" id="bankroll-pill">Dinero inicial: —</div>
        <div class="pill" id="legacy-pill">Historial viejo: —</div>
        <div class="pill" id="runner-pill">Bot: —</div>
      </div>
    </div>
    <div class="actions">
      <button class="btn" onclick="loadAll()">Actualizar</button>
      <button class="btn" onclick="doMonitor()">Revisar activas</button>
      <button class="btn btn-primary" onclick="runCycle()">Hacer análisis</button>
      <button class="btn" onclick="restartRunner()">Reiniciar bot</button>
      <button class="btn btn-secondary" onclick="fundPaper()">Fondear paper</button>
      <button class="btn btn-danger" onclick="resetLab()">Resetear lab</button>
    </div>
  </div>

  <div class="dashboard">
    <div class="top-priority">
      <div class="panel hero">
        <div class="hero-card">
          <div class="eyebrow">Último análisis</div>
          <div class="hero-value" id="bot-status">Sin datos</div>
          <div class="hero-copy" id="bot-reasoning">Revisó: —<br>Encontró: —</div>
          <div class="status-strip">
            <div class="hero-copy" id="cycle-message">Apostó: —<br>Motivo: —</div>
            <div class="status-badge" id="live-tag">En espera</div>
          </div>
        </div>
        <div class="hero-card">
          <div class="eyebrow">Bot</div>
          <div class="hero-value" id="health-score">Detenido</div>
          <div class="hero-copy" id="health-summary">Último análisis: —<br>Apuestas recientes: —<br>Análisis recientes: —</div>
        </div>
      </div>

      <div class="top-stat-grid">
        <div class="stat top-stat"><div class="stat-label">Dinero disponible</div><div class="stat-value" id="capital-free">$0</div><div class="stat-note">Disponible ahora</div></div>
        <div class="stat top-stat"><div class="stat-label">Apuestas activas</div><div class="stat-value" id="open-trades">0</div><div class="stat-note">Abiertas ahora</div></div>
        <div class="stat top-stat"><div class="stat-label">Último análisis</div><div class="stat-value" id="cycle-stats">0 / 0</div><div class="stat-note">Revisadas / Apuestas</div></div>
        <div class="stat top-stat"><div class="stat-label">Dinero en uso</div><div class="stat-value" id="capital-committed">$0</div><div class="stat-note">En mercado</div></div>
        <div class="stat top-stat"><div class="stat-label">Uso del dinero</div><div class="stat-value" id="portfolio-exposure">0%</div><div class="stat-note">Parte del capital usada</div></div>
      </div>
    </div>

    <div class="mid-grid">
      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Nivel 2</div>
            <div class="section-title">Qué encontró</div>
            <div class="section-sub">Oportunidades del último análisis.</div>
          </div>
        </div>
        <div class="cycle-grid">
          <div class="mini-stat"><div class="eyebrow">Revisadas</div><strong id="cycle-analyzed">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Preseleccionadas</div><strong id="cycle-shortlist">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Apuestas hechas</div><strong id="cycle-selected">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Oportunidades</div><strong id="cycle-watchlist">0</strong></div>
          <div class="mini-stat"><div class="eyebrow">Descartadas</div><strong id="cycle-rejected">0</strong></div>
        </div>
        <div class="panel" style="padding:14px;margin-top:14px">
          <div class="section-kicker">Resumen del análisis</div>
          <div class="metric-list" id="cycle-mix"><div class="metric-item"><span>Sin datos</span><strong>—</strong></div></div>
        </div>
        <div class="panel" style="padding:14px;margin-top:14px">
          <div class="section-kicker">Posibles apuestas</div>
          <div class="compact-list" id="watchlist"><div class="empty">No hay oportunidades detectadas en este análisis.</div></div>
        </div>
      </div>

      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Nivel 2</div>
            <div class="section-title">Por qué no apostó</div>
            <div class="section-sub">Razones principales.</div>
          </div>
        </div>
        <div class="reason-list" id="blockers"><div class="reason-item"><span>Sin motivos todavía</span><strong>—</strong></div></div>
        <div class="panel" style="padding:14px;margin-top:14px">
          <div class="section-kicker">Resumen actual</div>
          <div class="metric-list">
            <div class="metric-item"><span>Fuertes / Buenas / Exploración</span><strong id="core-exp">0 / 0 / 0</strong></div>
            <div class="metric-item"><span>Oportunidades</span><strong id="watchlist-count">0</strong></div>
            <div class="metric-item"><span>Ganancia total</span><strong id="total-pnl">0</strong></div>
          </div>
        </div>
      </div>
    </div>

    <div class="bottom-grid">
      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Nivel 3</div>
            <div class="section-title">Apuestas activas</div>
            <div class="section-sub">Detalle de lo que está abierto.</div>
          </div>
        </div>
        <div class="list" id="bets"><div class="empty">Todavía no hay apuestas activas.</div></div>
      </div>

      <div class="panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Nivel 3</div>
            <div class="section-title">Métricas</div>
            <div class="section-sub">Información secundaria.</div>
          </div>
        </div>
        <details open><summary>Bot</summary><div class="summary-copy" id="runner-summary">Cargando…</div></details>
        <details open><summary>Resultados</summary><div class="summary-copy" id="perf-summary">Cargando…</div></details>
        <details><summary>Reparto de apuestas</summary><div class="summary-copy" id="mix-summary">Cargando…</div></details>
        <details><summary>Aprendizaje</summary><div class="summary-copy" id="learning-summary">Cargando…</div></details>
        <details><summary>Patrones</summary><div class="summary-copy" id="pattern-summary">Cargando…</div></details>
        <details><summary>Detalle</summary><div class="summary-copy" id="debug-summary">Cargando…</div></details>
      </div>
    </div>
  </div>
</div>
<script>
function money(value){return '$'+Math.round(value||0).toLocaleString('en-US')}
function pct(value){return Math.round((value||0)*100)+'%'}
function metricClass(value){return value>0?'positive':value<0?'negative':'neutral'}
function titleCase(value){return (value||'—').replaceAll('_',' ')}
function humanLabel(value){
  const raw=(value||'').toString()
  const map={
    healthy:'funcionando',
    delayed:'lento',
    stale:'frenado',
    stopped:'detenido',
    success:'bien',
    error:'error',
    skipped:'omitido',
    never:'sin datos',
    core:'fuertes',
    secondary:'buenas',
    experimental:'exploración',
    exploratory:'exploración',
    watchlist:'oportunidades',
    shortlist:'preseleccionadas',
    selected:'apuestas hechas',
    rejected:'descartadas',
    analyzed:'revisadas'
  }
  return map[raw]||titleCase(raw)
}
function humanReason(value){
  const raw=(value||'').toString()
  const map={
    duplicate_semantic_overlap:'Demasiado parecida a otra apuesta',
    duplicate_market_id:'Ya existe una apuesta igual',
    duplicate_question:'Ya existe una apuesta igual',
    tier_skip:'No era lo suficientemente buena',
    low_reliability:'Poca confianza',
    low_score:'No era lo suficientemente buena',
    weak_edge_or_confidence:'La ventaja no era clara',
    low_evidence:'Había poca información',
    llm_skip:'No parecía una buena apuesta',
    recently_evaluated:'Se revisó hace poco',
    cycle_limit:'Ya había suficientes apuestas por ahora',
    core_cycle_limit:'Ya había suficientes apuestas fuertes',
    secondary_cycle_limit:'Ya había suficientes apuestas buenas',
    exploratory_cycle_limit:'Ya había suficiente exploración',
    max_open_positions:'Ya había demasiadas apuestas abiertas',
    max_total_exposure:'Ya había demasiado dinero en uso',
    max_category_exposure:'Ya había demasiado riesgo en ese tema',
    max_side_exposure:'Ya había demasiado riesgo en esa dirección',
    max_thesis_exposure:'Ya había demasiado riesgo parecido',
    long_dated_budget_full:'Ya había demasiado dinero trabado por mucho tiempo',
    size_too_small:'Era demasiado chica',
    cycle_lock_busy:'El bot ya estaba trabajando',
    market_quality:'No parecía un mercado confiable'
  }
  if(map[raw]) return map[raw]
  if(raw.includes('_')) return titleCase(raw)
  return raw||'—'
}
function shortReason(blockers){
  const first=Object.keys(blockers||{})[0]
  return first?humanReason(first):'Sin motivo fuerte'
}
function bucketLabel(value){if(value==='experimental')return 'exploración';if(value==='secondary')return 'buena';if(value==='core')return 'fuerte';return titleCase(value)}
function timeAgo(value){if(!value)return '—';const then=new Date(value);const diff=Math.max(0,Math.floor((Date.now()-then.getTime())/1000));if(diff<60)return `${diff}s`;const m=Math.floor(diff/60);if(m<60)return `${m}m`;const h=Math.floor(m/60);if(h<24)return `${h}h ${m%60}m`;const d=Math.floor(h/24);return `${d}d ${h%24}h`}
function objectLines(obj, empty='—'){const entries=Object.entries(obj||{});if(!entries.length)return empty;return entries.map(([k,v])=>`${humanLabel(k)}: ${typeof v==='object'?JSON.stringify(v):v}`).join('<br>')}
async function postJson(url,payload){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})});return res.json()}

function setValue(id,text,raw){const el=document.getElementById(id);el.textContent=text;if(raw!==undefined){el.className=(el.className.includes('hero-value')?'hero-value ':'stat-value ')+metricClass(raw)}}

function renderTradeCard(b){return `<div class='trade-card'><div class='trade-top'><div><div class='trade-q'>${b.question}</div><div class='badge-row'><span class='badge ${b.trade_class}'>${bucketLabel(b.trade_class)}</span><span class='badge'>${b.horizon_bucket||'—'}</span><span class='badge'>${b.category}</span>${b.obvious_trade_override?"<span class='badge'>clara</span>":""}</div></div><div class='badge'>${b.status_text}</div></div><div class='trade-grid'><div class='meta-box'><span>Apuesta</span><strong>${b.side} · ${money(b.amount)}</strong></div><div class='meta-box'><span>Resultado</span><strong class='${metricClass(b.pnl||0)}'>${b.pnl_text}</strong></div><div class='meta-box'><span>Entrada / Ahora</span><strong>${b.price_entry||0} / ${b.price_current||0}</strong></div><div class='meta-box'><span>Ventaja / Confianza</span><strong>${b.edge}pp · ${b.confidence}/10</strong></div><div class='meta-box'><span>Confianza / Facilidad</span><strong>${b.reliability}% · ${b.ease_of_win}%</strong></div><div class='meta-box'><span>Prioridad</span><strong>${b.portfolio_priority_score}% · ${b.relative_rank_score||0}%</strong></div></div><div class='trade-foot'><strong>Señal:</strong> ${b.key_signal||'—'}<br><strong>Cuándo dejarla:</strong> ${b.invalidation_condition||'—'}<br><strong>Por qué se hizo:</strong> ${b.reasoning||'—'}</div></div>`}
function renderWatchCard(item){return `<div class='watch-card'><div class='watch-top'><div><div class='watch-q'>${item.question}</div><div class='badge-row'><span class='badge ${item.trade_class||'watch'}'>${bucketLabel(item.trade_class||'watchlist')}</span><span class='badge'>${item.horizon_bucket||'—'}</span>${item.obvious_trade_override?"<span class='badge'>clara</span>":""}</div></div></div><div class='trade-grid'><div class='meta-box'><span>Prioridad</span><strong>${Math.round((item.portfolio_priority_score||0)*100)}%</strong></div><div class='meta-box'><span>Oportunidad</span><strong>${Math.round((item.opportunity_score||0)*100)}%</strong></div><div class='meta-box'><span>Confianza</span><strong>${Math.round((item.reliability||0)*100)}%</strong></div><div class='meta-box'><span>Facilidad</span><strong>${Math.round((item.learnability||0)*100)}% · ${Math.round((item.ease_of_win||0)*100)}%</strong></div></div><div class='watch-foot'>${humanReason(item.reason)||'Todavía no es momento de apostar.'}</div></div>`}

async function loadMetrics(){const d=await fetch('/metrics').then(r=>r.json());document.getElementById('lab-pill').textContent=`Lab activo: ${d.current_lab_epoch||'—'}`;document.getElementById('strategy-pill').textContent=`Versión: ${d.current_strategy_version||'—'}`;document.getElementById('bankroll-pill').textContent=`Dinero inicial: ${money(d.paper_starting_balance)}`;document.getElementById('legacy-pill').textContent=`Historial viejo: ${d.legacy_trades_archived||0}`;document.getElementById('runner-pill').textContent=`Bot: ${humanLabel(d.runner_health_state||'unknown')}`;setValue('capital-free',money(d.capital_free),d.capital_free);setValue('capital-committed',money(d.capital_committed),-d.capital_committed);setValue('portfolio-exposure',pct(d.portfolio_exposure),(d.portfolio_exposure||0)<0.7?1:-1);setValue('total-pnl',(d.total_pnl>=0?'+':'')+Math.round(d.total_pnl||0),d.total_pnl||0);document.getElementById('open-trades').textContent=d.open_current_lab||0;document.getElementById('core-exp').textContent=`${d.core_open||0} / ${d.secondary_open||0} / ${d.experimental_open||0}`;document.getElementById('cycle-stats').textContent=`${d.markets_analyzed_last_cycle||0} / ${d.positions_per_cycle_last||0}`;document.getElementById('watchlist-count').textContent=d.watchlist_last_cycle||0;const state=d.runner_health_state||'stale';const stateText=state==='healthy'?'BOT FUNCIONANDO':state==='delayed'?'BOT LENTO':'BOT FRENADO';const healthEl=document.getElementById('health-score');healthEl.textContent=stateText;healthEl.className=`hero-value ${state==='healthy'?'positive':state==='delayed'?'neutral':'negative'}`;document.getElementById('health-summary').innerHTML=`Último análisis: <strong>${timeAgo(d.last_cycle_finished_at||d.last_cycle_started_at)}</strong><br>Apuestas recientes: <strong>${d.trades_last_hour||0}</strong><br>Análisis recientes: <strong>${d.cycles_last_hour||0}</strong>`;document.getElementById('perf-summary').innerHTML=`Resultado total <strong>${money(d.total_pnl)}</strong>. Cerrado <strong>${money(d.realized_pnl)}</strong>, abierto <strong>${money(d.unrealized_pnl)}</strong>. Tiempo medio <strong>${d.average_hold_time_hours||0}h</strong>.`;document.getElementById('runner-summary').innerHTML=`Estado: <strong>${humanLabel(d.runner_health_state||'unknown')}</strong><br>Automático: <strong>${d.runner_autonomous?'sí':'no'}</strong><br>Última señal: <strong>${timeAgo(d.runner_last_heartbeat)}</strong><br>Último análisis iniciado: <strong>${timeAgo(d.last_cycle_started_at)}</strong><br>Último análisis terminado: <strong>${timeAgo(d.last_cycle_finished_at)}</strong><br>Último análisis bueno: <strong>${timeAgo(d.last_successful_cycle_at)}</strong><br>Estado del último análisis: <strong>${humanLabel(d.last_cycle_status||'never')}</strong><br>Duración: <strong>${Math.round((d.last_cycle_duration_ms||0)/1000)}s</strong><br>Conteos: <strong>${d.last_cycle_analyzed||0}</strong> revisadas / <strong>${d.last_cycle_shortlist||0}</strong> preseleccionadas / <strong>${d.last_cycle_selected||0}</strong> apuestas / <strong>${d.last_cycle_watchlist||0}</strong> oportunidades / <strong>${d.last_cycle_rejected||0}</strong> descartadas<br>Análisis última hora: <strong>${d.cycles_last_hour||0}</strong> · Apuestas última hora: <strong>${d.trades_last_hour||0}</strong>${d.last_cycle_error?`<br>Último error: <strong>${d.last_cycle_error}</strong>`:''}`;document.getElementById('mix-summary').innerHTML=`Apuestas por tipo:<br>${objectLines(d.open_count_by_bucket,'Todavía no hay apuestas activas.')}<br><br>Dinero por tipo:<br>${objectLines(d.open_amount_by_bucket,'Todavía no hay dinero en uso.')}<br><br>Tamaño medio:<br>${objectLines(d.average_size_by_bucket,'Todavía no hay tamaños para mostrar.')}<br><br>Prioridad media:<br>${objectLines(d.average_priority_by_bucket,'Todavía no hay resumen.')}<br><br>Por categoría:<br>${objectLines(d.portfolio_exposure_by_category,'Todavía no hay exposición activa.')}<br><br>Por tiempo:<br>${objectLines(d.portfolio_exposure_by_horizon,'Todavía no hay apuestas abiertas.')}`;document.getElementById('learning-summary').innerHTML=`Acierto por tipo:<br>${objectLines(d.winrate_core_vs_exploratory,'Aún no hay historial suficiente.')}<br><br>Acierto por velocidad:<br>${objectLines(d.winrate_by_learning_velocity,'Aún no hay historial suficiente.')}<br><br>Acierto por tiempo:<br>${objectLines(d.winrate_by_time_to_resolution_bucket,'Aún no hay grupos suficientes.')}<br><br>Apuestas claras en el último análisis: <strong>${d.obvious_trades_last_cycle||0}</strong>`;document.getElementById('pattern-summary').innerHTML=`Lo que más ganó: ${JSON.stringify(d.top_winning_patterns||[])}<br>Lo que más perdió: ${JSON.stringify(d.top_losing_patterns||[])}<br><br>Resultado por tipo:<br>${objectLines(d.pnl_by_trade_class,'Todavía no hay resultados por tipo.')}<br><br>Apuestas claras vs no claras:<br>${objectLines(d.performance_by_obviousness,'Todavía no hay suficiente historial.')}`;document.getElementById('debug-summary').innerHTML=`Bot principal: <strong>${d.runner_leader_id||'—'}</strong><br>Inicio automático: <strong>${d.runner_last_autostart_reason||'—'}</strong><br>Auto-recuperación: <strong>${d.runner_auto_recovered_reason||'—'}</strong><br>Historial viejo: <strong>${d.legacy_trades_archived||0}</strong><br>Descartadas por poca evidencia: <strong>${d.discarded_low_evidence_last_cycle||0}</strong><br>Descartadas por repetición o límite: <strong>${d.discarded_correlation_last_cycle||0}</strong><br>Apuestas / oportunidades / descartadas: <strong>${(d.selection_mix_last_cycle||{}).selected||0}</strong> / <strong>${(d.selection_mix_last_cycle||{}).watchlist||0}</strong> / <strong>${(d.selection_mix_last_cycle||{}).rejected||0}</strong><br>Apuestas última hora: <strong>${d.trades_last_hour||0}</strong> · Análisis última hora: <strong>${d.cycles_last_hour||0}</strong>`}
async function loadCycle(){const d=await fetch('/candidate-scores').then(r=>r.json());const runner=await fetch('/runner-status').then(r=>r.json());const s=d.summary||{};const blockers=d.blockers||{};const mainReason=shortReason(blockers);document.getElementById('cycle-analyzed').textContent=s.analyzed||0;document.getElementById('cycle-shortlist').textContent=s.shortlist||0;document.getElementById('cycle-selected').textContent=s.selected||0;document.getElementById('cycle-watchlist').textContent=s.watchlist||0;document.getElementById('cycle-rejected').textContent=s.rejected||0;document.getElementById('bot-status').textContent=(s.selected||0)>0?`${s.selected||0} APUESTAS`:(s.watchlist||0)>0?'SIN APUESTAS':'SIN SEÑAL';document.getElementById('bot-reasoning').innerHTML=`Revisó: <strong>${s.analyzed||0}</strong><br>Encontró: <strong>${s.shortlist||0}</strong>`;document.getElementById('cycle-message').innerHTML=`Apostó: <strong>${s.selected||0}</strong><br>Motivo: <strong>${mainReason}</strong>`;document.getElementById('cycle-mix').innerHTML=`<div class='metric-item'><span>Fuertes</span><strong>${s.core_selected||0}</strong></div><div class='metric-item'><span>Buenas</span><strong>${s.secondary_selected||0}</strong></div><div class='metric-item'><span>Exploración</span><strong>${s.exploratory_selected||0}</strong></div><div class='metric-item'><span>Claras</span><strong>${s.obvious_selected||0}</strong></div>`;document.getElementById('blockers').innerHTML=Object.entries(blockers).length?Object.entries(blockers).map(([k,v])=>`<div class='reason-item'><span>${humanReason(k)}</span><strong>${v}</strong></div>`).join(''):"<div class='reason-item'><span>No hubo un problema importante</span><strong>OK</strong></div>";document.getElementById('watchlist').innerHTML=(d.watchlist||[]).length?(d.watchlist||[]).slice(0,8).map(renderWatchCard).join(''):"<div class='empty'>No hay oportunidades detectadas en este análisis.</div>";document.getElementById('live-tag').textContent=(runner.runner_health_state||'stale')==='healthy'?'Bot funcionando':(runner.runner_health_state||'stale')==='delayed'?'Bot lento':'Bot frenado'}
async function loadBets(){const d=await fetch('/bets').then(r=>r.json());document.getElementById('bets').innerHTML=d.length?d.map(renderTradeCard).join(''):"<div class='empty'>Todavía no hay apuestas activas.</div>"}
async function runCycle(){document.getElementById('bot-status').textContent='Haciendo análisis';document.getElementById('bot-reasoning').textContent='Buscando oportunidades y decidiendo si apostar.';const d=await fetch('/bot-bet',{method:'POST'}).then(r=>r.json());document.getElementById('bot-status').textContent=d.placed?'Hizo apuestas':'No apostó';document.getElementById('bot-reasoning').textContent=d.message||d.reasoning||'';await loadAll()}
async function doMonitor(){document.getElementById('bot-status').textContent='Revisando apuestas';const d=await fetch('/monitor',{method:'POST'}).then(r=>r.json());document.getElementById('bot-reasoning').textContent=d.message||'Revisión hecha';await loadAll()}
async function restartRunner(){document.getElementById('bot-status').textContent='Reiniciando bot';const d=await fetch('/runner-restart',{method:'POST'}).then(r=>r.json());document.getElementById('bot-reasoning').textContent=d.message||d.error||'';await loadAll()}
async function resetLab(){if(!confirm('Esto archivará el laboratorio actual y arrancará uno nuevo. ¿Continuar?'))return;const balance=prompt('Balance inicial del nuevo lab','50000');const d=await postJson('/lab-reset',{balance:Number(balance||50000)});document.getElementById('bot-status').textContent=d.ok?'Lab reiniciado':'Error';document.getElementById('bot-reasoning').textContent=d.message||d.error||'';await loadAll()}
async function fundPaper(){const amount=prompt('Capital paper a agregar','10000');if(!amount)return;const d=await postJson('/fund-paper',{amount:Number(amount)});document.getElementById('bot-status').textContent=d.ok?'Capital agregado':'Error';document.getElementById('bot-reasoning').textContent=d.message||d.error||'';await loadAll()}
async function loadAll(){await Promise.all([loadMetrics(),loadCycle(),loadBets()])}
loadAll();setInterval(loadAll,12000)
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML, logo_url=url_for("static", filename="polymarket-404.png"))


@app.before_request
def keep_runner_autonomous():
    if should_run_background_loops():
        ensure_runner_autonomous(reason="request_self_heal")


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


# Safe autonomous autostart: multiple web workers may import this module, so
# the runner uses a persisted leader lease + cycle lock to avoid duplicates.
if should_run_background_loops():
    ensure_runner_autonomous(reason="module_import")


if __name__ == "__main__":
    ensure_runner_autonomous(reason="main_start")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
