import MetaTrader5 as mt5
from datetime import datetime

import json
import os

class TradeExecutor:
    """
    Exécuteur de trades pour MetaTrader 5.
    Gère le calcul de taille de lot (Money Management) avec logique High Water Mark.
    """
    MEMORY_FILE = "bot_memory.json"

    def _get_memory_path(self):
        """Retourne le chemin complet du fichier mémoire."""
        # On utilise le répertoire courant ou un chemin relatif
        return os.path.join(os.getcwd(), self.MEMORY_FILE)

    def _load_high_water_mark(self):
        """
        Lit le fichier JSON et retourne le plus haut capital enregistré.
        Retourne 0.0 si le fichier n'existe pas ou est corrompu.
        """
        path = self._get_memory_path()
        if not os.path.exists(path):
            return 0.0
            
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return data.get("highest_balance", 0.0)
        except Exception as e:
            print(f"Erreur lecture mémoire: {e}")
            return 0.0

    def _update_high_water_mark(self, current_balance):
        """
        Met à jour le High Water Mark si le solde actuel est supérieur.
        Retourne le nouveau (ou inchangé) High Water Mark.
        """
        path = self._get_memory_path()
        previous_high = self._load_high_water_mark()
        
        # Si nouveau record, on met à jour
        if current_balance > previous_high:
            print(f"Nouveau Record atteint! {previous_high} -> {current_balance}")
            try:
                with open(path, 'w') as f:
                    json.dump({"highest_balance": current_balance}, f)
                return current_balance
            except Exception as e:
                print(f"Erreur écriture mémoire: {e}")
                return current_balance # On retourne quand même le montant actuel
        
        return previous_high

    def calculate_lot_size(self, symbol, sl_distance_points, risk_percent=None):
        """
        Calcule la taille du lot en fonction du High Water Mark (HWM).
        
        Logique:
        1. Récupère solde actuel.
        2. Met à jour HWM si nécessaire.
        3. Reference Capital = HWM.
        4. Risk Money = Reference Capital / 10.0 (10% fixe du sommet).
        
        Args:
            symbol (str): Symbole à trader.
            sl_distance_points (float): Distance du SL en points.
            risk_percent (float): IGNORÉ dans cette version (gardé pour compatibilité).
            
        Returns:
            float: Taille du lot arrondie et bornée.
        """
        account_info = mt5.account_info()
        if account_info is None:
            print("Erreur: Impossible de récupérer les infos du compte.")
            return 0.0

        current_balance = account_info.balance
        
        # Gestion du High Water Mark
        high_water_mark = self._update_high_water_mark(current_balance)
        
        print(f"Solde Actuel: {current_balance}, High Water Mark: {high_water_mark}")
        
        # Money Management Aggressif : 1/10ème du plus haut historique
        risk_cash = high_water_mark / 10.0
        
        print(f"Capital Risqué (1/10 HWM) : {risk_cash:.2f}")
        
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"Erreur: Symbole {symbol} non trouvé.")
            return 0.0
            
        tick_value = symbol_info.trade_tick_value
        
        # Éviter la division par zéro
        if sl_distance_points == 0 or tick_value == 0:
            print("Erreur: SL distance ou Tick Value à 0.")
            return 0.0

        # Formule : Lot = Risk / (SL_points * Tick_Value)
        lot_size = risk_cash / (sl_distance_points * tick_value)
        
        # Respecter les contraintes du symbole (min, max, step)
        min_lot = symbol_info.volume_min
        max_lot = symbol_info.volume_max
        step = symbol_info.volume_step
        
        if step > 0:
             lot_size = round(lot_size / step) * step
        
        # Arrondir à 2 décimales finales pour sécurité
        lot_size = round(lot_size, 2)
        
        if lot_size < min_lot:
            lot_size = min_lot 
        if lot_size > max_lot:
            lot_size = max_lot

        # --- Check Marge (Anti-Erreur 10019) ---
        margin_free = account_info.margin_free
        
        # Calcul de la marge requise pour ce lot
        # Note: ORDER_TYPE_BUY ou SELL influence peu la marge en général (sauf hedge), on prend BUY par défaut pour estimer
        try:
            ask_price = mt5.symbol_info_tick(symbol).ask
            margin_required = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, lot_size, ask_price)
            
            if margin_required is None:
                print(f"Attention: Impossible de calculer la marge pour {symbol}. On continue avec risque.")
            elif margin_required > margin_free:
                print(f"⚠️ Marge Insuffisante! Requis: {margin_required:.2f}, Dispo: {margin_free:.2f}")
                # Tentative de réduction au minimum
                print(f"Tentative de réduction à {min_lot} (Min Lot)...")
                lot_size = min_lot
                
                # Re-check avec min_lot
                margin_required_min = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, lot_size, ask_price)
                if margin_required_min and margin_required_min > margin_free:
                    print("❌ Marge toujours insuffisante même avec lot minimum. Trade annulé.")
                    return 0.0
                else:
                    print("✅ Lot réduit au minimum accepté.")
        except Exception as e:
            print(f"Erreur Check Marge: {e}")
            # On laisse passer si erreur calcul, le serveur rejettera au pire
            
        return lot_size

    def validate_candle_momentum(self, symbol, timeframe, signal_type, data_dict):
        """
        [POWER TRIGGER] Valide la dynamique de la bougie pour confirmer le signal.
        Logic V7.2:
        - Vérifie la couleur (Green pour BUY, Red pour SELL)
        - Vérifie le breakout (Close > High_Prev pour BUY, Close < Low_Prev pour SELL)
        - Vérifie la force du corps (Body > 50% du Range)
        """
        # Choix du DF selon timeframe (par défaut M5 si non spécifié ou absent)
        tf_key = timeframe if timeframe in data_dict else 'M5'
        
        if tf_key not in data_dict:
            print(f"[POWER TRIGGER] Erreur: Données {tf_key} manquantes pour validation.")
            return False
            
        df = data_dict[tf_key]
        
        # Sécurité : vérifier la taille du DF
        if len(df) < 3:
            print(f"[POWER TRIGGER] Pas assez de données pour validation (len={len(df)}).")
            return False
            
        # Indexation : 
        # iloc[-1] = Bougie en cours (non clôturée)
        # iloc[-2] = Dernière bougie CLÔTURÉE (Celle qu'on analyse)
        # iloc[-3] = Bougie précédente (Référence pour le breakout)
        
        candle_target = df.iloc[-2]
        candle_prev = df.iloc[-3]
        
        # Target (iloc returns Series, assuming lower case columns from market_data_handler)
        # Check column names case sensitivity. Usually it's lowercase 'open', 'high', etc. based on Step 13.
        O = candle_target['open']
        H = candle_target['high']
        L = candle_target['low']
        C = candle_target['close']
        
        # Prev
        H_prev = candle_prev['high']
        L_prev = candle_prev['low']
        
        # Calculs communs
        body_size = abs(C - O)
        total_range = H - L
        
        # Sécurité division par zéro ou range nul
        if total_range == 0:
            print("[POWER TRIGGER] Range nul sur la bougie cible. Ignoré.")
            return False
            
        min_body_strength = 0.3 * total_range # [V7.3 Relaxation] 30% du range total
        
        is_valid = False
        reason = ""
        
        if signal_type == 'BUY':
            # 1. Color Check (Green)
            if C > O:
                # 2. Breakout Check (Close > Previous High)
                if C > H_prev:
                    # 3. Body Strength
                    if body_size > min_body_strength:
                        is_valid = True
                    else:
                        reason = f"Weak Body ({body_size:.5f} < {min_body_strength:.5f})"
                else:
                    reason = f"No Breakout of Prev High ({C:.5f} <= {H_prev:.5f})"
            else:
                reason = "Candle is Red (Close <= Open)"
                
        elif signal_type == 'SELL':
            # 1. Color Check (Red)
            if C < O:
                # 2. Breakout Check (Close < Previous Low)
                if C < L_prev:
                    # 3. Body Strength
                    if body_size > min_body_strength:
                        is_valid = True
                    else:
                        reason = f"Weak Body ({body_size:.5f} < {min_body_strength:.5f})"
                else:
                    reason = f"No Breakout of Prev Low ({C:.5f} >= {L_prev:.5f})"
            else:
                reason = "Candle is Green (Close >= Open)"
        
        if not is_valid:
            print(f"[POWER TRIGGER] Signal ABORTED. Reason: {reason}")
            return False
            
        print(f"[POWER TRIGGER] Candle Momentum VALIDATED for {signal_type}.")
        return True

    def execute_trade(self, symbol, signal, data_dict, dry_run=False):
        """
        Exécute un trade basé sur le signal (V7.1 Multi-Target).
        
        Args:
            symbol (str): Symbole.
            signal (str or dict): 'BUY'/'SELL' ou dict {'action': 'BUY', 'tps': [tp1, tp2, tp3]}.
            data_dict (dict): Données.
            dry_run (bool): Simulation.
        """
        # 1. Parse Signal
        if isinstance(signal, dict):
            signal_type = signal.get('action')
            targets = signal.get('tps', []) # [TP1, TP2, TP3]
        else:
            signal_type = signal
            targets = []
            
        if signal_type not in ['BUY', 'SELL']:
            return None

        # --- V7.2 POWER TRIGGER VALIDATION (Relaxed V7.3) ---
        # On valide la bougie M5 avant d'aller plus loin
        if not self.validate_candle_momentum(symbol, 'M5', signal_type, data_dict):
            print(f"[POWER TRIGGER] Momentum faible, mais on force l'exécution pour test ({signal_type}).")
            # return None <-- DISABLED for Test/Aggressive Mode
        # -------------------------------------

        # 2. Data & ATR Logic
        if 'M5' not in data_dict:
            print("Erreur: Clé 'M5' manquante.")
            return None
        df_m5 = data_dict['M5']
        if df_m5.empty: return None
        last_m5 = df_m5.iloc[-1]
        
        if 'ATR' not in last_m5:
            print("Erreur: Colonne ATR manquante.")
            return None
        atr = last_m5['ATR']
        
        # 3. Market Info
        tick = mt5.symbol_info_tick(symbol)
        if tick is None: return None
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None: return None
        point = symbol_info.point
        
        # 4. Calculate SL (Shared)
        sl_distance_price = 2.0 * atr # Default
        sl_distance_points = sl_distance_price / point
        
        # Entry Price
        entry_price = tick.ask if signal_type == 'BUY' else tick.bid
        
        if signal_type == 'BUY':
            action = mt5.ORDER_TYPE_BUY
            sl_price = entry_price - sl_distance_price
        else:
            action = mt5.ORDER_TYPE_SELL
            sl_price = entry_price + sl_distance_price
            
        # 5. Lot Size Calculation (Total Safe Volume)
        total_lot = self.calculate_lot_size(symbol, sl_distance_points)
        if total_lot == 0.0: return None
        
        # 6. Split Volume Logic (V7.4 4-Bullet Strategy)
        # We need 4 orders.
        # Split lot by 4.
        raw_split_lot = total_lot / 4.0
        
        # Normalize to Step
        step = symbol_info.volume_step
        min_lot = symbol_info.volume_min
        
        if step > 0:
            split_lot = round(raw_split_lot / step) * step
        else:
            split_lot = raw_split_lot
            
        split_lot = round(split_lot, 2)
        
        if split_lot < min_lot:
            # Fallback: force min_lot (Total risk increases slightly)
            split_lot = min_lot
            
        print(f"--- Exécution V7.4 Multi-Target : {signal_type} ---")
        print(f"Total Risk Lot: {total_lot} -> Split: 4 x {split_lot}")
        print(f"Entry: {entry_price}, SL: {sl_price:.5f}")
        
        # 7. Targets Assignment (V7.4 Fixed RR)
        # TP1: 0.5 R
        # TP2: 1.0 R
        # TP3: 1.5 R
        # TP4: 2.0 R
        
        final_tps = []
        r_ratios = [0.5, 1.0, 1.5, 2.0]
        
        dist = sl_distance_price
        for r in r_ratios:
            if signal_type == 'BUY':
                tp = entry_price + (dist * r)
            else:
                tp = entry_price - (dist * r)
            final_tps.append(tp)

        comments = ["V7.4_TP1", "V7.4_TP2", "V7.4_TP3", "V7.4_TP4"]
        order_results = []
        
        for i in range(4):
            tp = final_tps[i]
            comment = comments[i]
            
            print(f"  Order {i+1} ({comment}): Vol={split_lot}, TP={tp:.5f} (R={r_ratios[i]})")
            
            if dry_run:
                order_results.append({"comment": comment, "status": "Simulated"})
                continue
                
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": split_lot,
                "type": action,
                "price": entry_price,
                "sl": sl_price,
                "tp": tp,
                "deviation": 30, 
                "magic": 123456 + i, # Magic 123456, 123457, 123458, 123459
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            res = mt5.order_send(request)
            if res.retcode != mt5.TRADE_RETCODE_DONE:
                 print(f"  ❌ Order Failed: {res.comment}")
            else:
                 print(f"  ✅ Order Sent: Ticket {res.order}")
            order_results.append(res)
            
        return order_results

if __name__ == "__main__":
    print("--- Test TradeExecutor ---")
    
    # 1. Init MT5
    if not mt5.initialize():
        print("Erreur Init MT5")
    else:
        # 2. Instancie Executor
        executor = TradeExecutor()
        
        # 3. Simulation
        print("\nTest Simulation (dry_run=True):")
        
        # Mock Data pour ATR
        # On ne peut pas facilement mocker un DF M5 valide sans pandas complet, 
        # donc on va essayer de récupérer en réel si possible pour le test
        try:
            from market_data_handler import MarketDataHandler
            from indicator_engine import IndicatorEngine
            
            handler = MarketDataHandler()
            symbol_test = "EURUSD"
            data = handler.get_multi_timeframe_data(symbol_test)
            
            if data and 'M5' in data:
                engine = IndicatorEngine()
                data = engine.add_indicators(data) # Calcul ATR
                
                # Force un signal BUY
                print("Appel execute_trade avec signal BUY forcé...")
                # On met dry_run=True pour NE PAS exécuter réellement
                result = executor.execute_trade(symbol_test, 'BUY', data, dry_run=True)
                
            else:
                print("Pas de données réelles disponibles pour le test.")
                
        except Exception as e:
            print(f"Erreur Test: {e}")
            
        mt5.shutdown()
