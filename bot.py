# bot.py
import os
import time
from decimal import Decimal, ROUND_DOWN
from binance.client import Client
from binance.exceptions import BinanceAPIException

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TLD = os.getenv("BINANCE_TLD", "com")     # 'com' ou 'us'
LIVE = os.getenv("LIVE", "0")             # '0' = test order, '1' = trading réel
BUDGET_USDC = Decimal(os.getenv("BUDGET_USDC", "10"))  # ex : 10 USDC

# Paire cible
PRIMARY_SYMBOL = "BTCUSDC"   # on tente ça en premier
FALLBACK_SYMBOL = "BTCUSD"   # solution de repli pour Binance US si BTCUSDC n'existe pas

client = Client(API_KEY, API_SECRET, tld=TLD)

def d(x):
    return Decimal(str(x))

def get_symbol_filters(symbol):
    info = client.get_symbol_info(symbol)
    if not info:
        return None
    filters = {f["filterType"]: f for f in info["filters"]}
    lot = filters.get("LOT_SIZE", {})
    min_qty = d(lot.get("minQty", "0"))
    step_size = d(lot.get("stepSize", "1"))
    min_notional = d(filters.get("MIN_NOTIONAL", {}).get("minNotional", "0"))
    is_spot_ok = info.get("isSpotTradingAllowed", False)
    status = info.get("status")
    return {
        "min_qty": min_qty,
        "step_size": step_size,
        "min_notional": min_notional,
        "is_spot_ok": is_spot_ok,
        "status": status,
    }

def quantize(qty, step):
    # arrondi à la baisse sur le stepSize
    if step == 0:
        return qty
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step

def choose_symbol():
    """On essaie BTCUSDC d'abord, sinon fallback (BTCUSD)."""
    for sym in [PRIMARY_SYMBOL, FALLBACK_SYMBOL]:
        info = client.get_symbol_info(sym)
        if info and info.get("isSpotTradingAllowed"):
            return sym
    return None

def can_trade_symbol(symbol):
    f = get_symbol_filters(symbol)
    if not f:
        return False, "Symbole introuvable"
    if not f["is_spot_ok"] or f["status"] != "TRADING":
        return False, f"Spot non autorisé ou status={f['status']}"
    return True, f

def buy_market(symbol, usdc_budget):
    # prix moyen via ticker
    price = d(client.get_symbol_ticker(symbol=symbol)["price"])
    ok, resp = can_trade_symbol(symbol)
    if not ok:
        raise RuntimeError(f"Symbole non tradable: {resp}")

    f = resp
    qty = usdc_budget / price
    qty = quantize(qty, f["step_size"])

    # Vérifier minNotional & minQty
    if qty < f["min_qty"]:
        raise RuntimeError(f"Qty trop petite ({qty}) minQty={f['min_qty']}")

    notional = qty * price
    if notional < f["min_notional"]:
        raise RuntimeError(f"Notional trop petit ({notional}) minNotional={f['min_notional']}")

    # Test order ou live
    if LIVE == "1":
        order = client.create_order(
            symbol=symbol, side="BUY", type="MARKET",
            quantity=str(qty)  # quantité en BTC
        )
        return order, price, qty
    else:
        client.create_test_order(
            symbol=symbol, side="BUY", type="MARKET",
            quantity=str(qty)
        )
        return {"status": "TEST_OK"}, price, qty

if __name__ == "__main__":
    try:
        # choisir un symbole tradable
        symbol = choose_symbol()
        if not symbol:
            print("❌ Aucun symbole de repli tradable (BTCUSDC/BTCUSD) pour ce compte / ce TLD.")
            raise SystemExit(1)

        print(f"→ TLD = {TLD} | Symbole choisi = {symbol} | LIVE={LIVE}")
        acc = client.get_account()
        print("Permissions compte:", acc.get("permissions", []))

        while True:
            try:
                order, price, qty = buy_market(symbol, BUDGET_USDC)
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                      f"BUY {symbol} qty={qty} ~price={price} USDC ; order={order}")

            except BinanceAPIException as e:
                print("BinanceAPIException:", e)
            except Exception as e:
                print("Erreur locale:", e)

            # boucle de test lente pour ne pas spammer
            time.sleep(30)

    except KeyboardInterrupt:
        print("Stop.")

        generate_weekly_summary()
        time.sleep(3600)  # 1 trade par heure
