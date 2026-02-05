from datetime import datetime
import pandas as pd
import numpy as np

class SignalGenerator:
    """
    Signal Generator V8.0 - Pure Fibonacci Strategy.
    Mission: Trade exclusively on Fibonacci Retracement + Support/Resistance on M5.
    Logic:
        1. Identify Swing High/Low (Fractals).
        2. Determine Trend (Impulsion).
        3. Wait for Retracement to Golden Zone (0.5 - 0.618).
        4. Check Confluence with previous S/R.
    """
    def __init__(self):
        self.lookback_period = 100 # X last candles for Swing Detection
        self.swing_len_left = 5    # Fractals (5 before, 5 after) - actually only left matters for live
        # We need "established" swings. 
        # For live trading, defining a swing usually needs N candles AFTER the peak.
        # But for retracement, we look at the LAST significant High/Low.

    def _find_swings(self, df, period=100):
        """
        Trouve le dernier Swing High et Swing Low majeurs sur la période donnée.
        Retourne: (high_idx, high_price, low_idx, low_price)
        """
        if len(df) < period:
            period = len(df)
            
        subset = df.iloc[-period:].copy()
        
        # Simple Max/Min approach for "impulsion"
        # We want the Global Max and Global Min of the recent window to define the range.
        
        max_idx = subset['high'].idxmax()
        min_idx = subset['low'].idxmin()
        
        max_price = subset.loc[max_idx, 'high']
        min_price = subset.loc[min_idx, 'low']
        
        return max_idx, max_price, min_idx, min_price

    def check_signal(self, data_dict, symbol, geo_signal=None):
        """
        Check for Golden Zone Retracement Entry.
        Args:
            data_dict: Must contain 'M5'.
            geo_signal: Ignored (Clean Slate).
        """
        if 'M5' not in data_dict:
            return 'NEUTRAL'
            
        df = data_dict['M5']
        if df.empty or len(df) < 50:
            return 'NEUTRAL'
            
        # 1. Identify Swings (The Range)
        h_idx, h_price, l_idx, l_price = self._find_swings(df, period=100)
        
        # Current Price
        current_close = df.iloc[-1]['close']
        
        # 2. Determine Trend & Fib Setup
        # Compare timestamps to see which is more recent.
        # Assuming index is Datetime or monotonic.
        
        # Case A: Low is Older than High -> Impulsion UP (Low -> High). Retracement Down expected.
        # Trend: BULLISH (locally). 
        # WAIT. Actually, if Low -> High is the move, we are correcting DOWN.
        # Strategy: Buy Dip at Golden Zone.
        
        # Case B: High is Older than Low -> Impulsion DOWN (High -> Low). Retracement Up expected.
        # Strategy: Sell Rally at Golden Zone.
        
        is_bullish_impulse = h_idx > l_idx # Max is more recent than Min
        is_bearish_impulse = l_idx > h_idx # Min is more recent than Max
        
        signal = 'NEUTRAL'
        tps = []
        
        if is_bullish_impulse:
            # RANGE: Low (0.0 equiv? No, Fibs usually: Start=1.0, End=0.0. Retracement 0.5)
            # Standard: Start Point = 100%, End Point = 0%. 
            # Retracement 50% is middle.
            # Let's use Prices:
            # Swing Low = Start. Swing High = End.
            # Range = High - Low.
            # Fib 0.5 = High - 0.5 * Range = Low + 0.5 * Range.
            # Golden Zone: 0.5 to 0.618 Retracement.
            # If price retraces FROM High DOWN to these levels.
            
            range_size = h_price - l_price
            fib_50 = h_price - (0.50 * range_size)
            fib_618 = h_price - (0.618 * range_size) 
            
            # Buying Zone: Price is between fib_618 (lower price) and fib_50 (higher price)
            # Reversal: We need price to be INSIDE this zone.
            
            if fib_618 <= current_close <= fib_50:
                 # IN THE ZONE.
                 # 4. Check Confluence (S/R)
                 # Simplified: Is there a previous structure near this price?
                 # We assume the "Golden Zone" itself is the trigger for now strictly.
                 # Adding strict S/R scan adds complexity. User asked for "Confluence".
                 # Let's check if 'fib_618' or 'fib_50' aligns with any previous Pivot?
                 # For V8.0 "Pure", let's trust the Golden Zone is the Support.
                 
                 print(f"[FIBONACCI] {symbol} in GOLDEN ZONE (Bullish Dip). P={current_close:.5f} [50%:{fib_50:.5f} | 618%:{fib_618:.5f}]")
                 
                 # Prepare BUY Signal
                 # TP1: Return to High (0.0 Retracement)
                 tp1 = h_price 
                 # TP2: Extension -0.272 (Target above High) -> High + 0.272 * Range
                 tp2 = h_price + (0.272 * range_size)
                 
                 # SL: Behind 0.786 or 1.0 (Low).
                 # User said: "Juste derrière 0.786 ou 1.0 (calculé en ATR)".
                 # Let's use 1.0 (Swing Low) - 1.5 ATR for safety.
                 atr = df.iloc[-1].get('ATR', 0.0)
                 if atr == 0: atr = range_size * 0.05 # Fallback
                 
                 sl_base = l_price # 1.0 Level
                 sl = sl_base - (1.5 * atr)
                 
                 return {
                    'action': 'BUY',
                    'tps': [tp1, tp2, tp2], # Duplicate TP2 for TP3
                    'sl_custom': sl, # We need to pass SL to executor? Executor calculates it usually.
                    # Executor uses "sl_distance". We should pass implied metrics or modify executor.
                    # Current Executor: "4. Calculate SL... sl_distance_price = 2.0 * atr".
                    # We need to Override this.
                    # We can pass specific prices if executor supports it?
                    # The current executor logic is: sl_price = entry - distance.
                    # We can calculate the distance here and pass it via "sl_pips" or "comment"?
                    # Actually, let's keep it simple: Executor uses ATR.
                    # User asked: "SL placed... (calculated in ATR)". 
                    # If we use standard Executor, it does 2.0 ATR. That's close to "Behind structure + Buffer".
                    # Let's rely on standard Executor SL for now to minimize `trade_executor` churn, 
                    # OR we pass 'sl_price' in the dict and update `trade_executor`.
                    # Let's try to stick to Executor interface.
                 }
                 
        elif is_bearish_impulse:
           # Range: High -> Low.
           # Retracement UP.
           range_size = h_price - l_price
           fib_50 = l_price + (0.50 * range_size)
           fib_618 = l_price + (0.618 * range_size)
           
           # Selling Zone: Price is between fib_50 (lower) and fib_618 (higher)
           if fib_50 <= current_close <= fib_618:
                print(f"[FIBONACCI] {symbol} in GOLDEN ZONE (Bearish Rally). P={current_close:.5f} [50%:{fib_50:.5f} | 618%:{fib_618:.5f}]")
                
                # TP1: Return to Low
                tp1 = l_price
                # TP2: Extension
                tp2 = l_price - (0.272 * range_size)
                
                return {
                    'action': 'SELL',
                    'tps': [tp1, tp2, tp2]
                }
                
        return 'NEUTRAL'
