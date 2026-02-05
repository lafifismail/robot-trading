import pandas as pd
import ta

class IndicatorEngine:
    """
    Moteur d'indicateurs simplifié (Operation Clean Slate).
    Seul l'ATR est conservé pour le calcul du risque (SL/TP).
    """
    def __init__(self):
        pass
        
    def add_indicators(self, data_dict):
        """
        Ajoute l'ATR aux données M5.
        """
        if 'M5' not in data_dict:
            return data_dict
            
        df = data_dict['M5']
        if df.empty:
            return data_dict
            
        # ATR Calculation (Period 14)
        try:
            # Check if ta library is available, otherwise manual calculation
            indicator_atr = ta.volatility.AverageTrueRange(
                high=df['high'], low=df['low'], close=df['close'], window=14
            )
            df['ATR'] = indicator_atr.average_true_range()
        except Exception as e:
            print(f"Erreur Calcul ATR: {e}")
            
        data_dict['M5'] = df
        return data_dict
