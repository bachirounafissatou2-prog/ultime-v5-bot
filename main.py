#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONFLUENCE 3.0 - Système de Trading Algorithmique
Version Finale avec Support/Résistance et Signal Garanti
"""

import asyncio
import json
import websockets
import requests
import time
import os
import urllib3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# CONFIGURATION CENTRALISÉE
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8649949649:AAGCngwn-mYUfcdI-KYbeBdQTvgiiI0gD_A")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8400153330")
DERIV_APP_ID = os.environ.get("DERIV_APP_ID", "36544")

CAPITAL = float(os.environ.get("TRADING_CAPITAL", "1000.0"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.0"))

SYMBOLS = [
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "CRASH500", "CRASH1000", "BOOM500", "BOOM1000",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY",
    "GOLD", "SILVER",
    "BTCUSD", "ETHUSD",
    "US500", "US100", "GER40"
]

FULL_NAMES = {
    "R_10": "Volatility 10", "R_25": "Volatility 25", "R_50": "Volatility 50",
    "R_75": "Volatility 75", "R_100": "Volatility 100",
    "CRASH500": "Crash 500", "CRASH1000": "Crash 1000",
    "BOOM500": "Boom 500", "BOOM1000": "Boom 1000",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
    "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY",
    "GOLD": "Or (XAU/USD)", "SILVER": "Argent (XAG/USD)",
    "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum",
    "US500": "S&P 500", "US100": "Nasdaq 100", "GER40": "DAX 40"
}

ASSET_TYPES = {
    "R_10": "synthetic", "R_25": "synthetic", "R_50": "synthetic",
    "R_75": "synthetic", "R_100": "synthetic",
    "CRASH500": "crash_boom", "CRASH1000": "crash_boom",
    "BOOM500": "crash_boom", "BOOM1000": "crash_boom",
    "EURUSD": "forex", "GBPUSD": "forex", "USDJPY": "forex",
    "AUDUSD": "forex", "USDCAD": "forex", "NZDUSD": "forex",
    "EURGBP": "forex", "EURJPY": "forex", "GBPJPY": "forex",
    "GOLD": "forex", "SILVER": "forex",
    "BTCUSD": "crypto", "ETHUSD": "crypto",
    "US500": "indices", "US100": "indices", "GER40": "indices"
}

SCAN_INTERVAL = 300
JOURNAL_FILE = "confluence_v3_journal.csv"

STATS = {"scans": 0, "total_signals": 0}

def get_full_name(symbol: str) -> str:
    return FULL_NAMES.get(symbol, symbol)

def get_asset_type(symbol: str) -> str:
    return ASSET_TYPES.get(symbol, "unknown")

# ============================================================
# INDICATEURS TECHNIQUES
# ============================================================

def calculate_ema(data: List[float], period: int) -> float:
    if len(data) < period:
        return data[-1] if data else 0.0
    multiplier = 2.0 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(change if change > 0 else 0)
        losses.append(abs(change) if change < 0 else 0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_stoch_rsi(closes: List[float], period: int = 14, smooth_k: int = 3) -> Tuple[float, float]:
    if len(closes) < period + smooth_k:
        return 50.0, 50.0
    rsi_values = []
    for i in range(period, len(closes) + 1):
        window = closes[max(0, i-period):i]
        if len(window) >= period:
            rsi_values.append(calculate_rsi(window, period))
    if len(rsi_values) < period:
        return 50.0, 50.0
    min_rsi = min(rsi_values[-period:])
    max_rsi = max(rsi_values[-period:])
    if max_rsi - min_rsi == 0:
        return 50.0, 50.0
    stoch_k = ((rsi_values[-1] - min_rsi) / (max_rsi - min_rsi)) * 100.0
    recent_stoch = []
    for i in range(-smooth_k, 0):
        if i - period >= 0:
            min_r = min(rsi_values[i-period:i])
            max_r = max(rsi_values[i-period:i])
        else:
            min_r = min(rsi_values[:i])
            max_r = max(rsi_values[:i])
        if max_r - min_r > 0:
            recent_stoch.append(((rsi_values[i] - min_r) / (max_r - min_r)) * 100)
    stoch_d = sum(recent_stoch) / len(recent_stoch) if recent_stoch else stoch_k
    return stoch_k, stoch_d

def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Tuple[float, float, float]:
    if len(highs) < period + 1:
        return 15.0, 0.0, 0.0
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
    if tr_smooth == 0:
        return 0.0, 0.0, 0.0
    plus_di = (plus_dm_smooth / tr_smooth) * 100.0
    minus_di = (minus_dm_smooth / tr_smooth) * 100.0
    dx_sum = 0.0
    for i in range(-period, 0):
        if tr_list[i] > 0:
            p_di = (sum(plus_dm_list[max(0, i-period):i]) / tr_list[i]) * 100
            m_di = (sum(minus_dm_list[max(0, i-period):i]) / tr_list[i]) * 100
            if p_di + m_di > 0:
                dx_sum += abs(p_di - m_di) / (p_di + m_di) * 100.0
    adx = dx_sum / period if period > 0 else 0.0
    return adx, plus_di, minus_di

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / period

def calculate_macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line * 0.5
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def detect_swings(highs: List[float], lows: List[float], window: int = 5) -> Tuple[List[float], List[float]]:
    swing_highs, swing_lows = [], []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i-window:i+window+1]):
            swing_lows.append(lows[i])
    return swing_highs, swing_lows

# ============================================================
# SUPPORT / RÉSISTANCE HORIZONTAUX
# ============================================================

def find_support_resistance_levels(highs: List[float], lows: List[float], window: int = 5, tolerance_pct: float = 0.003) -> List[float]:
    swing_highs, swing_lows = detect_swings(highs, lows, window)
    all_swings = swing_highs + swing_lows
    if not all_swings:
        return []
    levels = []
    all_swings.sort()
    current_group = [all_swings[0]]
    for price in all_swings[1:]:
        if abs(price - current_group[-1]) / current_group[-1] < tolerance_pct:
            current_group.append(price)
        else:
            levels.append(sum(current_group) / len(current_group))
            current_group = [price]
    levels.append(sum(current_group) / len(current_group))
    return levels

def is_near_sr_level(current_price: float, sr_levels: List[float], tolerance_pct: float = 0.005) -> bool:
    for level in sr_levels:
        if abs(current_price - level) / level < tolerance_pct:
            return True
    return False

# ============================================================
# FIBONACCI AUTOMATIQUE
# ============================================================

def calculate_fibonacci_levels(high: float, low: float, is_uptrend: bool = True) -> Dict[str, float]:
    diff = high - low
    if is_uptrend:
        return {
            "0.0": high, "0.236": high - diff * 0.236, "0.382": high - diff * 0.382,
            "0.5": high - diff * 0.5, "0.618": high - diff * 0.618, "0.786": high - diff * 0.786,
            "1.0": low, "-0.272": high + diff * 0.272, "-0.618": high + diff * 0.618,
            "-1.0": high + diff * 1.0, "-1.618": high + diff * 1.618
        }
    else:
        return {
            "0.0": low, "0.236": low + diff * 0.236, "0.382": low + diff * 0.382,
            "0.5": low + diff * 0.5, "0.618": low + diff * 0.618, "0.786": low + diff * 0.786,
            "1.0": high, "-0.272": low - diff * 0.272, "-0.618": low - diff * 0.618,
            "-1.0": low - diff * 1.0, "-1.618": low - diff * 1.618
        }

def is_price_in_fibo_zone(price: float, fibo_level: float, tolerance: float = 0.008) -> bool:
    return abs(price - fibo_level) / fibo_level < tolerance

def select_auto_tp_level(fibo_levels: Dict[str, float], adx: float, is_buy: bool) -> Tuple[float, str]:
    if adx >= 40:
        level, name = "-1.0", "EXT -1.0"
    elif adx >= 30:
        level, name = "-0.618", "EXT -0.618"
    else:
        level, name = "-0.272", "EXT -0.272"
    return fibo_levels[level], name

# ============================================================
# FILTRES SPÉCIFIQUES PAR TYPE D'ACTIF
# ============================================================

def is_market_open(asset_type: str) -> bool:
    now = datetime.utcnow()
    hour = now.hour
    weekday = now.weekday()
    if asset_type == "forex":
        if weekday == 4 and hour >= 22:
            return False
        if weekday == 5:
            return False
        if weekday == 6 and hour < 22:
            return False
        return True
    elif asset_type == "indices":
        return weekday < 5
    elif asset_type in ["crypto", "synthetic", "crash_boom"]:
        return True
    return True

def apply_asset_filters(symbol: str, signal_data: Dict) -> Tuple[bool, int]:
    asset_type = get_asset_type(symbol)
    bonus = 0
    if asset_type == "synthetic":
        if signal_data.get('adx', 0) < 20:
            return False, 0
        bonus = 5
    elif asset_type == "crash_boom":
        is_crash = "CRASH" in symbol
        is_buy = "ACHAT" in signal_data.get('action', '')
        if is_crash and not is_buy:
            bonus = 10
        elif not is_crash and is_buy:
            bonus = 10
        else:
            return False, 0
    elif asset_type == "forex":
        if not is_market_open("forex"):
            return False, 0
    elif asset_type == "crypto":
        if signal_data.get('atr_ratio', 1.0) < 1.5:
            return False, 0
        bonus = 5
    elif asset_type == "indices":
        if not is_market_open("indices"):
            return False, 0
    return True, bonus

# ============================================================
# SCORE DE CONFLUENCE (MAX 140 pts avec S/R)
# ============================================================

def calculate_confluence_score(signal_data: Dict, fibo_bonus: int = 0, asset_bonus: int = 0, sr_bonus: int = 0) -> int:
    score = 0
    if signal_data.get('trend_h1', False) and signal_data.get('trend_m15', False):
        score += 20
    elif signal_data.get('trend_h1', False):
        score += 10
    if signal_data.get('in_fibo_zone', False):
        score += 15
    adx = signal_data.get('adx', 0)
    if adx >= 40:
        score += 15
    elif adx >= 30:
        score += 12
    elif adx >= 25:
        score += 10
    rsi = signal_data.get('rsi', 50)
    if rsi < 25 or rsi > 75:
        score += 15
    elif rsi < 30 or rsi > 70:
        score += 10
    stoch_k = signal_data.get('stoch_k', 50)
    if stoch_k < 15 or stoch_k > 85:
        score += 10
    elif stoch_k < 20 or stoch_k > 80:
        score += 5
    if signal_data.get('macd_aligned', False):
        score += 10
    if signal_data.get('volume_valid', False):
        score += 5
    score += fibo_bonus + asset_bonus + sr_bonus
    if signal_data.get('macd_divergence', False):
        score += 10
    return min(score, 140)

def get_signal_quality(score: int) -> str:
    if score >= 85:
        return "PREMIUM 🏆"
    elif score >= 70:
        return "STANDARD ✅"
    else:
        return "FAIBLE ⚠️"

def calculate_raw_score(signal_data: Dict, in_fibo_zone: bool, strong_trend: bool,
                        stoch_extreme: bool, rsi_extreme: bool, macd_aligned: bool,
                        volume_valid: bool, trend_aligned: bool, near_sr: bool) -> int:
    score = 0
    if in_fibo_zone:
        distance = abs(signal_data['current_price'] - signal_data['fibo_618']) / signal_data['fibo_618']
        if distance < 0.003:
            score += 20
        elif distance < 0.006:
            score += 15
        elif distance < 0.01:
            score += 10
        else:
            score += 5
    adx = signal_data.get('adx', 0)
    if adx >= 40:
        score += 20
    elif adx >= 30:
        score += 15
    elif adx >= 25:
        score += 10
    elif adx >= 20:
        score += 5
    rsi = signal_data.get('rsi', 50)
    if rsi < 25 or rsi > 75:
        score += 15
    elif rsi < 30 or rsi > 70:
        score += 10
    elif rsi < 35 or rsi > 65:
        score += 5
    stoch_k = signal_data.get('stoch_k', 50)
    if stoch_k < 15 or stoch_k > 85:
        score += 15
    elif stoch_k < 20 or stoch_k > 80:
        score += 10
    elif stoch_k < 25 or stoch_k > 75:
        score += 5
    if trend_aligned:
        score += 10
    if macd_aligned:
        score += 10
    if volume_valid:
        score += 10
    if near_sr:
        score += 10
    return min(score, 100)

# ============================================================
# GESTION DU RISQUE
# ============================================================

def calculate_position_size(capital: float, risk_percent: float, entry: float, stop_loss: float) -> float:
    risk_amount = capital * (risk_percent / 100.0)
    sl_distance = abs(entry - stop_loss)
    if sl_distance == 0:
        return 0.0
    return round(risk_amount / sl_distance, 2)

# ============================================================
# ANALYSE D'UN ACTIF
# ============================================================

async def fetch_ticks(symbol: str, granularity: int = 300, count: int = 100) -> Dict:
    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
            request = {"ticks_history": symbol, "granularity": granularity, "count": count, "style": "candles", "end": "latest"}
            await ws.send(json.dumps(request))
            response = await asyncio.wait_for(ws.recv(), timeout=30.0)
            return json.loads(response)
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

def analyze_symbol(data: Dict, symbol: str) -> Optional[Dict]:
    if 'error' in data:
        return None
    candles = data.get('candles', [])
    if len(candles) < 60:
        return None

    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    closes = [float(c['close']) for c in candles]
    volumes = [float(c.get('volume', 0)) for c in candles]
    current_price = closes[-1]

    swing_highs, swing_lows = detect_swings(highs, lows, window=5)
    if not swing_highs or not swing_lows:
        return None

    recent_high = max(swing_highs[-3:]) if len(swing_highs) >= 3 else max(highs)
    recent_low = min(swing_lows[-3:]) if len(swing_lows) >= 3 else min(lows)

    is_uptrend = closes[-1] > closes[-20]
    fibo_levels = calculate_fibonacci_levels(recent_high, recent_low, is_uptrend)
    fibo_618 = fibo_levels["0.618"]
    in_fibo_zone = is_price_in_fibo_zone(current_price, fibo_618)

    rsi = calculate_rsi(closes, 14)
    stoch_k, stoch_d = calculate_stoch_rsi(closes, 14)
    adx, plus_di, minus_di = calculate_adx(highs, lows, closes, 14)
    atr = calculate_atr(highs, lows, closes, 14)
    macd, macd_signal, macd_hist = calculate_macd(closes)

    ema_50 = calculate_ema(closes, 50)
    ema_20 = calculate_ema(closes[-30:], 20) if len(closes) >= 30 else ema_50

    avg_volume = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
    volume_valid = volumes[-1] > avg_volume * 1.5 if avg_volume > 0 else True

    trend_aligned = (current_price > ema_20 and current_price > ema_50) or (current_price < ema_20 and current_price < ema_50)
    strong_trend = adx >= 25
    stoch_extreme = stoch_k < 20 or stoch_k > 80
    rsi_extreme = rsi < 30 or rsi > 70
    macd_aligned = (macd_hist > 0 and is_uptrend) or (macd_hist < 0 and not is_uptrend)

    sr_levels = find_support_resistance_levels(highs, lows)
    near_sr = is_near_sr_level(current_price, sr_levels)

    classic_valid = False
    if is_uptrend and stoch_k < 20 and rsi < 40 and in_fibo_zone:
        action = "ACHAT (BUY) 🟢"
        sl_price = current_price - atr * 1.5
        tp_price, tp_label = select_auto_tp_level(fibo_levels, adx, True)
        stoch_status = "SURVENDU"
        classic_valid = True
    elif not is_uptrend and stoch_k > 80 and rsi > 60 and in_fibo_zone:
        action = "VENTE (SELL) 🔴"
        sl_price = current_price + atr * 1.5
        tp_price, tp_label = select_auto_tp_level(fibo_levels, adx, False)
        stoch_status = "SURACHETÉ"
        classic_valid = True
    else:
        if is_uptrend:
            action = "ACHAT (BUY) 🟢"
            sl_price = current_price - atr * 1.5
            tp_price, tp_label = select_auto_tp_level(fibo_levels, adx, True)
            stoch_status = "NEUTRE"
        else:
            action = "VENTE (SELL) 🔴"
            sl_price = current_price + atr * 1.5
            tp_price, tp_label = select_auto_tp_level(fibo_levels, adx, False)
            stoch_status = "NEUTRE"

    signal_data = {
        'symbol': symbol, 'full_name': get_full_name(symbol), 'action': action,
        'current_price': current_price, 'fibo_618': fibo_618, 'in_fibo_zone': in_fibo_zone,
        'adx': adx, 'rsi': rsi, 'stoch_k': stoch_k, 'stoch_status': stoch_status,
        'sl_price': sl_price, 'tp_price': tp_price, 'tp_label': tp_label,
        'trend_h1': is_uptrend, 'trend_m15': trend_aligned,
        'macd_aligned': macd_aligned, 'volume_valid': volume_valid,
        'classic_valid': classic_valid, 'near_sr': near_sr
    }

    raw_score = calculate_raw_score(signal_data, in_fibo_zone, strong_trend,
                                    stoch_extreme, rsi_extreme, macd_aligned,
                                    volume_valid, trend_aligned, near_sr)

    signal_data['raw_score'] = raw_score
    signal_data['confidence'] = "🔥 ÉLEVÉE" if raw_score >= 70 else "📊 MOYENNE" if raw_score >= 50 else "⚠️ FAIBLE"

    return signal_data

# ============================================================
# SCAN PARALLÈLE ET SÉLECTION DU MEILLEUR
# ============================================================

async def scan_all_symbols_parallel(symbols: List[str]) -> List[Dict]:
    print(f"\n🔎 Scan parallèle de {len(symbols)} actifs...")
    tasks = [fetch_ticks(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_signals = []
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            continue
        if isinstance(result, dict):
            signal = analyze_symbol(result, symbol)
            if signal:
                all_signals.append(signal)

    all_signals.sort(key=lambda x: x['raw_score'], reverse=True)
    best_signals = all_signals[:1]

    for signal in best_signals:
        print(f"   🏆 MEILLEUR : {signal['full_name']} - Score brut: {signal['raw_score']}/100 - {signal['confidence']}")
        save_to_journal(signal)
        message = format_signal_message(signal)
        send_telegram_message(message)

    return best_signals

# ============================================================
# JOURNAL ET NOTIFICATIONS
# ============================================================

def save_to_journal(signal_data: Dict):
    file_exists = os.path.isfile(JOURNAL_FILE)
    with open(JOURNAL_FILE, 'a', encoding='utf-8') as f:
        if not file_exists:
            f.write("timestamp,symbol,confidence,action,entry,sl,tp,raw_score\n")
        line = (f"{datetime.now().isoformat()},{signal_data['symbol']},{signal_data['confidence']},"
                f"{signal_data['action']},{signal_data['current_price']:.5f},{signal_data['sl_price']:.5f},"
                f"{signal_data['tp_price']:.5f},{signal_data['raw_score']}\n")
        f.write(line)

def send_telegram_message(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=30, verify=False)
            if response.status_code == 200:
                print("✅ Message Telegram envoyé")
                return True
        except Exception as e:
            print(f"⚠️ Tentative {attempt+1} échouée : {e}")
            time.sleep(2)
    return False

def format_signal_message(signal: Dict) -> str:
    classic_badge = "✅ SIGNAL CLASSIQUE" if signal.get('classic_valid') else "📊 MEILLEUR DU SCAN"
    return f"""
{classic_badge}

📊 Actif : {signal['full_name']}
📋 Action : {signal['action']}
⭐ Score brut : {signal['raw_score']}/100
🔥 Confiance : {signal['confidence']}

📍 Entrée : {signal['current_price']:.5f}
🎯 Fibo 0.618 : {signal['fibo_618']:.5f}
💪 ADX : {signal['adx']:.1f}
📊 RSI : {signal['rsi']:.1f}
⚡ Stoch RSI : {signal['stoch_k']:.1f} ({signal['stoch_status']})
🧱 Proche S/R : {'Oui (+10 pts)' if signal.get('near_sr') else 'Non'}

🛑 SL : {signal['sl_price']:.5f}
💰 TP ({signal['tp_label']}) : {signal['tp_price']:.5f}
"""

# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

async def main():
    print("🚀 CONFLUENCE 3.0 - DÉMARRAGE (Support/Résistance + Signal Garanti)")
    print("=" * 60)
    print(f"📊 {len(SYMBOLS)} actifs | Scan toutes les {SCAN_INTERVAL // 60} min")
    print("=" * 60)

    scan_count = 0
    while True:
        scan_count += 1
        STATS["scans"] += 1
        print(f"\n🕐 Scan #{scan_count} - {datetime.now().strftime('%H:%M:%S')}")

        try:
            signals = await scan_all_symbols_parallel(SYMBOLS)
            STATS["total_signals"] += len(signals)
            recap = f"📊 Scan #{scan_count} : {len(signals)} signal(aux) | Total : {STATS['total_signals']}"
            send_telegram_message(recap)
        except Exception as e:
            print(f"⚠️ Erreur scan : {e}")

        print(f"\n⏳ Prochain scan dans {SCAN_INTERVAL // 60} minutes...")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
