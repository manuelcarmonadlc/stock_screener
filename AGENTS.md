# Stock Opportunity Screener

## Project description

Screener de acciones que detecta empresas sólidas (tipo buy&hold con dividendos) temporalmente infravaloradas, con confirmación de análisis técnico. Estrategia inspirada en Gregorio Hernández Jiménez (medio plazo: compra en caída temporal, venta en 6-24 meses).

## Project structure

```
stock_screener/
├── AGENTS.md                  # This file (instructions for coding agents)
├── config.py                  # Configuration: thresholds, tickers, weights, sector adjustments
├── screener.py                # Main engine: 5-layer pipeline, scoring, export, alerts
├── database.py                # SQLite persistence: evaluations, watchlist, alerts
├── dashboard.py               # Streamlit dashboard
├── requirements.txt           # Python dependencies
├── requirements_streamlit.txt # Streamlit Cloud dependencies
├── documentation/             # Project documentation and handoff material
├── .streamlit/                # Streamlit config and secrets example
├── .github/workflows/         # Automated scans in GitHub Actions
├── cache/                     # Local yfinance data cache (auto-generated)
└── results/                   # Output: CSV + fichas Markdown (auto-generated)
```

## Dev environment

- **Python 3.10+** on Windows
- Virtual environment: `.venv` in project root
- Install: `pip install -r requirements.txt`

## Build and test commands

```bash
# Create venv and install deps
python -m venv .venv
.venv\Scripts\activate        # Windows CMD
# .venv/Scripts/Activate.ps1  # PowerShell
pip install -r requirements.txt

# Quick test (IBEX only, ~3 min)
python screener.py --quick

# Full scan (all markets, ~30 min)
python screener.py

# Specific markets
python screener.py --markets IBEX SP500

# Clear cache and rescan
python screener.py --clear-cache

# Watchlist and alerts
python screener.py --watchlist
python screener.py --alerts
```

After any code change, always run `python screener.py --quick` to verify it works.

## Tech stack

- **yfinance** — Market data (prices, fundamentals, dividends)
- **pandas / numpy** — Data processing
- **ta** (Technical Analysis library) — RSI, MACD, technical indicators
- **rich** — Console output with tables and progress bars
- **openpyxl** — Excel export

## Business logic: 5-layer filtering

### Layer 1 — Quantitative
Evaluates HISTORICAL QUALITY, not current state. Key philosophy: a company
that has cut or suspended its dividend is NOT discarded — this may be PART
of the opportunity. What matters is whether it WAS solid before the problem:
- Dividend history (years paying in last 10, not necessarily consecutive)
- Current dividend: bonus if still paying, but NEVER penalizes if zero
- Recent dividend cut: detected and flagged as opportunity signal
- Debt/Equity controlled (critical to survive the downturn), adjusted by sector
- ROE with soft floor (depressed ROE is acceptable if not negative)
- Minimum market cap (avoid penny stocks)
- Valuation metrics integrated here: PE, P/B, EV/EBITDA, drawdowns, liquidity

### Layer 2 — Causal classification
Currently heuristic/stub. Reserved for causal diagnosis of the problem.

### Layer 3 — Recovery
Signals based on yfinance data only: margin stabilization, EPS stabilization,
debt reduction, dividend maintained, analyst upside, insider context if available.

### Layer 4 — Technical validation
Timing signals: RSI, MACD, supports, SMA50/SMA200, weekly MACD, stochastic,
weekly MA40, base pattern detection, trendline break proxy.

### Layer 5 — Operational plan
Final categorical classification, entry/exit zones, invalidation conditions,
horizon estimate, Markdown fichas.

### Hard rules
Hard rules override the numeric score before final classification.

## Markets covered

- **IBEX**: ~40 tickers (IBEX 35 + selected Mercado Continuo)
- **EUROSTOXX**: ~90 tickers (DAX, CAC40, AEX, FTSE MIB, BEL20, PSI, SMI, FTSE100)
- **SP500**: ~80 tickers (Dividend Aristocrats + Value)
- **ASX**: ~30 tickers (main Australian stocks)
- **ASIA**: ~50 tickers (Nikkei, Hang Seng, KOSPI, SGX)

## Coding conventions

- Code language: English (function/variable names). Comments and user strings: Spanish.
- Docstrings in Spanish.
- Type hints on public functions.
- Config centralized in config.py — never hardcode thresholds in screener.py.
- Sector overrides (SECTOR_OVERRIDES) are critical: banks have high D/E by nature, etc.
- Local JSON cache to avoid yfinance rate-limiting.
- Always export to both Excel + CSV with timestamp.

## Known limitations (v1) → Roadmap v2

1. **Historical PE**: Estimated by comparing trailing vs forward PE. No real 5-year average PE because yfinance doesn't reliably provide historical earnings. → Fix with scraping or paid API.
2. **Historical dividend yield**: No comparison of current yield vs 5-year average. → Calculate from dividend history + historical prices.
3. **RSI divergences**: No bullish divergence detection RSI/price. → Implement with slope analysis.
4. **Alerts**: No notifications. → Email/Telegram when new opportunities appear.
5. **Dashboard**: Console only. → Dash/Streamlit for web visualization.
6. **Backtesting**: Not validated with historical data. → Simulate past results to calibrate thresholds.

## Development principles

- **Iterative**: Use versioning v1, v2, v3 with explicit deltas.
- **Modular**: Each analysis layer is independent and testable.
- **Configurable**: Every threshold in config.py, nothing hardcoded.
- **Defensive**: Try/catch on data fetch; failing tickers don't interrupt the scan.
- **Transparent**: Output shows exactly which flags were triggered and why.

## Deployment

- **Streamlit Cloud entry point**: `dashboard.py`
- **Authentication**: `st.secrets["auth"]["password"]`
- **Secret template**: `.streamlit/secrets.toml.example`
- **Cloud data source**: latest `results/oportunidades_*.csv`
- **Local data source**: SQLite (`screener.db`) with CSV enrichment when available
- **Automation**: GitHub Actions workflows in `.github/workflows/`
- **Flow**: GitHub Actions runs `screener.py` -> commits `results/` -> Streamlit Cloud reads CSV and fichas
