"""
=============================================================================
 CONFIGURACION DEL SCREENER - Stock Opportunity Finder v1
=============================================================================
 Estrategia: detectar empresas solidas (tipo buy&hold con dividendos)
 que estan temporalmente infravaloradas, con confirmacion tecnica.

 Inspirado en la estrategia de medio plazo de Gregorio Hernandez Jimenez.
=============================================================================
"""

# ---------------------------------------------------------------------------
# 1. UNIVERSO DE MERCADOS
# ---------------------------------------------------------------------------
# Cada mercado es un dict con nombre y lista de tickers en formato yfinance.
# Sufijos habituales:
#   .MC (Madrid), .PA (Paris), .DE (Frankfurt), .AS (Amsterdam),
#   .MI (Milan), .BR (Bruselas), .LS (Lisboa), .HE (Helsinki),
#   .AX (Australia), .T (Tokio), .HK (Hong Kong), .KS (Corea), .WA (Polonia)

MARKETS = {
    # EUROSTOXX / Principales europeas
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
        # Belgica
        "ABI.BR", "UCB.BR", "SOLB.BR", "KBC.BR",
        # Portugal
        "EDP.LS", "GALP.LS", "SON.LS",
        # Finlandia
        "FORTUM.HE", "NESTE.HE", "NOKIA.HE",
        # Suiza
        "NESN.SW", "NOVN.SW", "ROG.SW", "UBSG.SW", "ZURN.SW",
        # UK
        "SHEL.L", "BP.L", "GSK.L", "AZN.L", "ULVR.L", "HSBA.L",
        "LLOY.L", "BARC.L", "RIO.L", "BHP.L", "VOD.L", "NG.L",
        "SSE.L", "BA.L", "DGE.L", "BATS.L", "IMB.L", "LSEG.L",
    ],

    # S&P 500 principales (Dividend Aristocrats + Value)
    "SP500": [
        "JNJ", "PG", "KO", "PEP", "MMM", "ABT", "ABBV", "T", "VZ",
        "XOM", "CVX", "CL", "EMR", "GPC", "SWK", "ITW", "ADP", "BDX",
        "ED", "LOW", "TGT", "MCD", "AFL", "CB", "SHW",
        "JPM", "BAC", "WFC", "C", "GS", "MS", "BRK-B", "UNH",
        "HD", "WMT", "COST", "CSCO", "INTC", "IBM", "CAT", "DE",
        "UPS", "FDX", "RTX", "LMT", "GD", "BA",
        "PFE", "MRK", "BMY", "AMGN", "GILD",
        "DUK", "SO", "NEE", "AEP", "D", "SRE",
        "O", "SPG", "AMT", "PSA",
        "PM", "MO", "KMB", "HRL", "SJM", "GIS", "CPB",
        "F", "GM", "IP", "WY",
        "AAPL", "MSFT", "GOOG", "META", "AVGO", "TXN", "QCOM",
    ],

    # ASX (Australia)
    "ASX": [
        "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX",
        "MQG.AX", "WES.AX", "WOW.AX", "TLS.AX", "RIO.AX", "FMG.AX",
        "TCL.AX", "COL.AX", "STO.AX", "WDS.AX", "AMC.AX", "QBE.AX",
        "SUN.AX", "IAG.AX", "ORG.AX", "APA.AX", "GPT.AX", "SCG.AX",
        "MGR.AX", "VCX.AX", "TWE.AX", "BEN.AX", "BOQ.AX",
    ],

    # Italy mid/small caps (.MI) validadas con yfinance.info
    "ITALY_MID": [
        # Banca / seguros / finanzas
        "BMED.MI", "BGN.MI", "CE.MI", "FBK.MI", "PST.MI", "UNI.MI",
        "MB.MI", "AZM.MI",
        # Industrial / infraestructura
        "IP.MI", "REY.MI", "CRL.MI", "AMP.MI", "BZU.MI", "DAN.MI",
        "MAIRE.MI", "WBD.MI", "INW.MI",
        # Consumo / utilities
        "REC.MI", "DIA.MI", "HER.MI", "IRE.MI", "A2A.MI", "BPE.MI",
        "BC.MI", "MONC.MI", "IG.MI",
    ],

    # Poland / principales empresas (.WA) validadas con yfinance.info
    "POLAND": [
        # Banca / finanzas
        "PKO.WA", "PEO.WA", "SPL.WA", "PZU.WA",
        # Energia / materias primas
        "PKN.WA", "KGH.WA", "PGE.WA", "TPE.WA", "JSW.WA",
        # Consumo / tecnologia / otros
        "CDR.WA", "ALE.WA", "DNP.WA", "CPS.WA", "OPL.WA", "EAT.WA",
    ],

    # Asia
    "ASIA": [
        # Japon
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

# Mercados activos por defecto
ACTIVE_MARKETS = [
    "EUROSTOXX",
    "SP500",
    "ASX",
    "ITALY_MID",
    "POLAND",
    "ASIA",
]

# Mercados para pruebas rapidas. Mantener pequeno para smoke tests.
QUICK_MARKETS = [
    "ASX",
]


# ---------------------------------------------------------------------------
# 2. FILTROS FUNDAMENTALES (Capa 1: Calidad / Solidez)
# ---------------------------------------------------------------------------
FUNDAMENTAL = {
    # Historial de dividendos
    "min_historical_div_years": 5,
    "min_peak_dividend_yield": 2.0,

    # Dividendo actual
    "current_div_bonus_threshold": 1.0,
    "max_payout_ratio": 90.0,

    # Deuda
    "max_debt_to_equity": 2.0,
    "max_net_debt_ebitda": 4.0,

    # Rentabilidad
    "min_roe": 8.0,
    "roe_soft_floor": 3.0,
    "min_positive_earnings_years": 3,

    # Tamano minimo
    "min_market_cap_millions": 500,
    "min_avg_daily_volume": 100000,
}


# ---------------------------------------------------------------------------
# 3. FILTROS DE VALORACION
# ---------------------------------------------------------------------------
VALUATION = {
    "max_per": 18.0,
    "per_discount_vs_historical": 25.0,
    "div_yield_premium_vs_historical": 20.0,
    "min_drop_from_52w_high": 15.0,
    "max_drop_from_52w_high": 60.0,
    "max_price_to_book": 3.0,
    "max_ev_ebitda": 12.0,
}


# ---------------------------------------------------------------------------
# 4. FILTROS TECNICOS
# ---------------------------------------------------------------------------
TECHNICAL = {
    "rsi_period": 14,
    "rsi_oversold": 35,
    "rsi_recovery_zone": 45,
    "rsi_divergence_min_window": 20,
    "rsi_divergence_max_window": 60,
    "rsi_divergence_bonus_points": 10,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "sma_short": 50,
    "sma_long": 200,
    "volume_increase_threshold": 1.3,
    "support_proximity_pct": 5.0,
    "support_lookback_days": 120,
    "history_period": "2y",
}


# ---------------------------------------------------------------------------
# 5. SCORING
# ---------------------------------------------------------------------------
SCORING = {
    "weight_fundamental": 0.35,
    "weight_valuation": 0.40,
    "weight_technical": 0.25,
    "min_total_score": 55,
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
SECTOR_OVERRIDES = {
    "Financial Services": {
        "max_debt_to_equity": 8.0,
        "max_net_debt_ebitda": None,
        "max_price_to_book": 1.5,
        "min_roe": 6.0,
    },
    "Utilities": {
        "max_debt_to_equity": 3.5,
        "max_net_debt_ebitda": 5.0,
        "max_per": 22.0,
    },
    "Real Estate": {
        "max_debt_to_equity": 4.0,
        "max_per": 25.0,
        "min_dividend_yield": 3.0,
    },
    "Energy": {
        "max_per": 14.0,
    },
}


# ---------------------------------------------------------------------------
# 7. OUTPUT
# ---------------------------------------------------------------------------
OUTPUT = {
    "results_dir": "results",
    "export_xlsx": True,
    "export_csv": True,
    "top_n_results": 50,
    "include_failed_tickers": False,
}


# ---------------------------------------------------------------------------
# 8. EJECUCION
# ---------------------------------------------------------------------------
EXECUTION = {
    "max_workers": 4,
    "request_delay": 0.2,
    "cache_expiry_hours": 12,
    "retry_attempts": 2,
}
