#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONFLUENCE 3.0 - Système de Trading Algorithmique
Bot de scan multi-actifs pour Deriv avec analyse multi-timeframe et score de confluence
Version : 3.0 Finale
Fichier : ultime-v5-bot
"""

import asyncio
import json
import websockets
import aiohttp
import time
import os
import ssl
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

# ============================================================
# CONFIGURATION CENTRALISÉE
# ============================================================

TELEGRAM_TOKEN = "8649949649:AAGCngwn-mYUfcdI-KYbeBdQTvgiiI0gD_A"
TELEGRAM_CHAT_ID = "8400153330"
DERIV_APP_ID = "36544"

# Capital et risque (modifiables)
CAPITAL = float(os.environ.get("TRADING_CAPITAL", "1000.0"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.0"))  # 1% par défaut

# Liste des actifs à scanner
SYMBOLS = [
    # Indices Synthétiques Deriv
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "CRASH500", "CRASH1000", "BOOM500", "BOOM1000",
    # Forex Majors
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
    # Forex Crosses
    "EURGBP", "EURJPY", "GBPJPY",
    # Métaux
    "GOLD", "SILVER",
    # Crypto
    "BTCUSD", "ETHUSD",
    # Indices Boursiers
    "US500", "US100", "GER40"
]

FULL_NAMES = {
    "R_10": "Volatility 10 Index", "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index", "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
    "CRASH500": "Crash 500 Index", "CRASH1000": "Crash 1000 Index",
    "BOOM500": "Boom 500 Index", "BOOM1000": "Boom 1000 Index",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
    "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY",
    "GOLD": "Or (XAU/USD)", "SILVER": "Argent (XAG/USD)",
    "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum",
    "US500": "S&P 500", "US100": "Nasdaq 100", "GER40": "DAX 40"
}

# Types d'actifs pour filtres spécifiques
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

SCAN_INTERVAL = 300  # 5 minutes
JOURNAL_FILE = "confluence_v3_journal.csv"

STATS = {
    "scans": 0,
    "signals_premium": 0,
    "signals_standard": 0,
    "total_signals": 0
}

# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def get_full_name(symbol: str) -> str:
    return FULL_NAMES.get(symbol, symbol)

def get_asset_type(symbol: str) -> str:
    return ASSET_TYPES.get(symbol, "unknown")

# ============================================================
# INDICATEURS TECHNIQUES (CORRIGÉS)
# ============================================================

def calculate_ema(data: List[float], period: int) -> float:
    """Calcule l'EMA sur une liste de prix"""
    if len(data) < period:
        return data[-1] if data else 0.0
    multiplier = 2.0 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """Calcule le RSI correctement"""
    if len(closes) < period + 1:
        return 50.0
    
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def calculate_stoch_rsi(closes: List[float], period: int = 14, smooth_k: int = 3) -> Tuple[float, float]:
    """
    VRAI Stochastique RSI (formule corrigée)
    Stoch RSI = (RSI - min_RSI) / (max_RSI - min_RSI)
    Retourne (stoch_k, stoch_d)
    """
    if len(closes) < period + smooth_k:
        return 50.0, 50.0
    
    # Calculer les RSI sur la période
    rsi_values = []
    for i in range(period, len(closes) + 1):
        window = closes[max(0, i-period):i]
        if len(window) >= period:
            rsi = calculate_rsi(window, period)
            rsi_values.append(rsi)
    
    if len(rsi_values) < period:
        return 50.0, 50.0
    
    # Stoch RSI = (RSI - min) / (max - min) * 100
    min_rsi = min(rsi_values[-period:])
    max_rsi = max(rsi_values[-period:])
    
    if max_rsi - min_rsi == 0:
        return 50.0, 50.0
    
    stoch_k = ((rsi_values[-1] - min_rsi) / (max_rsi - min_rsi)) * 100.0
    
    # Stoch D = SMA de Stoch K
    if len(rsi_values) >= smooth_k:
        recent_stoch = []
        for i in range(-smooth_k, 0):
            min_r = min(rsi_values[i-period:i] if i-period >= 0 else rsi_values[:i])
            max_r = max(rsi_values[i-period:i] if i-period >= 0 else rsi_values[:i])
            if max_r - min_r > 0:
                recent_stoch.append(((rsi_values[i] - min_r) / (max_r - min_r)) * 100)
        stoch_d = sum(recent_stoch) / len(recent_stoch) if recent_stoch else stoch_k
    else:
        stoch_d = stoch_k
    
    return stoch_k, stoch_d

def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Tuple[float, float, float]:
    """
    Calcule l'ADX correctement
    Retourne (adx, plus_di, minus_di)
    """
    if len(highs) < period + 1:
        return 15.0, 0.0, 0.0
    
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    
    for i in range(1, len(highs)):
        # CORRECTION BUG ATR : closes[i-1] (PAS lows[i-1])
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
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
                dx = abs(p_di - m_di) / (p_di + m_di) * 100.0
                dx_sum += dx
    
    adx = dx_sum / period if period > 0 else 0.0
    
    return adx, plus_di, minus_di

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """
    Calcule l'ATR avec la formule CORRIGÉE
    """
    if len(highs) < period + 1:
        return 0.0
    
    tr_list = []
    for i in range(1, len(highs)):
        # CORRECTION : closes[i-1] (PAS lows[i-1])
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    
    return sum(tr_list[-period:]) / period

def calculate_macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    """
    Calcule le MACD
    Retourne (macd_line, signal_line, histogram)
    """
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    
    ema_fast = calculate_ema(closes, fast)
    
    # Calculer EMA slow sur les mêmes données
    ema_slow = calculate_ema(closes, slow)
    
    macd_line = ema_fast - ema_slow
    
    # Pour la ligne de signal, on aurait besoin de l'historique MACD
    # Simplification pour ce bot
    signal_line = macd_line * 0.5  # Approximation
    
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

def detect_swings(highs: List[float], lows: List[float], window: int = 5) -> Tuple[List[float], List[float]]:
    """
    Détecte les pivots hauts et bas réels (swings)
    """
    swing_highs, swing_lows = [], []
    
    for i in range(window, len(highs) - window):
        # Pivot haut
        if highs[i] == max(highs[i-window:i+window+1]):
            swing_highs.append(highs[i])
        
        # Pivot bas
        if lows[i] == min(lows[i-window:i+window+1]):
            swing_lows.append(lows[i])
    
    return swing_highs, swing_lows

# ============================================================
# FIBONACCI AUTOMATIQUE (Ancré sur swings H1)
# ============================================================

def calculate_fibonacci_levels(high: float, low: float, is_uptrend: bool = True) -> Dict[str, float]:
    """
    Calcule les niveaux Fibonacci retracement et extension
    Ancré sur les vrais swings
    """
    diff = high - low
    
    if is_uptrend:
        # Tendance haussière : retracements depuis le haut
        return {
            "0.0": high,
            "0.236": high - diff * 0.236,
            "0.382": high - diff * 0.382,
            "0.5": high - diff * 0.5,
            "0.618": high - diff * 0.618,
            "0.786": high - diff * 0.786,
            "1.0": low,
            # Extensions
            "-0.272": high + diff * 0.272,
            "-0.618": high + diff * 0.618,
            "-1.0": high + diff * 1.0,
            "-1.618": high + diff * 1.618
        }
    else:
        # Tendance baissière : retracements depuis le bas
        return {
            "0.0": low,
            "0.236": low + diff * 0.236,
            "0.382": low + diff * 0.382,
            "0.5": low + diff * 0.5,
            "0.618": low + diff * 0.618,
            "0.786": low + diff * 0.786,
            "1.0": high,
            # Extensions
            "-0.272": low - diff * 0.272,
            "-0.618": low - diff * 0.618,
            "-1.0": low - diff * 1.0,
            "-1.618": low - diff * 1.618
        }

def is_price_in_fibo_zone(price: float, fibo_level: float, tolerance: float = 0.005) -> bool:
    """
    Vérifie si le prix est dans une zone Fibonacci
    """
    return abs(price - fibo_level) / fibo_level < tolerance

def select_auto_entry_level(fibo_levels: Dict[str, float], current_price: float, is_buy: bool) -> float:
    """
    Sélectionne automatiquement le niveau d'entrée Fibonacci
    """
    if is_buy:
        # Pour BUY : chercher le niveau de retracement le plus proche sous le prix
        levels = [fibo_levels[k] for k in ["0.382", "0.5", "0.618", "0.786"]]
        levels = [l for l in levels if l < current_price]
        return max(levels) if levels else fibo_levels["0.618"]
    else:
        # Pour SELL : chercher le niveau de retracement le plus proche au-dessus du prix
        levels = [fibo_levels[k] for k in ["0.382", "0.5", "0.618", "0.786"]]
        levels = [l for l in levels if l > current_price]
        return min(levels) if levels else fibo_levels["0.618"]

def select_auto_tp_level(fibo_levels: Dict[str, float], adx: float, is_buy: bool) -> Tuple[float, str]:
    """
    Sélectionne automatiquement le niveau de TP basé sur Fibonacci et ADX
    """
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
    """
    Vérifie si le marché est ouvert selon le type d'actif
    """
    now = datetime.utcnow()
    hour = now.hour
    weekday = now.weekday()  # 0 = Lundi
    
    if asset_type == "forex":
        # Forex : fermé du vendredi 22h au dimanche 22h UTC
        if weekday == 4 and hour >= 22:
            return False
        if weekday == 5:
            return False
        if weekday == 6 and hour < 22:
            return False
        return True
    
    elif asset_type == "indices":
        # Indices : fermé le weekend
        if weekday >= 5:
            return False
        return True
    
    elif asset_type == "crypto":
        # Crypto : toujours ouvert
        return True
    
    elif asset_type in ["synthetic", "crash_boom"]:
        # Synthétiques Deriv : toujours ouvert
        return True
    
    return True

def apply_asset_filters(symbol: str, signal_data: Dict) -> Tuple[bool, int]:
    """
    Applique les filtres spécifiques par type d'actif
    Retourne (valide, bonus_score)
    """
    asset_type = get_asset_type(symbol)
    bonus = 0
    
    if asset_type == "synthetic":
        # Synthétiques : momentum pure, ATR relatif
        if signal_data.get('adx', 0) < 20:
            return False, 0
        bonus = 5  # Bonus pour forte tendance
    
    elif asset_type == "crash_boom":
        # Crash/Boom : direction unique
        is_crash = "CRASH" in symbol
        is_buy = "ACHAT" in signal_data.get('action', '')
        
        if is_crash and not is_buy:
            # Crash : on trade SELL
            bonus = 10
        elif not is_crash and is_buy:
            # Boom : on trade BUY
            bonus = 10
        else:
            return False, 0
    
    elif asset_type == "forex":
        # Forex : filtre horaire
        if not is_market_open("forex"):
            return False, 0
        bonus = 0
    
    elif asset_type == "crypto":
        # Crypto : volatilité élevée
        if signal_data.get('atr_ratio', 1.0) < 1.5:
            return False, 0
        bonus = 5  # Bonus volatilité
    
    elif asset_type == "indices":
        # Indices : session obligatoire
        if not is_market_open("indices"):
            return False, 0
        bonus = 0
    
    return True, bonus

# ============================================================
# SCORE DE CONFLUENCE (130 pts max)
# ============================================================

def calculate_confluence_score(signal_data: Dict, fibo_bonus: int = 0, asset_bonus: int = 0) -> int:
    """
    Calcule le score de confluence final
    Maximum : 130 points
    """
    score = 0
    
    # 1. Alignement Multi-TF (20 pts)
    if signal_data.get('trend_h1', False) and signal_data.get('trend_m15', False):
        score += 20
    elif signal_data.get('trend_h1', False):
        score += 10
    
    # 2. Prix dans zone Fibonacci (15 pts)
    if signal_data.get('in_fibo_zone', False):
        score += 15
    
    # 3. ADX ≥ 25 (15 pts)
    adx = signal_data.get('adx', 0)
    if adx >= 40:
        score += 15
    elif adx >= 30:
        score += 12
    elif adx >= 25:
        score += 10
    
    # 4. RSI en zone extrême (15 pts)
    rsi = signal_data.get('rsi', 50)
    if rsi < 25 or rsi > 75:
        score += 15
    elif rsi < 30 or rsi > 70:
        score += 10
    
    # 5. Stoch RSI confirmé (10 pts)
    stoch_k = signal_data.get('stoch_k', 50)
    if stoch_k < 15 or stoch_k > 85:
        score += 10
    elif stoch_k < 20 or stoch_k > 80:
        score += 5
    
    # 6. MACD aligné (10 pts)
    if signal_data.get('macd_aligned', False):
        score += 10
    
    # 7. Volume confirmé (5 pts)
    if signal_data.get('volume_valid', False):
        score += 5
    
    # 8. Bonus Fibonacci + EMA (15 pts)
    score += fibo_bonus
    
    # 9. Bonus spécifique actif
    score += asset_bonus
    
    # 10. Bonus Divergence MACD (10 pts)
    if signal_data.get('macd_divergence', False):
        score += 10
    
    return min(score, 130)

def get_signal_quality(score: int) -> str:
    """Détermine la qualité du signal basée sur le score"""
    if score >= 85:
        return "PREMIUM 🏆"
    elif score >= 70:
        return "STANDARD ✅"
    else:
        return "FAIBLE ⚠️"

# ============================================================
# GESTION DU RISQUE
# ============================================================

def calculate_position_size(capital: float, risk_percent: float, entry: float, stop_loss: float) -> float:
    """
    Calcule la taille de position basée sur le risque
    Formule : Taille = (Capital × Risque%) / Distance_SL
    """
    risk_amount = capital * (risk_percent / 100.0)
    sl_distance = abs(entry - stop_loss)
    
    if sl_distance == 0:
        return 0.0
    
    position_size = risk_amount / sl_distance
    return round(position_size, 2)

# ============================================================
# ANALYSE D'UN ACTIF
# ============================================================

async def fetch_ticks(symbol: str, granularity: int = 300, count: int = 100) -> Dict:
    """Récupère les ticks depuis Deriv"""
    url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
            request = {
                "ticks_history": symbol,
                "granularity": granularity,
                "count": count,
                "style": "candles",
                "end": "latest"
            }
            await ws.send(json.dumps(request))
            response = await asyncio.wait_for(ws.recv(), timeout=30.0)
            data = json.loads(response)
            
            if 'error' in data:
                return {'error': data['error']['message'], 'symbol': symbol}
            if 'candles' not in data:
                return {'error': 'Missing candles', 'symbol': symbol}
            
            return data
    except Exception as e:
        return {'error': str(e), 'symbol': symbol}

def analyze_symbol(data: Dict, symbol: str) -> Optional[Dict]:
    """
    Analyse un actif selon la méthodologie CONFLUENCE 3.0
    """
    if 'error' in data:
        return None
    
    candles = data.get('candles', [])
    if len(candles) < 60:
        return None
    
    # Extraction des données
    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    closes = [float(c['close']) for c in candles]
    volumes = [float(c.get('volume', 0)) for c in candles]
    
    current_price = closes[-1]
    
    # Détection des swings (structure)
    swing_highs, swing_lows = detect_swings(highs, lows, window=5)
    
    if not swing_highs or not swing_lows:
        return None
    
    recent_high = max(swing_highs[-3:]) if len(swing_highs) >= 3 else max(highs)
    recent_low = min(swing_lows[-3:]) if len(swing_lows) >= 3 else min(lows)
    
    # Détermination de la tendance
    is_uptrend = closes[-1] > closes[-20]  # Simplifié
    
    # Fibonacci ancré sur les vrais swings
    fibo_levels = calculate_fibonacci_levels(recent_high, recent_low, is_uptrend)
    
    # Vérification zone Fibonacci
    fibo_618 = fibo_levels["0.618"]
    in_fibo_zone = is_price_in_fibo_zone(current_price, fibo_618)
    
    # Indicateurs techniques (CORRIGÉS)
    rsi = calculate_rsi(closes, 14)
    stoch_k, stoch_d = calculate_stoch_rsi(closes, 14)
    adx, plus_di, minus_di = calculate_adx(highs, lows, closes, 14)
    atr = calculate_atr(highs, lows, closes, 14)
    macd, macd_signal, macd_hist = calculate_macd(closes)
    
    # EMA
    ema_50 = calculate_ema(closes, 50)
    ema_20 = calculate_ema(closes[-30:], 20) if len(closes) >= 30 else ema_50
    
    # Volume
    avg_volume = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
    volume_valid = volumes[-1] > avg_volume * 1.5 if avg_volume > 0 else True
    
    # Conditions de signal
    trend_aligned = (current_price > ema_20 and current_price > ema_50) or (current_price < ema_20 and current_price < ema_50)
    strong_trend = adx >= 25
    stoch_extreme = stoch_k < 20 or stoch_k > 80
    rsi_extreme = rsi < 30 or rsi > 70
    macd_aligned = (macd_hist > 0 and is_uptrend) or (macd_hist < 0 and not is_uptrend)
    
    # Détermination action
    if is_uptrend and stoch_k < 20 and rsi < 40 and in_fibo_zone:
        action = "ACHAT (BUY) 🟢"
        sl_price = current_price - atr * 1.5
        tp_price, tp_label = select_auto_tp_level(fibo_levels, adx, True)
        stoch_status = "SURVENDU"
    elif not is_uptrend and stoch_k > 80 and rsi > 60 and in_fibo_zone:
        action = "VENTE (SELL) 🔴"
        sl_price = current_price + atr * 1.5
        tp_price, tp_label = select_auto_tp_level(fibo_levels, adx, False)
        stoch_status = "SURACHETÉ"
    else:
        return None
    
    # Construction signal_data
    signal_data = {
        'symbol': symbol,
        'full_name': get_full_name(symbol),
        'action': action,
        'current_price': current_price,
        'fibo_618': fibo_618,
        'in_fibo_zone': in_fibo_zone,
        'adx': adx,
        'plus_di': plus_di,
        'minus_di': minus_di,
        'rsi': rsi,
        'stoch_k': stoch_k,
        'stoch_d': stoch_d,
        'stoch_status': stoch_status,
        'ema_20': ema_20,
        'ema_50': ema_50,
        'atr': atr,
        'sl_price': sl_price,
        'tp_price': tp_price,
        'tp_label': tp_label,
        'trend_h1': is_uptrend,
        'trend_m15': trend_aligned,
        'macd_aligned': macd_aligned,
        'macd_divergence': False,  # À implémenter
        'volume_valid': volume_valid,
        'ratio': abs(current_price - tp_price) / abs(current_price - sl_price) if sl_price != current_price else 0
    }
    
    # Filtres spécifiques par actif
    valid, asset_bonus = apply_asset_filters(symbol, signal_data)
    if not valid:
        return None
    
    # Bonus Fibonacci + EMA
    fibo_bonus = 0
    if in_fibo_zone and abs(current_price - ema_50) / ema_50 < 0.01:
        fibo_bonus = 15
    
    # Score de confluence
    score = calculate_confluence_score(signal_data, fibo_bonus, asset_bonus)
    quality = get_signal_quality(score)
    
    if score < 70:
        return None
    
    # Calcul taille de position
    position_size = calculate_position_size(CAPITAL, RISK_PERCENT, current_price, sl_price)
    
    signal_data['score'] = score
    signal_data['quality'] = quality
    signal_data['position_size'] = position_size
    
    return signal_data

# ============================================================
# SCAN PARALLÈLE
# ============================================================

async def scan_all_symbols_parallel(symbols: List[str]) -> List[Dict]:
    """
    Scan tous les actifs en PARALLÈLE avec asyncio.gather()
    """
    print(f"\n🔎 Scan parallèle de {len(symbols)} actifs...")
    
    # Récupération simultanée de toutes les données
    tasks = [fetch_ticks(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    signals = []
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            print(f"   ❌ {get_full_name(symbol)} : Erreur connexion")
            continue
        
        if isinstance(result, dict):
            signal = analyze_symbol(result, symbol)
            if signal:
                signals.append(signal)
                print(f"   ✅ {signal['full_name']} - Score: {signal['score']}/130 - {signal['quality']}")
                
                # Sauvegarde dans le journal
                save_to_journal(signal)
                
                # Envoi Telegram
                message = format_signal_message(signal)
                asyncio.create_task(send_telegram_message(message))
            else:
                print(f"   ◻️ {get_full_name(symbol)} : Pas de signal")
    
    return signals

# ============================================================
# JOURNAL ET NOTIFICATIONS
# ============================================================

def save_to_journal(signal_data: Dict):
    """Sauvegarde un signal dans le journal CSV"""
    file_exists = os.path.isfile(JOURNAL_FILE)
    
    with open(JOURNAL_FILE, 'a', encoding='utf-8') as f:
        if not file_exists:
            f.write("timestamp,symbol,quality,action,entry,sl,tp,ratio,adx,rsi,stoch,score,position_size\n")
        
        line = (
            f"{datetime.now().isoformat()},"
            f"{signal_data['symbol']},"
            f"{signal_data['quality']},"
            f"{signal_data['action']},"
            f"{signal_data['current_price']:.5f},"
            f"{signal_data['sl_price']:.5f},"
            f"{signal_data['tp_price']:.5f},"
            f"{signal_data['ratio']:.2f},"
            f"{signal_data['adx']:.1f},"
            f"{signal_data['rsi']:.1f},"
            f"{signal_data['stoch_k']:.1f},"
            f"{signal_data['score']},"
            f"{signal_data['position_size']}\n"
        )
        f.write(line)
    
    print(f"📝 Signal sauvegardé dans {JOURNAL_FILE}")

async def send_telegram_message(message: str) -> bool:
    """
    Envoie un message Telegram avec aiohttp (SSL ACTIVÉ)
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=30) as response:
                if response.status == 200:
                    print("✅ Message Telegram envoyé")
                    return True
                else:
                    print(f"⚠️ Erreur Telegram: {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Erreur envoi Telegram: {e}")
        return False

def format_signal_message(signal: Dict) -> str:
    """Formate un message pour Telegram"""
    quality_emoji = "🏆" if "PREMIUM" in signal['quality'] else "✅"
    
    return f"""
{quality_emoji} SIGNAL CONFLUENCE 3.0 - {signal['quality']}

📊 Actif : {signal['full_name']}
📋 Action : {signal['action']}
⭐ Score : {signal['score']}/130

📍 Entrée : {signal['current_price']:.5f}
🎯 Zone Fibo 0.618 : {signal['fibo_618']:.5f}
💪 ADX : {signal['adx']:.1f}
📊 RSI : {signal['rsi']:.1f}
⚡ Stoch RSI : {signal['stoch_k']:.1f} ({signal['stoch_status']})

🛑
