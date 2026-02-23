from datetime import datetime, timezone
import pandas as pd
import numpy as np

class SignalGenerator:
    """
    Signal Generator V9.0 - Institutional SMC Fibonacci Strategy.

    3 institutional filters stacked on top of the Pure Fibonacci strategy:

    FILTER 1 — Kill Zone (Time Filter)
        Only trade during London & New York sessions (07:00–22:00 UTC).
        Outside these hours, banks reduce volume and "fakeouts" are common.

    FILTER 2 — H1 Multi-Timeframe Alignment
        The 50-period SMA on H1 defines the macro bias.
        Price above SMA50_H1 → only BUY signals pass.
        Price below SMA50_H1 → only SELL signals pass.

    FILTER 3 — Fractal-Based Swing Detection (Order Blocks)
        Instead of a simple Max/Min on the last 100 candles, we detect
        REAL fractal Swing Highs and Swing Lows (sharp pivots) that
        correspond to zones where institutions have genuinely injected capital.
        A fractal point requires N candles on each side to be lower/higher.
    """

    # --- Kill Zone Configuration ---
    KILL_ZONE_START_UTC = 7   # 07:00 UTC (London Open)
    KILL_ZONE_END_UTC   = 22  # 22:00 UTC (New York Close)

    # --- Fractal Detection Configuration ---
    FRACTAL_STRENGTH = 5      # Number of candles on each side required to validate a fractal
    LOOKBACK_PERIOD  = 200    # How many M5 candles to scan for fractals

    # --- H1 Trend Filter ---
    H1_SMA_PERIOD = 50

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # FILTER 1: Kill Zone
    # ------------------------------------------------------------------
    def _is_in_kill_zone(self):
        """
        Returns True only during London + New York Kill Zone (07:00–16:00 UTC).
        This avoids the low-volume Asian session where Stop Hunts are frequent.
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        return self.KILL_ZONE_START_UTC <= hour < self.KILL_ZONE_END_UTC

    # ------------------------------------------------------------------
    # FILTER 2: H1 Multi-Timeframe Bias
    # ------------------------------------------------------------------
    def _get_h1_bias(self, data_dict):
        """
        Calculates the macro trend bias from the H1 timeframe using SMA50.

        Returns:
            'BULLISH'  → Price > SMA50_H1 (only BUY signals allowed)
            'BEARISH'  → Price < SMA50_H1 (only SELL signals allowed)
            'NEUTRAL'  → Not enough data
        """
        if 'H1' not in data_dict:
            print("[HTF FILTER] Données H1 manquantes. Biais: NEUTRAL.")
            return 'NEUTRAL'

        df_h1 = data_dict['H1']
        if df_h1.empty or len(df_h1) < self.H1_SMA_PERIOD:
            print(f"[HTF FILTER] Pas assez de bougie H1 (besoin={self.H1_SMA_PERIOD}). Biais: NEUTRAL.")
            return 'NEUTRAL'

        sma50 = df_h1['close'].rolling(window=self.H1_SMA_PERIOD).mean().iloc[-1]
        current_price = df_h1['close'].iloc[-1]

        if current_price > sma50:
            bias = 'BULLISH'
        else:
            bias = 'BEARISH'

        print(f"[HTF FILTER] H1 Close={current_price:.5f} | SMA50={sma50:.5f} → Biais HTF: {bias}")
        return bias

    # ------------------------------------------------------------------
    # FILTER 3: Fractal-Based Swing Detection (Order Blocks)
    # ------------------------------------------------------------------
    def _find_fractal_swings(self, df):
        """
        Detects REAL fractal Swing Highs and Swing Lows in the M5 data.

        A Fractal High at index i means:
            df['high'][i] is strictly greater than the N candles before AND after it.

        A Fractal Low at index i means:
            df['low'][i] is strictly less than the N candles before AND after it.

        We scan the last LOOKBACK_PERIOD candles (excluding the last FRACTAL_STRENGTH
        candles, which don't have enough right-side confirmation yet).

        Returns:
            (swing_high_price, swing_high_idx, swing_low_price, swing_low_idx)
            or (None, None, None, None) if not enough fractals are found.
        """
        N = self.FRACTAL_STRENGTH
        period = self.LOOKBACK_PERIOD

        if len(df) < period:
            period = len(df)

        subset = df.iloc[-period:].copy()
        subset = subset.reset_index(drop=True)  # Work with integer index for fractal math

        fractal_highs = []  # list of (int_idx, price)
        fractal_lows  = []

        # We can only confirm a fractal up to len-N-1 (need N candles to the right)
        scan_end = len(subset) - N

        for i in range(N, scan_end):
            # --- Fractal High ---
            current_high = subset['high'].iloc[i]
            left_highs   = subset['high'].iloc[i - N : i]
            right_highs  = subset['high'].iloc[i + 1 : i + N + 1]

            if (current_high > left_highs).all() and (current_high > right_highs).all():
                fractal_highs.append((i, current_high))

            # --- Fractal Low ---
            current_low = subset['low'].iloc[i]
            left_lows   = subset['low'].iloc[i - N : i]
            right_lows  = subset['low'].iloc[i + 1 : i + N + 1]

            if (current_low < left_lows).all() and (current_low < right_lows).all():
                fractal_lows.append((i, current_low))

        if not fractal_highs or not fractal_lows:
            print(f"[ORDER BLOCK] Pas assez de fractals détectés (H:{len(fractal_highs)}, L:{len(fractal_lows)}). Signal ignoré.")
            return None, None, None, None

        # Use the MOST RECENT fractal high and low
        last_frac_high_idx, last_frac_high_price = fractal_highs[-1]
        last_frac_low_idx,  last_frac_low_price  = fractal_lows[-1]

        print(f"[ORDER BLOCK] Fractal High @ candle {last_frac_high_idx} → {last_frac_high_price:.5f}")
        print(f"[ORDER BLOCK] Fractal Low  @ candle {last_frac_low_idx}  → {last_frac_low_price:.5f}")

        return last_frac_high_price, last_frac_high_idx, last_frac_low_price, last_frac_low_idx

    # ------------------------------------------------------------------
    # CORE SIGNAL CHECK
    # ------------------------------------------------------------------
    def check_signal(self, data_dict, symbol, geo_signal=None):
        """
        Generates a trade signal applying all 3 institutional filters.

        Filters applied IN ORDER (fail-fast):
            1. Kill Zone   → Time window check (07:00–16:00 UTC)
            2. H1 HTF Bias → SMA50 direction filter
            3. Order Block → Fractal-validated swing detection

        Entry logic (Fibonacci Golden Zone):
            Bullish impulse (Low before High) + HTF BULLISH → BUY on retracement to 50–61.8%
            Bearish impulse (High before Low) + HTF BEARISH → SELL on rally to 50–61.8%

        Returns:
            dict with 'action', 'tps', 'sl_custom'
            or 'NEUTRAL' if any filter rejects.
        """

        # ── FILTER 1: Kill Zone ──────────────────────────────────────
        if not self._is_in_kill_zone():
            return 'NEUTRAL'

        # ── FILTER 2: H1 Bias ────────────────────────────────────────
        h1_bias = self._get_h1_bias(data_dict)
        if h1_bias == 'NEUTRAL':
            return 'NEUTRAL'

        # ── M5 Data Check ────────────────────────────────────────────
        if 'M5' not in data_dict:
            return 'NEUTRAL'

        df = data_dict['M5']
        if df.empty or len(df) < 50:
            return 'NEUTRAL'

        # ── FILTER 3: Fractal Swings (Order Blocks) ──────────────────
        h_price, h_idx, l_price, l_idx = self._find_fractal_swings(df)
        if h_price is None or l_price is None:
            return 'NEUTRAL'

        # Validate that swing range is meaningful (not degenerate)
        range_size = h_price - l_price
        if range_size <= 0:
            print(f"[FIBONACCI] Range invalide ({range_size}). Signal ignoré.")
            return 'NEUTRAL'

        # ── Impulse Direction ─────────────────────────────────────────
        # h_idx and l_idx are integer positions within the subset
        is_bullish_impulse = h_idx > l_idx   # Low came first → price went UP
        is_bearish_impulse = l_idx > h_idx   # High came first → price went DOWN

        current_close = df.iloc[-1]['close']
        atr = df.iloc[-1].get('ATR', 0.0)
        if atr == 0:
            atr = range_size * 0.05  # Fallback: 5% of swing range

        # ── BULLISH SETUP ─────────────────────────────────────────────
        # Conditions: bullish fractal impulse + H1 confirms BULLISH
        if is_bullish_impulse and h1_bias == 'BULLISH':
            # Fibonacci retracement from HIGH back to LOW direction
            fib_50  = h_price - (0.50  * range_size)
            fib_618 = h_price - (0.618 * range_size)

            if fib_618 <= current_close <= fib_50:
                print(f"[FIBONACCI] {symbol} → BUY ZONE (Bullish Dip + HTF OK).")
                print(f"  Prix={current_close:.5f} | 50%={fib_50:.5f} | 61.8%={fib_618:.5f}")

                tp1 = h_price                          # Return to swing High (0.0 retrace)
                tp2 = h_price + (0.272 * range_size)  # Extension above swing High

                sl  = l_price - (1.5 * atr)           # Below swing Low + ATR buffer

                return {
                    'action'    : 'BUY',
                    'tps'       : [tp1, tp2],
                    'sl_custom' : sl,
                }

        # ── BEARISH SETUP ─────────────────────────────────────────────
        # Conditions: bearish fractal impulse + H1 confirms BEARISH
        elif is_bearish_impulse and h1_bias == 'BEARISH':
            # Fibonacci retracement from LOW back up toward HIGH
            fib_50  = l_price + (0.50  * range_size)
            fib_618 = l_price + (0.618 * range_size)

            if fib_50 <= current_close <= fib_618:
                print(f"[FIBONACCI] {symbol} → SELL ZONE (Bearish Rally + HTF OK).")
                print(f"  Prix={current_close:.5f} | 50%={fib_50:.5f} | 61.8%={fib_618:.5f}")

                tp1 = l_price                          # Return to swing Low (0.0 retrace)
                tp2 = l_price - (0.272 * range_size)  # Extension below swing Low

                sl  = h_price + (1.5 * atr)            # Above swing High + ATR buffer

                return {
                    'action'    : 'SELL',
                    'tps'       : [tp1, tp2],
                    'sl_custom' : sl,
                }

        else:
            # Impulse direction conflicts with H1 bias → institutional filter rejects
            if is_bullish_impulse and h1_bias == 'BEARISH':
                print(f"[HTF FILTER] {symbol} → Impulse HAUSSIER mais H1 BAISSIER. BUY ignoré.")
            elif is_bearish_impulse and h1_bias == 'BULLISH':
                print(f"[HTF FILTER] {symbol} → Impulse BAISSIER mais H1 HAUSSIER. SELL ignoré.")

        return 'NEUTRAL'
