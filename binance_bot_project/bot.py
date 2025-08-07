
import time
from binance.client import Client
import pandas as pd

# Remplacer ces clés par vos variables d'environnement en production
API_KEY = "votre_api_key"
API_SECRET = "votre_api_secret"

client = Client(API_KEY, API_SECRET)

def run_bot():
    print("Bot lancé...")
    while True:
        prices = client.get_all_tickers()
        df = pd.DataFrame(prices)
        print(df.head())
        time.sleep(60)

if __name__ == "__main__":
    run_bot()
