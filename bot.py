import os
import json
import time
import math
import signal
from datetime import datetime, timezone
from dateutil import tz

from binance.client import Client
from binance.exceptions import BinanceAPIException

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========
#   PARAMS
# ==========
SYMBOL = os.getenv("SYMBOL", "BTCUSDC")       # paire
MAX_USDC = float(os.getenv("MAX_USDC", "1000"))  # budget max
TRADE_FRACTION = float(os.getenv("TRADE_FRACTION", "0.02"))  # 2% du budget max / trade
TP_PCT = float(os.getenv("TP_PCT", "0.002"))   # +0.2% take-profit
SL_PCT = float(os.getenv("SL_PCT", "0.003"))   # -0.3% stop-loss
SLEEP_SEC = int(os.getenv("SLEEP_SEC", "20"))  # boucle

# Mode test par défaut (tu devras mettre LIVE=1 pour le vrai)
LIVE = os.getenv("LIVE_TRADING", "0") == "1"

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()  # l’ID du classeur
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS", "").strip()

# Binance API
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

PARIS_TZ = tz.gettz("Europe/Paris")

# État global simple
running = True
position = None              # {"qty": float, "cost": float, "tp": float, "sl": float}
daily_pnl_usdc = 0.0
last_pnl_date = None

# ==========
#  UTILS
# ==========
def now_paris():
    return datetime.now(tz=PARIS_TZ)

def day_key(dt):
    return dt.strftime("%Y-%m-%d")

def iso_week(dt):
    return dt.isocalendar()[1]

def log(*args):
    print(*args, flush=True)

# ==========
#   SHEETS
# ==========
def gs_client():
    if not GOOGLE_CREDENTIALS:
        raise ValueError("La variable d'env GOOGLE_CREDENTIALS est absente dans Railway.")
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(credentials)

def get_worksheet(gc, name):
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=2000, cols=10)
        if name == "Journal":
            ws.update("A1:C1", [["date", "pnl_usdc", "comment"]])
        elif name == "Hebdo":
            ws.update("A1:B1", [["Semaine", "Total_USDC"]])
        return ws

def append_journal(pnl, comment=""):
    """Ajoute une ligne dans Journal pour la date du jour."""
    if not SPREADSHEET_ID:
        return
    gc = gs_client()
    ws = get_worksheet(gc, "Journal")
    today = day_key(now_paris())
    ws.append_row([today, round(pnl, 6), comment])

def update_hebdo(pnl):
    """Cumul par semaine (feuille Hebdo)."""
    if not SPREADSHEET_ID:
        return
    gc = gs_client()
    ws = get_worksheet(gc, "Hebdo")
    week = iso_week(now_paris())
    records = ws.get_all_records()
    weeks = [r["Semaine"] for r in records] if records else []
    if week in weeks:
        # +2: header + 1-based index
        idx = weeks.index(week) + 2
        current = ws.cell(idx, 2).value
        current = float(current) if current else 0.0
        ws.update_cell(idx, 2, round(current + pnl, 6))
    else:
        ws.append_row([week, round(pnl, 6)])

def flush_daily_pnl():
    global daily_pnl_usdc
    if abs(daily_pnl_usdc) > 1e-9:
        append_journal(daily_pnl_usdc, "Auto close day")
        update_hebdo(daily_pnl_usdc)
        log(f"[{day_key(now_paris())}] PNL Journal+Hebdo écrit : {daily_pnl_usdc:.6f} USDC")
        daily_pnl_usdc = 0.0

# ==========
#  BINANCE
# ==========
def binance_client():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise ValueError("BINANCE_API_KEY / BINANCE_API_SECRET manquent.")

    c = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET, testnet=(not LIVE))
    # Testnet spot
    if not LIVE:
        # Endpoint testnet spot (binance.vision)
        c.API_URL = "https://testnet.binance.vision/api"
    return c

def get_symbol_info(client, symbol):
    info = client.get_symbol_info(symbol)
    if not info:
        raise ValueError(f"Symbol info introuvable pour {symbol}")
    lot_filter = next(f for f in info["filters"] if f["filterType"] == "LOT_SIZE")
    tick_filter = next(f for f in info["filters"] if f["filterType"] == "PRICE_FILTER")
    step_size = float(lot_filter["stepSize"])
    min_qty = float(lot_filter["minQty"])
    tick_size = float(tick_filter["tickSize"])
    return {
        "step": step_size,
        "min_qty": min_qty,
        "tick": tick_size
    }

def round_step(qty, step):
    if step <= 0:
        return qty
    return math.floor(qty / step) * step

def round_tick(price, tick):
    if tick <= 0:
        return price
    return math.floor(price / tick) * tick

def get_last_price(client):
    t = client.get_symbol_ticker(symbol=SYMBOL)
    return float(t["price"])

def get_free_asset(client, asset):
    b = client.get_asset_balance(asset=asset)
    return float(b["free"]) if b else 0.0

def market_buy(client, usdc_amount, sym_info):
    price = get_last_price(client)
    qty = usdc_amount / price
    qty = max(round_step(qty, sym_info["step"]), sym_info["min_qty"])
    if qty * price < 5:  # mini notionnel de Binance
        return None, None

    try:
        order = client.order_market_buy(symbol=SYMBOL, quantity=qty)
        fills = order.get("fills", [])
        fill_price = price
        if fills:
            total_q = sum(float(f["qty"]) for f in fills)
            total_paid = sum(float(f["price"]) * float(f["qty"]) for f in fills)
            fill_price = total_paid / total_q if total_q > 0 else price
        log(f"ACHAT {SYMBOL} qty={qty} ~price={fill_price} | {'DIRECT' if LIVE else 'TEST'}")
        return qty, fill_price
    except BinanceAPIException as e:
        log("ERREUR BUY:", e)
        return None, None

def market_sell(client, qty):
    try:
        order = client.order_market_sell(symbol=SYMBOL, quantity=qty)
        fills = order.get("fills", [])
        price = get_last_price(client)
        if fills:
            total_q = sum(float(f["qty"]) for f in fills)
            total_got = sum(float(f["price"]) * float(f["qty"]) for f in fills)
            price = total_got / total_q if total_q > 0 else price
        log(f"VENTE {SYMBOL} qty={qty} ~price={price} | {'DIRECT' if LIVE else 'TEST'}")
        return price
    except BinanceAPIException as e:
        log("ERREUR SELL:", e)
        return None

# ==========
#   BOT
# ==========
def try_trade_once(client, sym_info):
    """Stratégie super simple : si aucune position, acheter un petit pourcentage;
       si en position, sortir TP/SL."""
    global position, daily_pnl_usdc

    last = get_last_price(client)

    # Pas de position : on achète un petit montant
    if position is None:
        free_usdc = get_free_asset(client, "USDC")
        budget = min(MAX_USDC, free_usdc)
        if budget < 10:
            log("USDC insuffisant pour un trade.")
            return

        usdc_to_use = max(10, budget * TRADE_FRACTION)  # mini 10 USDC
        qty, entry = market_buy(client, usdc_to_use, sym_info)
        if qty and entry:
            tp = round_tick(entry * (1 + TP_PCT), sym_info["tick"])
            sl = round_tick(entry * (1 - SL_PCT), sym_info["tick"])
            position = {"qty": qty, "cost": entry, "tp": tp, "sl": sl}
            log(f"Position ouverte: qty={qty} cost={entry} tp={tp} sl={sl}")
        return

    # En position : vérifier TP/SL
    if position:
        qty = position["qty"]
        cost = position["cost"]
        tp = position["tp"]
        sl = position["sl"]

        if last >= tp:
            # Take Profit
            out = market_sell(client, qty)
            if out:
                pnl = (out - cost) * qty
                daily_pnl_usdc += pnl
                log(f"TP atteint. PNL réalisé: {pnl:.6f} USDC | Daily: {daily_pnl_usdc:.6f}")
                position = None
            return

        if last <= sl:
            # Stop Loss
            out = market_sell(client, qty)
            if out:
                pnl = (out - cost) * qty
                daily_pnl_usdc += pnl
                log(f"SL atteint. PNL réalisé: {pnl:.6f} USDC | Daily: {daily_pnl_usdc:.6f}")
                position = None
            return

def handle_day_rollover():
    """Si on passe à un nouveau jour (Europe/Paris), écrire le PnL jour et reset."""
    global last_pnl_date
    today = day_key(now_paris())
    if last_pnl_date is None:
        last_pnl_date = today
        return
    if today != last_pnl_date:
        flush_daily_pnl()
        log(f"--- Nouveau jour {today} ---")
        last_pnl_date = today

def on_sigterm(signum, frame):
    global running
    log("SIGTERM reçu → arrêt propre.")
    running = False

def main():
    global running

    # Sécurité Google Sheets
    if not SPREADSHEET_ID:
        log("⚠️  SPREADSHEET_ID manquant : le bot tournera sans écrire dans Google Sheets.")
    else:
        log("Google Sheets OK (SPREADSHEET_ID fourni).")

    # Binance
    client = binance_client()
    sym_info = get_symbol_info(client, SYMBOL)

    log(f"Démarrage bot | Symbol={SYMBOL} | LIVE={LIVE} | Budget max: {MAX_USDC} USDC")
    signal.signal(signal.SIGTERM, on_sigterm)

    while running:
        try:
            handle_day_rollover()
            try_trade_once(client, sym_info)
        except Exception as e:
            log("Loop error:", e)
        time.sleep(SLEEP_SEC)

    # À l’arrêt, on écrit le PnL restant du jour
    flush_daily_pnl()
    log("Arrêt terminé.")

if __name__ == "__main__":
    main()
