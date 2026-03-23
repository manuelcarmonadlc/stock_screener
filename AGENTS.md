# Stock Opportunity Screener

## Project description

Screener de acciones que detecta empresas sólidas (tipo buy&hold con dividendos) temporalmente infravaloradas, con confirmación de análisis técnico. Estrategia inspirada en Gregorio Hernández Jiménez (medio plazo: compra en caída temporal, venta en 6-24 meses).

## Project structure

```
stock_screener/
├── AGENTS.md              # This file (instructions for coding agents)
├── config.py              # Configuration: thresholds, tickers, weights, sector adjustments
├── screener.py            # Main engine: data fetch, 3-layer analysis, scoring, export
├── requirements.txt       # Python dependencies
├── README.md              # User documentation
├── cache/                 # Local yfinance data cache (auto-generated)
└── results/               # Output: Excel + CSV with opportunities (auto-generated)
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
```

After any code change, always run `python screener.py --quick` to verify it works.

## Tech stack

- **yfinance** — Market data (prices, fundamentals, dividends)
- **pandas / numpy** — Data processing
- **ta** (Technical Analysis library) — RSI, MACD, technical indicators
- **rich** — Console output with tables and progress bars
- **openpyxl** — Excel export

## Business logic: 3-layer filtering

### Layer 1 — Fundamental (35% of score)
Evaluates HISTORICAL QUALITY, not current state. Key philosophy: a company
that has cut or suspended its dividend is NOT discarded — this may be PART
of the opportunity. What matters is whether it WAS solid before the problem:
- Dividend history (years paying in last 10, not necessarily consecutive)
- Current dividend: bonus if still paying, but NEVER penalizes if zero
- Recent dividend cut: detected and flagged as opportunity signal
- Debt/Equity controlled (critical to survive the downturn), adjusted by sector
- ROE with soft floor (depressed ROE is acceptable if not negative)
- Minimum market cap (avoid penny stocks)

### Layer 2 — Valuation (40% of score)
Detects temporary undervaluation: low PE ratio vs threshold, 15-60% drop from
52-week high, reasonable P/B ratio, price below SMA200.

### Layer 3 — Technical (25% of score)
Timing signals: RSI oversold/recovery, MACD bullish crossover or convergence,
SMA50 turning up, increasing volume, proximity to support levels.

### Scoring
Weighted composite score 0-100 with labels:
🟢 ≥75 (strong), 🟡 ≥60 (moderate), 🔵 ≥55 (watch).

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
