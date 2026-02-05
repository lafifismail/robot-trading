import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

class MarketDataHandler:
    def __init__(self, login=None, password=None, server=None):
        """
        Initialise la connexion à MetaTrader 5.
        
        Args:
            login (int, optional): Login du compte de trading.
            password (str, optional): Mot de passe du compte.
            server (str, optional): Serveur du courtier.
        
        Raises:
            Exception: Si l'initialisation MT5 échoue.
        """
        if login is None:
            authorized = mt5.initialize()
        else:
            authorized = mt5.initialize(login=login, password=password, server=server)
            
        if not authorized:
            raise Exception(f"MT5 initialization failed: {mt5.last_error()}")

    def get_multi_timeframe_data(self, symbol):
        """
        Récupère les données OHLCV pour les timeframes H4, H1 et M5.
        
        Args:
            symbol (str): Le symbole financier (ex: "EURUSD").
            
        Returns:
            dict: Dictionnaire de DataFrames {'H4': df, 'H1': df, 'M5': df}.
        """
        timeframes = {
            'H4': mt5.TIMEFRAME_H4,
            'H1': mt5.TIMEFRAME_H1,
            'M5': mt5.TIMEFRAME_M5
        }
        
        final_data = {}
        
        try:
            # Assurer que le symbole est visible
            if not mt5.symbol_select(symbol, True):
                print(f"Symbole {symbol} non trouvé dans le Market Watch.")
                return {}

            for tf_name, tf_constant in timeframes.items():
                rates = mt5.copy_rates_from_pos(symbol, tf_constant, 0, 1000)
                
                if rates is None or len(rates) == 0:
                    print(f"Erreur de récupération des données pour {symbol} {tf_name}")
                    continue
                
                # Conversion brute en DataFrame
                df = pd.DataFrame(rates)
                
                # Conversion de la colonne 'time' (unix timestamp) en datetime
                df['time'] = pd.to_datetime(df['time'], unit='s')
                
                # Définir l'index
                df.set_index('time', inplace=True)
                
                final_data[tf_name] = df
                
        except Exception as e:
            print(f"Une erreur est survenue lors de la récupération des données : {e}")
            
        return final_data

if __name__ == "__main__":
    try:
        # Initialisation sans arguments (utilise le terminal ouvert)
        handler = MarketDataHandler()
        
        symbol_test = "EURUSD"
        print(f"Récupération des données pour {symbol_test}...")
        
        data = handler.get_multi_timeframe_data(symbol_test)
        
        if 'H4' in data and not data['H4'].empty:
            print("\n--- 5 dernières lignes du H4 ---")
            print(data['H4'].tail(5))
        else:
            print("Données H4 non disponibles ou erreur de récupération.")
            
    except Exception as e:
        print(f"Erreur critique : {e}")
