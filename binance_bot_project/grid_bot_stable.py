import time
import csv
import datetime
import pandas as pd
from binance.client import Client

# CONFIGURATION
API_KEY = "TA_CLEF_API"
API_SECRET = "TON_SECRET"
PAIR = "BTCUSDC"
TRADE_BUDGET = 50
PROFIT_TARGET = 0.005
BUY_DISCOUNT = 0.995

client = Client(API_KEY, API_SECRET)

def get_symbol_rules(symbol):
    info = client.get_symbol_info(symbol)
    rules = {'step_size': None, 'min_qty': None, 'min_notional': None}
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            rules['step_size'] = float(f['stepSize'])
        if f['filterType'] == 'MIN_NOTIONAL':
            rules['min_notional'] = float(f['minNotional'])
    return rules

def log_trade_to_excel(data):
    df = pd.DataFrame([data])
    filename = 'weekly_report.xlsx'
    try:
        old = pd.read_excel(filename)
        df = pd.concat([old, df], ignore_index=True)
    except FileNotFoundError:
        pass
    df.to_excel(filename, index=False)

# Simulation (à remplacer par ta logique réelle)
if __name__ == "__main__":
    while True:
        now = datetime.datetime.now()
        trade_data = {
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'pair': PAIR,
            'action': 'buy',
            'price': 30000,
            'quantity': 0.001
        }
        log_trade_to_excel(trade_data)
        time.sleep(60)