import os
import time
from datetime import datetime, timedelta
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException

# Clés API Binance (mettre dans les variables Railway)
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Initialiser le client Binance
client = Client(API_KEY, API_SECRET)

# Paramètres de trading
SYMBOL = "BTCUSDT"
USDC_TARGET_PER_DAY = 5
ORDER_QUANTITY = 0.00025  # Ajuste selon ton capital

# Fichier pour les rapports
DAILY_REPORT_FILE = "daily_report.xlsx"

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def execute_trade():
    try:
        # Prix actuel
        ticker = client.get_symbol_ticker(symbol=SYMBOL)
        price = float(ticker["price"])
        log(f"Prix actuel {SYMBOL} : {price} USDT")

        # Achat
        log("Passage d'un ordre d'achat...")
        client.order_market_buy(symbol=SYMBOL, quantity=ORDER_QUANTITY)

        time.sleep(3)  # Petite pause pour éviter les erreurs

        # Vente
        log("Passage d'un ordre de vente...")
        client.order_market_sell(symbol=SYMBOL, quantity=ORDER_QUANTITY)

        profit = ORDER_QUANTITY * price * 0.002  # Estimation simplifiée
        save_daily_report(profit)

    except BinanceAPIException as e:
        log(f"Erreur Binance : {e}")
    except Exception as e:
        log(f"Erreur inattendue : {e}")

def save_daily_report(profit):
    today = datetime.now().strftime('%Y-%m-%d')
    if os.path.exists(DAILY_REPORT_FILE):
        df = pd.read_excel(DAILY_REPORT_FILE)
    else:
        df = pd.DataFrame(columns=["Date", "Profit"])

    df = pd.concat([df, pd.DataFrame([[today, profit]], columns=["Date", "Profit"])], ignore_index=True)
    df.to_excel(DAILY_REPORT_FILE, index=False)
    log(f"Profit du jour enregistré : {profit:.2f} USDT")

def generate_weekly_summary():
    if os.path.exists(DAILY_REPORT_FILE):
        df = pd.read_excel(DAILY_REPORT_FILE)
        last_week = datetime.now() - timedelta(days=7)
        df_last_week = df[pd.to_datetime(df["Date"]) >= last_week]
        total = df_last_week["Profit"].sum()
        log(f"Bilan des 7 derniers jours : {total:.2f} USDT")

if __name__ == "__main__":
    log("Bot démarré 🚀")
    while True:
        execute_trade()
        generate_weekly_summary()
        time.sleep(3600)  # 1 trade par heure
