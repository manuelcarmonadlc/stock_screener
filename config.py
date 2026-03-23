"""
=============================================================================
 CONFIGURACIÓN DEL SCREENER - Stock Opportunity Finder v1
=============================================================================
 Estrategia: Detectar empresas sólidas (tipo buy&hold con dividendos)
 que están temporalmente infravaloradas, con confirmación técnica.
 
 Inspirado en la estrategia de medio plazo de Gregorio Hernández Jiménez.
=============================================================================
"""

# ---------------------------------------------------------------------------
# 1. UNIVERSO DE MERCADOS
# ---------------------------------------------------------------------------
# Cada mercado es un dict con nombre y lista de tickers (formato yfinance).
# Para añadir/quitar empresas, simplemente edita las listas.
# Sufijos yfinance: .MC (Madrid), .PA (París), .DE (Frankfurt), .AS (Amsterdam),
#   .MI (Milán), .BR (Bruselas), .LS (Lisboa), .HE (Helsinki),
#   .AX (Australia), .T (Tokio), .HK (Hong Kong), .KS (Corea)

MARKETS = {
    # ── EUROSTOXX / Principales europeas ────────────────────────────────
    "EUROSTOXX": [
        # Alemania (DAX)
        "ALV.DE", "BAS.DE", "BAYN.DE", "BMW.DE", "CON.DE",
        "DTE.DE", "EOAN.DE", "FRE.DE", "HEN3.DE", "SIE.DE", "VOW3.DE",
        "MUV2.DE", "SAP.DE", "ADS.DE", "DB1.DE", "DBK.DE",
        "RWE.DE", "HEI.DE", "BEI.DE", "LIN.DE",
        # Francia (CAC 40)
        "AI.PA", "AIR.PA", "BN.PA", "BNP.PA", "CA.PA", "CAP.PA",
        "CS.PA", "DG.PA", "EL.PA", "EN.PA", "GLE.PA", "KER.PA",
        "LR.PA", "MC.PA", "ML.PA", "OR.PA", "ORA.PA", "RI.PA",
        "SAN.PA", "SGO.PA", "SU.PA", "TTE.PA", "VIE.PA", "VIV.PA",
        "ACA.PA", "DSY.PA", "PUB.PA", "RNO.PA",
        # Holanda
        "ASML.AS", "HEIA.AS", "INGA.AS", "KPN.AS", "PHIA.AS",
        "REN.AS", "UNA.AS", "WKL.AS", "AD.AS",
        # Italia
        "ENEL.MI", "ENI.MI", "ISP.MI", "G.MI", "UCG.MI", "SRG.MI",
        "TIT.MI", "TEN.MI", "PRY.MI", "RACE.MI",
        # Bélgica
        "ABI.BR", "UCB.BR", "SOLB.BR", "KBC.BR",
        # Portugal
        "EDP.LS", "GALP.LS", "SON.LS",
        # Finlandia
        "FORTUM.HE", "NESTE.HE", "NOKIA.HE",
        # Suiza (extra-UE pero relevante)
        "NESN.SW", "NOVN.SW", "ROG.SW", "UBSG.SW", "ZURN.SW",
        # UK (post-Brexit pero relevante)
        "SHEL.L", "BP.L", "GSK.L", "AZN.L", "ULVR.L", "HSBA.L",
        "LLOY.L", "BARC.L", "RIO.L", "BHP.L", "VOD.L", "NG.L",
        "SSE.L", "BA.L", "DGE.L", "BATS.L", "IMB.L", "LSEG.L",
    ],

    # ── S&P 500 principales (Dividend Aristocrats + Value) ──────────────
    "SP500": [
        # Dividend Aristocrats / Kings
        "JNJ", "PG", "KO", "PEP", "MMM", "ABT", "ABBV", "T", "VZ",
        "XOM", "CVX", "CL", "EMR", "GPC", "SWK", "ITW", "ADP", "BDX",
        "ED", "LOW", "TGT", "MCD", "AFL", "CB", "SHW",
        # Grandes value / dividendo
        "JPM", "BAC", "WFC", "C", "GS", "MS", "BRK-B", "UNH",
        "HD", "WMT", "COST", "CSCO", "INTC", "IBM", "CAT", "DE",
        "UPS", "FDX", "RTX", "LMT", "GD", "BA",
        "PFE", "MRK", "BMY", "AMGN", "GILD",
        "DUK", "SO", "NEE", "AEP", "D", "SRE",
        "O", "SPG", "AMT", "PSA",  # REITs
        "PM", "MO", "KMB", "HRL", "SJM", "GIS", "CPB",
        "F", "GM", "IP", "WY",
        # Tech value (cuando caen)
        "AAPL", "MSFT", "GOOG", "META", "AVGO", "TXN", "QCOM",
    ],

    # ── ASX (Australia) ─────────────────────────────────────────────────
    "ASX": [
        "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX",
        "MQG.AX", "WES.AX", "WOW.AX", "TLS.AX", "RIO.AX", "FMG.AX",
        "TCL.AX", "COL.AX", "STO.AX", "WDS.AX", "AMC.AX", "QBE.AX",
        "SUN.AX", "IAG.AX", "ORG.AX", "APA.AX", "GPT.AX", "SCG.AX",
        "MGR.AX", "VCX.AX", "TWE.AX", "BEN.AX", "BOQ.AX",
    ],

    # ── Asia ─────────────────────────────────────────────────────────────
    "ASIA": [
        # Japón (Nikkei - principales dividend payers)
        "7203.T", "8306.T", "8316.T", "8411.T", "9432.T", "9433.T",
        "9434.T", "4502.T", "4503.T", "4568.T", "6758.T", "6861.T",
        "7267.T", "7751.T", "8031.T", "8058.T", "8766.T", "9020.T",
        "9021.T", "9022.T", "2914.T", "3382.T", "8001.T", "8002.T",
        # Hong Kong
        "0005.HK", "0016.HK", "0002.HK", "0003.HK",
        "0006.HK", "0012.HK", "0019.HK", "0066.HK", "0083.HK",
        "0388.HK", "0700.HK", "0941.HK", "1038.HK", "1299.HK",
        # Corea del Sur
        "005930.KS", "000660.KS", "051910.KS", "035420.KS",
        "005380.KS", "055550.KS", "105560.KS",
        # Singapur
        "D05.SI", "O39.SI", "U11.SI", "Z74.SI", "C6L.SI",
    ],
}

# Selecciona qué mercados escanear (comenta/descomenta según necesites)
ACTIVE_MARKETS = [
    "EUROSTOXX",
    "SP500",
    "ASX",
    "ASIA",
]

# Mercados para pruebas rapidas. Mantener pequeno para smoke tests.
QUICK_MARKETS = [
    "ASX",
]


# ---------------------------------------------------------------------------
# 2. FILTROS FUNDAMENTALES (Capa 1: Calidad / Solidez)
# ---------------------------------------------------------------------------
# IMPORTANTE: Esta estrategia busca empresas que ERAN sólidas y están en un
# bache temporal. Por tanto distinguimos entre:
#   - HISTORIAL: ¿era una buena empresa antes del problema? (lo que importa)
#   - SITUACIÓN ACTUAL: puede estar deteriorada temporalmente (aceptable)
#
# Una empresa que ha recortado o suspendido dividendo NO se descarta
# automáticamente si tiene historial de haberlo pagado durante años.
# De hecho, un recorte de dividendo reciente puede ser PARTE de la caída
# que genera la oportunidad.

FUNDAMENTAL = {
    # ── HISTORIAL DE DIVIDENDOS (lo que importa) ──
    # ¿Pagaba dividendo de forma consistente ANTES del problema?
    "min_historical_div_years": 5,      # Años con dividendo en los últimos 10 (no consecutivos)
    # Ejemplo: si pagó 7 de 10 años, cumple. Permite huecos recientes.

    "min_peak_dividend_yield": 2.0,     # % yield máximo alcanzado en últimos 5 años
    # Demuestra que la empresa SÍ era generosa con el accionista.

    # ── DIVIDENDO ACTUAL (flexible) ──
    # El dividendo actual puede estar reducido o ser cero.
    # En vez de exigir un mínimo, damos BONUS si aún lo paga:
    "current_div_bonus_threshold": 1.0, # Si yield actual ≥ este %, bonus de puntuación
    # Si es 0% o bajo, no penaliza (la empresa puede haberlo cortado temporalmente)

    "max_payout_ratio": 90.0,           # % máximo de payout (por encima, riesgo de corte futuro)
    # Solo aplica si hay payout; si no paga dividendo actual, se ignora.

    # ── DEUDA ──
    "max_debt_to_equity": 2.0,          # Ratio deuda/equity máximo
    "max_net_debt_ebitda": 4.0,         # Deuda neta / EBITDA normalizado máximo
    # Nota: bancos y utilities se ajustan en SECTOR_OVERRIDES

    # ── RENTABILIDAD ──
    "min_roe": 8.0,                     # % ROE mínimo (puede relajarse si el problema es temporal)
    "roe_soft_floor": 3.0,             # % ROE mínimo absoluto — por debajo, descarte
    # Entre soft_floor y min_roe: puntuación reducida pero no eliminatoria

    "min_positive_earnings_years": 3,   # De los últimos 4 años, al menos X con beneficio

    # ── TAMAÑO MÍNIMO ──
    "min_market_cap_millions": 500,     # Capitalización mínima en millones USD/EUR
    "min_avg_daily_volume": 100000,     # Liquidez media diaria mínima
}


# ---------------------------------------------------------------------------
# 3. FILTROS DE VALORACIÓN (Capa 2: Infravaloración temporal)
# ---------------------------------------------------------------------------
VALUATION = {
    # PER
    "max_per": 18.0,                    # PER máximo absoluto
    "per_discount_vs_historical": 25.0, # % de descuento del PER actual vs media 5 años
    # Ejemplo: si media histórica es 16 y actual es 12, descuento = 25%

    # Rentabilidad por dividendo
    "div_yield_premium_vs_historical": 20.0,
    # % de prima del yield actual vs media 5 años
    # Si media es 3% y actual es 3.6%, prima = 20%

    # Precio
    "min_drop_from_52w_high": 15.0,     # % mínimo de caída desde máximo 52 semanas
    "max_drop_from_52w_high": 60.0,     # % máximo (más de esto puede ser problema real)

    # Price to Book (opcional, 0 para desactivar)
    "max_price_to_book": 3.0,           # P/B máximo
    "max_ev_ebitda": 12.0,              # EV/EBITDA máximo
}


# ---------------------------------------------------------------------------
# 4. FILTROS TÉCNICOS (Capa 3: Timing / Señal de entrada)
# ---------------------------------------------------------------------------
TECHNICAL = {
    # RSI
    "rsi_period": 14,
    "rsi_oversold": 35,                 # RSI por debajo = sobreventa
    "rsi_recovery_zone": 45,            # RSI entre oversold y este valor = recuperándose
    # Buscamos RSI < recovery_zone (idealmente saliendo de oversold)
    "rsi_divergence_min_window": 20,    # Distancia mínima entre mínimos para divergencia
    "rsi_divergence_max_window": 60,    # Distancia máxima entre mínimos para divergencia
    "rsi_divergence_bonus_points": 10,  # Bonus técnico si hay divergencia alcista válida

    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # Señal: MACD cruzando al alza la línea de señal, o histograma girando

    # Medias móviles
    "sma_short": 50,
    "sma_long": 200,
    # Señal: precio acercándose a SMA200 desde abajo, o SMA50 girando al alza

    # Volumen
    "volume_increase_threshold": 1.3,   # Volumen actual vs media 20 sesiones
    # Volumen creciente en rebote confirma interés comprador

    # Soportes
    "support_proximity_pct": 5.0,       # % de cercanía al soporte para considerarlo "en zona"
    "support_lookback_days": 120,       # Días hacia atrás para calcular soportes

    # Periodo de datos históricos para análisis técnico
    "history_period": "2y",             # Datos de los últimos 2 años
}


# ---------------------------------------------------------------------------
# 5. SCORING (Ponderación de cada capa)
# ---------------------------------------------------------------------------
SCORING = {
    "weight_fundamental": 0.35,         # 35% del score final
    "weight_valuation": 0.40,           # 40% - lo más importante para esta estrategia
    "weight_technical": 0.25,           # 25% - confirmación de timing

    "min_total_score": 55,              # Score mínimo (0-100) para aparecer en resultados
}


# ---------------------------------------------------------------------------
# 5.1 VERSIONADO DE EVALUACIONES
# ---------------------------------------------------------------------------
VERSIONING = {
    "rules_version": "1.0",
    "model_version": "script-v2.0",
    "config_version": "1.0",
}


# ---------------------------------------------------------------------------
# 6. AJUSTES POR SECTOR
# ---------------------------------------------------------------------------
# Algunos sectores tienen métricas inherentemente distintas.
# Estos overrides se aplican cuando se detecta el sector.
SECTOR_OVERRIDES = {
    "Financial Services": {
        "max_debt_to_equity": 8.0,      # Bancos tienen D/E muy alto por naturaleza
        "max_net_debt_ebitda": None,    # Ignorar para bancos/aseguradoras
        "max_price_to_book": 1.5,       # P/B más exigente para bancos
        "min_roe": 6.0,
    },
    "Utilities": {
        "max_debt_to_equity": 3.5,
        "max_net_debt_ebitda": 5.0,
        "max_per": 22.0,                # Utilities suelen cotizar con PER más alto
    },
    "Real Estate": {
        "max_debt_to_equity": 4.0,
        "max_per": 25.0,                # REITs usan FFO, PER es menos relevante
        "min_dividend_yield": 3.0,
    },
    "Energy": {
        "max_per": 14.0,                # Sector cíclico, PER bajo es normal
    },
}


# ---------------------------------------------------------------------------
# 7. OUTPUT
# ---------------------------------------------------------------------------
OUTPUT = {
    "results_dir": "results",
    "export_xlsx": True,                # Exportar a Excel
    "export_csv": True,                 # Exportar a CSV
    "top_n_results": 50,                # Mostrar top N resultados
    "include_failed_tickers": False,    # Incluir log de tickers que fallaron
}


# ---------------------------------------------------------------------------
# 8. EJECUCIÓN
# ---------------------------------------------------------------------------
EXECUTION = {
    "max_workers": 4,                   # Hilos paralelos para descarga de datos
    "request_delay": 0.2,               # Segundos entre requests (evitar rate limit)
    "cache_expiry_hours": 12,           # Horas de validez del caché local
    "retry_attempts": 2,                # Reintentos por ticker fallido
}
