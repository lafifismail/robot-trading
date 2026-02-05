import time
import os
import winsound # Bibliothèque standard Windows pour le son
import MetaTrader5 as mt5
import json
from datetime import datetime, timedelta, timezone

# Importation des modules
try:
    from market_data_handler import MarketDataHandler
    from indicator_engine import IndicatorEngine
    from signal_generator import SignalGenerator
    from trade_executor import TradeExecutor
except ImportError as e:
    print(f"Erreur d'importation des modules : {e}")
    exit(1)

# --- Configuration Colors ---
class Col:
    GREEN = '\033[92m' # Pour BUY
    RED = '\033[91m'   # Pour SELL
    YELLOW = '\033[93m' # Pour Info
    BLUE = '\033[94m'   # Pour Logique
    RESET = '\033[0m'  # Pour remettre à blanc

# --- Configuration Globale ---
RISK_PERCENT = 1.0
MAGIC_NUMBER = 123456
DRY_RUN = False 
MAX_DAILY_LOSS = -550.0 
COOLDOWN_HOURS = 2 
MAX_OPEN_POSITIONS = 30 
MEMORY_FILE = "bot_memory.json"
cooldowns = {} 

def manage_break_even():
    """
    V7.4 : Sécurisation automatique (Break-Even).
    Logic : Si TP1 est fermé, on met les autres à BE.
    """
    positions = mt5.positions_get()
    if positions is None: return
    
    grouped = {}
    for pos in positions:
        if pos.magic < 123000: continue 
        
        sym = pos.symbol
        if sym not in grouped: grouped[sym] = {'TP1': False, 'Others': []}
        
        comment = pos.comment
        if "TP1" in comment: # Generic matching for robust handling
            grouped[sym]['TP1'] = True
        elif "TP2" in comment or "TP3" in comment:
            grouped[sym]['Others'].append(pos)
            
    # Apply Logic
    for sym, data in grouped.items():
        if not data['TP1'] and data['Others']:
            for pos in data['Others']:
                if pos.type == mt5.ORDER_TYPE_BUY:
                     if pos.sl < pos.price_open: 
                         print(f"[BE MANAGER] Securing BUY {sym} (Ticket {pos.ticket}) -> Move SL to {pos.price_open}")
                         request = {
                             "action": mt5.TRADE_ACTION_SLTP,
                             "position": pos.ticket,
                             "sl": pos.price_open,
                             "tp": pos.tp
                         }
                         mt5.order_send(request)
                elif pos.type == mt5.ORDER_TYPE_SELL:
                     if pos.sl > pos.price_open or pos.sl == 0.0: 
                         print(f"[BE MANAGER] Securing SELL {sym} (Ticket {pos.ticket}) -> Move SL to {pos.price_open}")
                         request = {
                             "action": mt5.TRADE_ACTION_SLTP,
                             "position": pos.ticket,
                             "sl": pos.price_open,
                             "tp": pos.tp
                         }
                         mt5.order_send(request)

def load_memory():
    """Charge la mémoire (dont les cooldowns)"""
    global cooldowns
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f:
                data = json.load(f)
                saved_cds = data.get("cooldowns", {})
                for sym, expiry_str in saved_cds.items():
                    cooldowns[sym] = datetime.fromisoformat(expiry_str)
        except Exception as e:
            print(f"Erreur Load Memory: {e}")

def save_memory_cooldowns():
    """Sauvegarde les cooldowns"""
    try:
        data = {}
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, 'r') as f:
                data = json.load(f)
        
        serializable_cds = {sym: dt.isoformat() for sym, dt in cooldowns.items()}
        data["cooldowns"] = serializable_cds
        
        with open(MEMORY_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Erreur Save Memory: {e}")

def get_daily_pnl():
    """Calcule le PnL réalisé depuis minuit."""
    now = datetime.now()
    today_beginning = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(today_beginning, now)
    total_profit = 0.0
    if deals:
        for deal in deals:
            if deal.magic == MAGIC_NUMBER: 
                total_profit += deal.profit + deal.commission + deal.swap
    return total_profit

def check_recent_losses():
    """Scanne l'historique récent pour détecter les pertes et activer les cooldowns."""
    global cooldowns
    now = datetime.now()
    check_start = now - timedelta(minutes=10)
    deals = mt5.history_deals_get(check_start, now)
    updated = False
    if deals:
        for deal in deals:
            if deal.magic == MAGIC_NUMBER and deal.entry == mt5.DEAL_ENTRY_OUT:
                profit = deal.profit + deal.commission + deal.swap
                symbol = deal.symbol
                if profit < 0:
                    if symbol not in cooldowns:
                         print(f"🚫 PERTE DÉTECTÉE sur {symbol} ({profit:.2f}). Activation COOLDOWN 2H.")
                         expiry = now + timedelta(hours=COOLDOWN_HOURS)
                         cooldowns[symbol] = expiry
                         updated = True
    if updated:
        save_memory_cooldowns()

def play_alert(signal_type):
    try:
        if signal_type == 'BUY':
            for _ in range(3):
                winsound.Beep(1000, 500) 
                time.sleep(0.1)
        elif signal_type == 'SELL':
            for _ in range(3):
                winsound.Beep(500, 500)
                time.sleep(0.1)
    except Exception as e:
        print(f"Erreur Alerte Sonore : {e}")

def count_open_positions(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions is None: return 0
    count = 0
    for pos in positions:
        if pos.magic == MAGIC_NUMBER:
            count += 1
    return count

def run_bot():
    os.system('') 
    print(f"{Col.YELLOW}--- Démarrage du Robot Pure Fibonacci V8.0 ---{Col.RESET}")
    print("Mode: REAL TRADING (Fibonacci Retracement + S/R).")
    
    if not mt5.initialize():
        print(f"Échec de l'initialisation MT5: {mt5.last_error()}")
        return

    handler = MarketDataHandler()
    engine = IndicatorEngine()
    generator = SignalGenerator()
    executor = TradeExecutor()
    
    load_memory()
    print(f"Mémoire chargée. Cooldowns actifs: {list(cooldowns.keys())}")
    
    try:
        while True:
            print(f"\n{Col.YELLOW}--- Analyse : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---{Col.RESET}")
            
            try:
                manage_break_even()
            except Exception as e_be:
                print(f"Erreur BE Manager: {e_be}")
            
            all_symbols_info = mt5.symbols_get()
            symbols_to_trade = []
            # --- FILTRE FOREX ONLY (LISTE NOIRE) ---
            blacklist = [
                "XAU", "GOLD",      # Or
                "XAG", "SILVER",    # Argent
                "OIL", "WTI", "BRENT", "XTI", "XBR", "USOIL", "UKOIL", # Pétrole
                "BTC", "ETH", "LTC", "XRP", "CRYPTO", "BITCOIN", # Cryptos
                "DX", "DXY", "USDX", # Dollar Index
                "US30", "US100", "DE30", "DE40", "FR40", "SPX", "NAS" # Indices
            ]

            symbols_to_trade = []
            if all_symbols_info:
                for s in all_symbols_info:
                    # 1. Doit être visible dans le Market Watch
                    if not s.visible:
                        continue
                    
                    # 2. Ne doit PAS contenir un mot interdit
                    name_upper = s.name.upper()
                    is_clean = True
                    for bad_word in blacklist:
                        if bad_word in name_upper:
                            is_clean = False
                            break
                    
                    # 3. Si c'est propre (Forex), on ajoute
                    if is_clean:
                        symbols_to_trade.append(s.name)
            # -------------------------------------------------------
            
            if symbols_to_trade:
                print(f"Marchés surveillés ({len(symbols_to_trade)}): {symbols_to_trade[:5]} ...")
            else:
                print("Aucun symbole visible ! Attente...")
                time.sleep(60)
                continue

            daily_pnl = get_daily_pnl()
            print(f"PnL Journalier : {daily_pnl:.2f} USD")
            
            stop_trading_today = False
            if daily_pnl < MAX_DAILY_LOSS:
                print(f"{Col.RED}🛑 Perte Max Journalière atteinte. Trading suspendu.{Col.RESET}")
                stop_trading_today = True
            
            check_recent_losses()
            
            now = datetime.now()
            expired = [s for s, t in cooldowns.items() if now > t]
            for s in expired:
                print(f"✅ Fin de Cooldown pour {s}.")
                del cooldowns[s]
            if expired: save_memory_cooldowns()

            for symbol in symbols_to_trade:
                try:
                    if symbol in cooldowns and not stop_trading_today:
                        continue
                
                    open_trades = count_open_positions(symbol)
                    if open_trades > 0:
                        continue
                        
                    data = handler.get_multi_timeframe_data(symbol)
                    if not data:
                        continue
                     
                    total_positions = mt5.positions_total()
                    if total_positions >= MAX_OPEN_POSITIONS:
                         pass

                    # 1. Indicators (ATR Only)
                    data = engine.add_indicators(data)
                    
                    # 2. Strategy (Pure Fibonacci)
                    # Note: check_signal now handles everything (Swings, Fibs, Zone)
                    signal = 'NEUTRAL'
                    
                    can_trade = (not stop_trading_today) and (total_positions < MAX_OPEN_POSITIONS)
                    
                    if can_trade:
                         signal = generator.check_signal(data, symbol)
                    
                    # 3. Execution
                    signal_type = signal
                    if isinstance(signal, dict):
                        signal_type = signal.get('action', 'NEUTRAL')
                    
                    if signal_type == 'BUY':
                        print(f"{Col.GREEN}!!! SIGNAL BUY (FIBO) SUR {symbol} !!!{Col.RESET}")
                        play_alert('BUY')
                        executor.execute_trade(symbol, signal, data, dry_run=DRY_RUN)
                        
                    elif signal_type == 'SELL':
                        print(f"{Col.RED}!!! SIGNAL SELL (FIBO) SUR {symbol} !!!{Col.RESET}")
                        play_alert('SELL')
                        executor.execute_trade(symbol, signal, data, dry_run=DRY_RUN)
                        
                except Exception as e_inner:
                    print(f"[{symbol}] Erreur interne : {e_inner}")
                    continue

            print("Fin du cycle. Attente 60 secondes...")
            time.sleep(60)

    except KeyboardInterrupt:
        print("\nArrêt manuel.")
    finally:
        mt5.shutdown()
        print("Fin du programme.")

if __name__ == "__main__":
    run_bot()
