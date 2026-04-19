import asyncio
import json
import websockets
import requests
import time
import os
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# CONFIGURATION (LECTURE DEPUIS VARIABLES D'ENVIRONNEMENT)
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DERIV_APP_ID = os.environ.get("DERIV_APP_ID", "36544")

# Liste de TOUS les actifs à scanner (50+ actifs)
SYMBOLS = [
    "R_10", "R_25", "R_50", "R_75", "R_100", "R_150", "R_250",
    "R_15_1S", "R_30_1S", "R_90_1S",
    "CRASH300", "CRASH500", "CRASH600", "CRASH900", "CRASH1000",
    "BOOM300", "BOOM500", "BOOM600", "BOOM900", "BOOM1000",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF", "GBPCHF",
    "GOLD", "SILVER", "OIL", "PLATINUM", "PALLADIUM",
    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD",
    "US500", "US100", "US30", "GER40", "UK100", "FRA40"
]

FULL_NAMES = {
    "R_10": "Volatility 10 Index", "R_25": "Volatility 25 Index", "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index", "R_100": "Volatility 100 Index", "R_150": "Volatility 150 Index",
    "R_250": "Volatility 250 Index", "R_15_1S": "Volatility 15 (1s) Index", "R_30_1S": "Volatility 30 (1s) Index",
    "R_90_1S": "Volatility 90 (1s) Index",
    "CRASH300": "Crash 300 Index", "CRASH500": "Crash 500 Index", "CRASH600": "Crash 600 Index",
    "CRASH900": "Crash 900 Index", "CRASH1000": "Crash 1000 Index",
    "BOOM300": "Boom 300 Index", "BOOM500": "Boom 500 Index", "BOOM600": "Boom 600 Index",
    "BOOM900": "Boom 900 Index", "BOOM1000": "Boom 1000 Index",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
    "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY", "AUDJPY": "AUD/JPY",
    "EURCHF": "EUR/CHF", "GBPCHF": "GBP/CHF",
    "GOLD": "Or (XAU/USD)", "SILVER": "Argent (XAG/USD)", "OIL": "Pétrole Brut (WTI)",
    "PLATINUM": "Platine", "PALLADIUM": "Palladium",
    "BTCUSD": "Bitcoin (BTC/USD)", "ETHUSD": "Ethereum (ETH/USD)", "LTCUSD": "Litecoin (LTC/USD)",
    "XRPUSD": "Ripple (XRP/USD)",
    "US500": "S&P 500", "US100": "Nasdaq 100", "US30": "Dow Jones", "GER40": "DAX 40",
    "UK100": "FTSE 100", "FRA40": "CAC 40"
}

def get_full_name(symbol):
    return FULL_NAMES.get(symbol, symbol)

SCAN_INTERVAL = 300
JOURNAL_FILE = "ultime_v5_journal.csv"

STATS = {"scans": 0, "signals_ultra": 0, "signals_standard": 0, "total_signals": 0}

# ============================================================
# FONCTIONS DE CALCUL TECHNIQUE (IDENTIQUES À LA V4)
# ============================================================

async def fetch_deriv_ticks(symbol):
    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(url, ping_interval=20, ping_timeout=60) as websocket:
            request = {"ticks_history": symbol, "granularity": 300, "count": 100, "style": "candles", "end": "latest"}
            await websocket.send(json.dumps(request))
            response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
            return json.loads(response)
    except Exception as e:
        return {"error": str(e)}

def calculate_ema(closes, period=50):
    if len(closes) < period: return closes[-1] if closes else 0
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]: ema = (price - ema) * multiplier + ema
    return ema

def calculate_adx(highs, lows, closes, period=14):
    if len(highs) < period + 1: return 15, 0, 0
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
        plus_dm = highs[i] - highs[i-1] if highs[i] - highs[i-1] > lows[i-1] - lows[i] else 0
        minus_dm = lows[i-1] - lows[i] if lows[i-1] - lows[i] > highs[i] - highs[i-1] else 0
        plus_dm_list.append(max(plus_dm, 0))
        minus_dm_list.append(max(minus_dm, 0))
    tr_smooth = sum(tr_list[-period:])
    plus_dm_smooth = sum(plus_dm_list[-period:])
    minus_dm_smooth = sum(minus_dm_list[-period:])
    if tr_smooth == 0: return 0, 0, 0
    plus_di = (plus_dm_smooth / tr_smooth) * 100
    minus_di = (minus_dm_smooth / tr_smooth) * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return dx, plus_di, minus_di

def calculate_stoch_rsi(closes, period=14):
    if len(closes) < period + 1: return 50, 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0: gains.append(change); losses.append(0)
        else: gains.append(0); losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: rsi = 100
    else: rs = avg_gain / avg_loss; rsi = 100 - (100 / (1 + rs))
    return rsi, rsi

def calculate_atr(highs, lows, period=14):
    if len(highs) < period + 1: return 0
    tr_list = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - lows[i-1]), abs(lows[i] - lows[i-1]))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / period

def detect_range(adx_history, period=10):
    if len(adx_history) < period: return False
    recent_adx = adx_history[-period:]
    avg_adx = sum(recent_adx) / len(recent_adx)
    max_adx = max(recent_adx)
    return avg_adx < 20 and max_adx < 25

def calculate_confidence_score(signal_data):
    score = 0
    fibo_distance = abs(signal_data['current_price'] - signal_data['fibo_618']) / signal_data['fibo_618']
    if fibo_distance < 0.001: score += 25
    elif fibo_distance < 0.003: score += 15
    elif fibo_distance < 0.005: score += 5
    if signal_data['adx'] >= 40: score += 30
    elif signal_data['adx'] >= 30: score += 20
    elif signal_data['adx'] >= 25: score += 10
    elif signal_data['adx'] >= 20: score += 5
    if signal_data['stoch_k'] < 10 or signal_data['stoch_k'] > 90: score += 20
    elif signal_data['stoch_k'] < 15 or signal_data['stoch_k'] > 85: score += 15
    elif signal_data['stoch_k'] < 20 or signal_data['stoch_k'] > 80: score += 10
    if signal_data['ratio'] >= 5: score += 15
    elif signal_data['ratio'] >= 3: score += 10
    elif signal_data['ratio'] >= 2: score += 5
    if signal_data.get('volume_ratio', 0) > 2: score += 10
    elif signal_data.get('volume_ratio', 0) > 1.5: score += 5
    return score

def get_confidence_level(score):
    if score >= 80: return "🔥🔥🔥 TRÈS ÉLEVÉE"
    elif score >= 60: return "🔥🔥 ÉLEVÉE"
    elif score >= 40: return "🔥 MODÉRÉE"
    else: return "⚠️ FAIBLE"

def save_to_journal(signal_data, quality, confidence_score):
    file_exists = os.path.isfile(JOURNAL_FILE)
    with open(JOURNAL_FILE, 'a', encoding='utf-8') as f:
        if not file_exists: f.write("timestamp,symbol,quality,action,entry,sl,tp,ratio,adx,stoch,confidence_score\n")
        line = f"{datetime.now().isoformat()},{signal_data['symbol']},{quality},{signal_data['action']},{signal_data['current_price']:.5f},{signal_data['sl_price']:.5f},{signal_data['tp_price']:.5f},{signal_data['ratio']:.2f},{signal_data['adx']:.1f},{signal_data['stoch_k']:.1f},{confidence_score}\n"
        f.write(line)

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=60, verify=False)
            if response.status_code == 200: print("✅ Message Telegram envoyé !"); return True
        except Exception as e: print(f"⚠️ Tentative {attempt+1} échouée : {e}")
        if attempt < 2: time.sleep(2)
    return False

def analyze_single_symbol(data, symbol, ultra_secure=True):
    if 'error' in data: return None
    candles = data.get('candles', [])
    if len(candles) < 50: return None
    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    closes = [float(c['close']) for c in candles]
    volumes = [float(c.get('volume', 0)) for c in candles]
    highest = max(highs)
    lowest = min(lows)
    current_price = closes[-1]
    range_movement = highest - lowest
    fibo_618 = lowest + range_movement * 0.618
    in_fibo_zone = abs(current_price - fibo_618) / fibo_618 < 0.005
    adx, plus_di, minus_di = calculate_adx(highs, lows, closes)
    adx_threshold = 25 if ultra_secure else 20
    strong_trend = adx >= adx_threshold
    adx_history = [calculate_adx(highs[i:i+50], lows[i:i+50], closes[i:i+50])[0] for i in range(0, len(highs)-50, 10)]
    in_range = detect_range(adx_history)
    if in_range: return None
    stoch_k, _ = calculate_stoch_rsi(closes)
    stoch_low = 15 if ultra_secure else 20
    stoch_high = 85 if ultra_secure else 80
    stoch_oversold = stoch_k < stoch_low
    stoch_overbought = stoch_k > stoch_high
    stoch_valid = stoch_oversold or stoch_overbought
    volume_ratio = 1
    if ultra_secure:
        if len(volumes) >= 20 and sum(volumes[-20:]) > 0:
            avg_volume = sum(volumes[-20:]) / 20
            current_volume = volumes[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            volume_valid = current_volume > avg_volume * 1.5
        else: volume_valid = False
    else: volume_valid = True
    ema_50 = calculate_ema(closes, 50)
    ema_20 = calculate_ema(closes[-30:], 20) if len(closes) >= 30 else ema_50
    trend_short = current_price > ema_20
    trend_long = current_price > ema_50
    trend_aligned = trend_short == trend_long
    if not trend_aligned: return None
    conditions_met = in_fibo_zone and strong_trend and stoch_valid
    if ultra_secure: conditions_met = conditions_met and volume_valid
    if conditions_met:
        atr = calculate_atr(highs, lows)
        if atr == 0: return None
        if stoch_oversold and trend_long:
            action = "ACHAT (BUY) 🟢"
            sl_price = current_price - atr * 1.5
            ext_0272 = highest + range_movement * 0.272
            ext_0618 = highest + range_movement * 0.618
            ext_1000 = highest + range_movement * 1.000
            stoch_status = "SURVENDU"
        elif stoch_overbought and not trend_long:
            action = "VENTE (SELL) 🔴"
            sl_price = current_price + atr * 1.5
            ext_0272 = lowest - range_movement * 0.272
            ext_0618 = lowest - range_movement * 0.618
            ext_1000 = lowest - range_movement * 1.000
            stoch_status = "SURACHETÉ"
        else: return None
        if adx >= 40: tp_price = ext_1000; tp_label = "EXT -1.000"
        elif adx >= 25: tp_price = ext_0618; tp_label = "EXT -0.618"
        else: tp_price = ext_0272; tp_label = "EXT -0.272"
        ratio = abs(current_price - tp_price) / (atr * 1.5)
        signal_data = {
            "symbol": symbol, "full_name": get_full_name(symbol), "action": action,
            "current_price": current_price, "fibo_618": fibo_618, "adx": adx,
            "stoch_k": stoch_k, "stoch_status": stoch_status, "ema_50": ema_50,
            "volume_ratio": volume_ratio, "volume_valid": volume_valid if ultra_secure else None,
            "sl_price": sl_price, "tp_price": tp_price, "tp_label": tp_label, "ratio": ratio,
            "quality": "ULTRA" if ultra_secure else "STANDARD", "trend_aligned": trend_aligned, "in_range": in_range
        }
        confidence_score = calculate_confidence_score(signal_data)
        signal_data['confidence_score'] = confidence_score
        signal_data['confidence_level'] = get_confidence_level(confidence_score)
        return signal_data
    return None

async def scan_all_symbols(ultra_secure=True):
    signals = []
    mode_str = "ULTRA-SÉCURISÉ" if ultra_secure else "STANDARD"
    print(f"\n🔎 PASSE {mode_str} ({len(SYMBOLS)} actifs)...")
    for symbol in SYMBOLS:
        print(f"🔍 Scan de {get_full_name(symbol)}...")
        data = await fetch_deriv_ticks(symbol)
        signal = analyze_single_symbol(data, symbol, ultra_secure)
        if signal:
            signals.append(signal)
            print(f"   ✅ Signal trouvé sur {signal['full_name']} - Score: {signal['confidence_score']}/100 - Ratio: 1:{signal['ratio']:.1f}")
            quality_emoji = "🏆" if ultra_secure else "📌"
            quality_text = "ULTRA-SÉCURISÉ" if ultra_secure else "STANDARD"
            message = f"""
{quality_emoji} SIGNAL ULTIME V.5 - {quality_text}

📊 Actif : {signal['full_name']}
📋 Action : {signal['action']}
⭐ Score : {signal['confidence_score']}/100 ({signal['confidence_level']})

📍 Entrée : {signal['current_price']:.5f}
🎯 Zone Fibo 0.618 : {signal['fibo_618']:.5f}
💪 ADX : {signal['adx']:.1f}
⚡ Stochastique : {signal['stoch_k']:.1f} ({signal['stoch_status']})
🛑 Stop Loss : {signal['sl_price']:.5f}
💰 Take Profit ({signal['tp_label']}) : {signal['tp_price']:.5f}
📈 Ratio : 1:{signal['ratio']:.1f}

⚠️ Vérifie bien le Stop Loss avant de valider !
"""
            send_telegram_message(message)
        else: print(f"   ❌ Pas de signal sur {get_full_name(symbol)}")
        await asyncio.sleep(1.5)
    return signals

async def double_pass_scan():
    signals = await scan_all_symbols(ultra_secure=True)
    if signals: return signals, "ULTRA"
    print("\n⚠️ Aucun signal ULTRA. Passage en mode STANDARD...")
    signals = await scan_all_symbols(ultra_secure=False)
    return signals, "STANDARD"

def main():
    print("🚀 DÉMARRAGE DU SCAN ULTIME V.5 (V4 - MULTI-MARCHÉS)")
    print("=" * 70)
    print(f"📊 {len(SYMBOLS)} actifs scannés toutes les {SCAN_INTERVAL // 60} minutes.")
    print("🛡️ Stratégie : Ultra-Sécurisé → Standard (Double Passe)")
    print("📈 Améliorations : Score de confiance, Range, Multi-TF, Journal CSV")
    print("⚡ Envoi Telegram INSTANTANÉ")
    print("=" * 70)
    scan_count = 0
    while True:
        scan_count += 1
        STATS["scans"] += 1
        print(f"\n🕐 Scan #{scan_count} - {time.strftime('%H:%M:%S')}")
        print("-" * 70)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            signals, quality = loop.run_until_complete(double_pass_scan())
            loop.close()
            print(f"\n📊 RÉSULTATS : {len(signals)} signal(aux) trouvé(s) [Qualité: {quality}]")
            if signals:
                if quality == "ULTRA": STATS["signals_ultra"] += len(signals)
                else: STATS["signals_standard"] += len(signals)
                STATS["total_signals"] += len(signals)
                signals.sort(key=lambda x: x['confidence_score'], reverse=True)
                recap = f"""
📊 RÉCAPITULATIF SCAN #{scan_count}

✅ {len(signals)} signal(aux) trouvé(s) [{quality}]
📈 Stats depuis démarrage :
• Scans : {STATS['scans']}
• ULTRA : {STATS['signals_ultra']}
• STANDARD : {STATS['signals_standard']}

⏳ Prochain scan dans {SCAN_INTERVAL // 60} min.
"""
                send_telegram_message(recap)
            else:
                no_signal_message = f"""
📊 RAPPORT ULTIME V.5 - SCAN #{scan_count}

🕐 Heure : {time.strftime('%H:%M:%S')}
🔍 Actifs scannés : {len(SYMBOLS)}
📋 Signaux trouvés : 0

📈 Stats depuis démarrage :
• Scans : {STATS['scans']}
• ULTRA : {STATS['signals_ultra']}
• STANDARD : {STATS['signals_standard']}

💤 Marché calme. Prochain scan dans {SCAN_INTERVAL // 60} min.
"""
                print("❌ Aucun signal.")
                send_telegram_message(no_signal_message)
        except Exception as e:
            error_message = f"⚠️ Erreur scan #{scan_count}: {str(e)[:100]}"
            print(error_message)
            send_telegram_message(error_message)
        print(f"\n⏳ Prochain scan dans {SCAN_INTERVAL // 60} minutes...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
