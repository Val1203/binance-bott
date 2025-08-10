import os, json, time, datetime as dt
import pandas as pd
from pathlib import Path

# === CONFIG TRADING ============================================================
PAIR            = os.getenv("PAIR", "BTCUSDC")
MAX_CAP_USDC    = float(os.getenv("MAX_CAP_USDC", "1000"))   # capital max alloué
ORDER_NOTIONAL  = float(os.getenv("ORDER_NOTIONAL", "25"))   # ~taille d'un ordre (USDC)
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.05"))/100  # ex: 0.05% -> scalps
STOP_LOSS_PCT   = float(os.getenv("STOP_LOSS_PCT", "0.20"))/100    # ex: 0.20%
LIVE_TRADING    = os.getenv("LIVE_TRADING", "0") == "1"      # 1 = compte réel, 0 = test

# === FICHIERS (Railway) =======================================================
DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE  = DATA_DIR / "state.json"           # position + PRU
TRADES_CSV  = DATA_DIR / "trades.csv"           # append des trades
REPORT_XLSX = DATA_DIR / "rapport_trading.xlsx" # rapport Excel complet

# === ETAT (position & PRU) ====================================================
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"position_qty": 0.0, "avg_cost": 0.0, "used_cap": 0.0}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s))

state = load_state()

# === OUTILS ===================================================================
def now_paris():
    return dt.datetime.utcnow() + dt.timedelta(hours=2)

def df_trades():
    if TRADES_CSV.exists():
        return pd.read_csv(TRADES_CSV)
    return pd.DataFrame(columns=[
        "time", "side", "symbol", "price", "qty", "notional", "fee",
        "realized_pnl", "note"
    ])

def append_trade(side, price, qty, fee=0.0, realized_pnl=0.0, note=""):
    d = df_trades()
    notional = price * qty
    d.loc[len(d)] = [
        now_paris().strftime("%Y-%m-%d %H:%M:%S"), side, PAIR,
        round(price, 6), round(qty, 8), round(notional, 2),
        round(fee, 2), round(realized_pnl, 2), note
    ]
    d.to_csv(TRADES_CSV, index=False)

def update_position_on_buy(price, qty):
    """moyenne pondérée pour le PRU"""
    global state
    pos = state["position_qty"]
    avg = state["avg_cost"]
    new_pos = pos + qty
    if new_pos <= 0:
        state["position_qty"] = 0.0
        state["avg_cost"] = 0.0
    else:
        state["avg_cost"] = (pos*avg + qty*price) / new_pos
        state["position_qty"] = new_pos
    state["used_cap"] = min(state.get("used_cap", 0.0) + price*qty, MAX_CAP_USDC)
    save_state(state)

def update_position_on_sell(price, qty):
    """réalise le PNL sur la quantité vendue"""
    global state
    avg = state["avg_cost"]
    pos = state["position_qty"]
    qty = min(qty, pos)  # sécurité
    realized = (price - avg) * qty
    state["position_qty"] = round(pos - qty, 8)
    if state["position_qty"] == 0:
        state["avg_cost"] = 0.0
        state["used_cap"] = 0.0
    save_state(state)
    return realized

# === RAPPORTS EXCEL ============================================================
def make_reports():
    d = df_trades()
    if d.empty:
        return

    d["time"] = pd.to_datetime(d["time"])
    d["date"] = d["time"].dt.date
    d["week"] = d["time"].dt.to_period("W").astype(str)
    d["month"] = d["time"].dt.to_period("M").astype(str)

    by_day   = d.groupby("date")[["realized_pnl"]].sum().reset_index()
    by_week  = d.groupby("week")[["realized_pnl"]].sum().reset_index()
    by_month = d.groupby("month")[["realized_pnl"]].sum().reset_index()

    summary = pd.DataFrame({
        "metric": ["Total réalisé", "Jours avec trade", "PNL moyen/jour"],
        "value": [
            round(d["realized_pnl"].sum(), 2),
            int(by_day.shape[0]),
            round(d["realized_pnl"].sum() / max(1, by_day.shape[0]), 2)
        ]
    })

    with pd.ExcelWriter(REPORT_XLSX, engine="openpyxl") as xw:
        d.to_excel(xw, sheet_name="TRADES", index=False)
        by_day.to_excel(xw, sheet_name="JOURNALIER", index=False)
        by_week.to_excel(xw, sheet_name="HEBDO", index=False)
        by_month.to_excel(xw, sheet_name="MENSUEL", index=False)
        summary.to_excel(xw, sheet_name="RESUME", index=False)

# === TAILLE D’ORDRE ET GARDE-FOUS ============================================
def allowed_notional_left():
    """combien de capital il reste à utiliser sans dépasser MAX_CAP_USDC"""
    used = float(state.get("used_cap", 0.0))
    return max(0.0, MAX_CAP_USDC - used)

def compute_order_qty(price):
    """taille de l’ordre en BTC à partir de ORDER_NOTIONAL et du capital restant"""
    notional = min(ORDER_NOTIONAL, allowed_notional_left())
    if notional <= 0:
        return 0.0
    qty = notional / price
    # arrondi sécurité (ex: 1e-6 BTC min)
    return max(0.000001, round(qty, 6))

# === PLACEHOLDERS BINANCE =====================================================
# Adapte ces deux fonctions à ta fonction actuelle d’envoi d’ordre.
# Ici on les simule: retourne toujours status=TEST_OK et price passé en param.
def place_buy(price, qty):
    # --> ici mets ton appel client.order_market_buy(symbol=PAIR, quoteOrderQty=notional) ou équivalent
    return {"status": "TEST_OK", "price": price, "executedQty": qty, "fee": 0.0}

def place_sell(price, qty):
    # --> ici mets ton appel client.order_market_sell(symbol=PAIR, quantity=qty)
    return {"status": "TEST_OK", "price": price, "executedQty": qty, "fee": 0.0}

# === LOGIQUE EXEMPLE : micro-scalps ===========================================
def trading_loop(get_price_func):
    """
    get_price_func() doit retourner le prix spot BTC/USDC (float).
    Boucle: achète une petite taille puis revend avec TP/SL. Ajoute chaque trade au CSV
    et régénère l’Excel à chaque cycle.
    """
    while True:
        price = float(get_price_func())
        qty   = compute_order_qty(price)
        if qty > 0:
            # BUY
            r = place_buy(price, qty)
            if r["status"] == "TEST_OK":
                update_position_on_buy(price, qty)
                append_trade("BUY", price, qty, note="scalp buy")
                # Take Profit / Stop Loss
                tp = price * (1 + TAKE_PROFIT_PCT)
                sl = price * (1 - STOP_LOSS_PCT)
                # boucle d'attente simple
                while True:
                    p = float(get_price_func())
                    if p >= tp or p <= sl:
                        r2 = place_sell(p, qty)
                        if r2["status"] == "TEST_OK":
                            realized = update_position_on_sell(p, qty)
                            append_trade("SELL", p, qty, realized_pnl=realized,
                                         note=("TP" if p>=tp else "SL"))
                        break
                    time.sleep(5)  # 5s entre checks

                make_reports()

        # régénère les rapports une fois par heure au cas où
        if int(time.time()) % 3600 < 5:
            make_reports()

        time.sleep(10)  # souffle entre cycles
