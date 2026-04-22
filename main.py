#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIBONACCI GOAT - Stratégie Ken Ahyee
Version Finale - Code Complet
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
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8649949649:AAGCngwn-mYUfcdI-KYbeBdQTvgiiI0gD_A")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8400153330")
DERIV_APP_ID = os.environ.get("DERIV_APP_ID", "36544")

# Actifs prioritaires (ceux qui font de grandes vagues)
SYMBOLS = [
    "GOLD", "US100", "GER40", "BTCUSD", "ETHUSD",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
    "R_100", "CRASH1000", "BOOM1000"
]

FULL_NAMES = {
    "GOLD": "Or (XAU/USD)", "US100": "Nasdaq 100", "GER40": "DAX 40",
    "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
    "R_100": "Volatility 100", "CRASH1000": "Crash 1000", "BOOM1000": "Boom 1000"
}

GIANT_ASSETS = ["GOLD", "US100", "GER40", "BTCUSD", "ETHUSD"]
SCAN_INTERVAL = 300
STATS = {"scans": 0, "signals": 0}

# ============================================================
# INDICATEURS TECHNIQUES
# ============================================================

def calculate_ema(data: List[float], period: int) -> float:
    if len(data) < period: return data[-1] if data else 0.0
    multiplier = 2.0 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]: ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(change if change > 0 else 0)
        losses.append(abs(change) if change < 0 else 0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(highs) < period + 1: return 15.0
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
    
    if tr_smooth == 0: return 0.0
    plus_di = (plus_dm_smooth / tr_smooth) * 100.0
    minus_di = (minus_dm_smooth / tr_smooth) * 100.0
    
    dx_sum = 0.0
    for i in range(-period, 0):
        if tr_list[i] > 0:
            p_di = (sum(plus_dm_list[max(0, i-period):i]) / tr_list[i]) * 100
            m_di = (sum(minus_dm_list[max(0, i-period):i]) / tr_list[i]) * 100
            if p_di + m_di > 0: dx_sum += abs(p_di - m_di) / (p_di + m_di) * 100.0
    return dx_sum / period if period > 0 else 0.0

def detect_swings(highs: List[float], lows: List[float], window: int = 5) -> Tuple[List[float], List[float]]:
    swing_highs, swing_lows = [], []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i-window:i+window+1]): swing_highs.append(highs[i])
        if lows[i] == min(lows[i-window:i+window+1]): swing_lows.append(lows[i])
    return swing_highs, swing_lows

def detect_rejection(candles: List[Dict]) -> Tuple[bool, str]:
    if len(candles) < 2: return False, None
    candle = candles[-2]
    body = abs(candle['close'] - candle['open'])
    upper_wick = candle['high'] - max(candle['close'], candle['open'])
    lower_wick = min(candle['close'], candle['open']) - candle['low']
    
    if lower_wick > body * 2.0: return True, 'bullish'
    elif upper_wick > body * 2.0: return True, 'bearish'
    return False, None

# ============================================================
# FIBONACCI GOAT
# ============================================================

def calculate_fibo_levels(high: float, low: float, is_uptrend: bool = True) -> Dict[str, float]:
    diff = high - low
    if is_uptrend:
        return {
            "0.000": high, "0.500": high - diff * 0.500, "0.618": high - diff * 0.618,
            "0.786": high - diff * 0.786, "1.000": low,
            "-0.272": high + diff * 0.272, "-0.618": high + diff * 0.618,
            "-1.000": high + diff * 1.000, "-1.618": high + diff * 1.618
        }
    else:
        return {
            "0.000": low, "0.500": low + diff * 0.500, "0.618": low + diff * 0.618,
            "0.786": low + diff * 0.786, "1.000": high,
            "-0.272": low - diff * 0.272, "-0.618": low - diff * 0.618,
            "-1.000": low - diff * 1.000, "-1.618": low - diff * 1.618
        }

def is_in_golden_zone(price: float, fibo: Dict) -> bool:
    return fibo["0.500"] <= price <= fibo["0.786"] or fibo["0.786"] <= price <= fibo["0.500"]

def calculate_tp_levels(entry: float, fibo: Dict, adx: float, wave_amp: float, is_giant: bool) -> Dict:
    tp = {}
    
    if is_giant:
        tp["tp1"] = {"price": fibo["-0.272"], "close_pct": 30, "label": "TP1 (-0.272)"}
        tp["tp2"] = {"price": fibo["-0.618"], "close_pct": 30, "label": "TP2 (-0.618)"}
        tp["tp_giant"] = {"price": fibo["-1.000"], "close_pct": 20, "label": "TP GIANT (-1.000)"}
        tp["tp_dream"] = {"price": fibo["-1.618"], "close_pct": 20, "label": "TP DREAM (-1.618)"}
    else:
        tp["tp1"] = {"price": fibo["-0.272"], "close_pct": 40, "label": "TP1 (-0.272)"}
        tp["tp2"] = {"price": fibo["-0.618"], "close_pct": 30, "label": "TP2 (-0.618)"}
        if adx >= 40: tp["tp_final"] = {"price": fibo["-1.000"], "close_pct": 30, "label": "TP FINAL (-1.000)"}
        else: tp["tp2"]["close_pct"] = 60
    
    return tp

# ============================================================
# ANALYSE PRINCIPALE
# ============================================================

async def fetch_ticks(symbol: str, timeframe: str = "H1") -> Dict:
    granularity = {"M5": 60, "M15": 300, "H1": 3600, "H4": 14400}.get(timeframe, 3600)
    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
            request = {"ticks_history": symbol, "granularity": granularity, "count": 100, "style": "candles", "end": "latest"}
            await ws.send(json.dumps(request))
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=30.0))
    except: return {"error": "timeout"}

def analyze_goat(data: Dict, symbol: str, timeframe: str) -> Optional[Dict]:
    if 'error' in data: return None
    candles = data.get('candles', [])
    if len(candles) < 60: return None

    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    closes = [float(c['close']) for c in candles]
    current_price = closes[-1]
    
    # 1. Structure
    swing_highs, swing_lows = detect_swings(highs, lows)
    if not swing_highs or not swing_lows: return None
    recent_high, recent_low = max(swing_highs[-3:]), min(swing_lows[-3:])
    wave_amplitude = abs(recent_high - recent_low)
    
    # 2. Tendance
    is_uptrend = closes[-1] > closes[-20]
    fibo = calculate_fibo_levels(recent_high, recent_low, is_uptrend)
    
    # 3. Golden Zone
    if not is_in_golden_zone(current_price, fibo): return None
    
    # 4. Rejet
    is_rej, direction = detect_rejection(candles)
    if not is_rej: return None
    if (direction == 'bullish' and not is_uptrend) or (direction == 'bearish' and is_uptrend): return None
    
    # 5. Momentum
    rsi = calculate_rsi(closes)
    if (direction == 'bullish' and rsi > 30) or (direction == 'bearish' and rsi < 70): return None
    
    # 6. ADX
    adx = calculate_adx(highs, lows, closes)
    
    # 7. Détermination du mode
    is_giant = (symbol in GIANT_ASSETS and timeframe in ["H4", "D1"] and wave_amplitude > 300)
    
    # 8. SL
    if direction == 'bullish': sl = min(fibo["0.786"], fibo["1.000"]) - (current_price * 0.001)
    else: sl = max(fibo["0.786"], fibo["1.000"]) + (current_price * 0.001)
    
    # 9. Ratio R/R minimum
    tp1_price = fibo["-0.272"]
    risk = abs(current_price - sl)
    reward = abs(tp1_price - current_price)
    if risk == 0 or (reward / risk) < 2.0: return None
    
    # 10. TP Levels
    tp_levels = calculate_tp_levels(current_price, fibo, adx, wave_amplitude, is_giant)
    
    action = "ACHAT (BUY) 🟢" if direction == 'bullish' else "VENTE (SELL) 🔴"
    setup_type = "🚀 GÉANT" if is_giant else "✅ STANDARD"
    
    return {
        "symbol": symbol, "full_name": FULL_NAMES.get(symbol, symbol),
        "action": action, "setup": setup_type,
        "entry": current_price, "sl": sl, "tp_levels": tp_levels,
        "wave": wave_amplitude, "adx": adx, "rsi": rsi,
        "timeframe": timeframe
    }

def format_goat_message(signal: Dict) -> str:
    tp_lines = "\n".join([f"💰 {tp['label']} : {tp['price']:.5f} (Fermer {tp['close_pct']}%)" for tp in signal['tp_levels'].values()])
    risk = abs(signal['entry'] - signal['sl'])
    reward = abs(list(signal['tp_levels'].values())[0]['price'] - signal['entry'])
    ratio = reward / risk if risk > 0 else 0
    
    return f"""
{signal['setup']} SETUP - FIBONACCI GOAT

📊 Actif : {signal['full_name']}
⏰ Timeframe : {signal['timeframe']}
📏 Vague : {signal['wave']:.1f} pips
📋 Action : {signal['action']}

📍 Entrée : {signal['entry']:.5f}
🛑 SL : {signal['sl']:.5f} (-{risk:.1f} pips)

{tp_lines}

💪 ADX : {signal['adx']:.1f}
📊 RSI : {signal['rsi']:.1f}
📈 Ratio R/R minimum : 1:{ratio:.1f}
"""

def send_telegram_message(message: str) -> bool:
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     json={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=30, verify=False)
        return True
    except: return False

# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

async def main():
    print("🐐 FIBONACCI GOAT - STRATÉGIE KEN AHYEE")
    print("=" * 50)
    print(f"📊 {len(SYMBOLS)} actifs | Scan toutes les {SCAN_INTERVAL // 60} min")
    print("🎯 Modes : STANDARD (30-100 pips) | GÉANT (200-2000+ pips)")
    print("=" * 50)
    
    while True:
        STATS["scans"] += 1
        print(f"\n🕐 Scan #{STATS['scans']} - {datetime.now().strftime('%H:%M:%S')}")
        
        for symbol in SYMBOLS:
            for tf in ["H1", "H4"]:
                data = await fetch_ticks(symbol, tf)
                signal = analyze_goat(data, symbol, tf)
                if signal:
                    STATS["signals"] += 1
                    msg = format_goat_message(signal)
                    send_telegram_message(msg)
                    print(f"   ✅ Signal {signal['setup']} sur {signal['full_name']}")
                await asyncio.sleep(1)
        
        print(f"   📊 Total signaux : {STATS['signals']}")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
