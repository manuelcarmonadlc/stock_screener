#!/usr/bin/env python3
"""
=============================================================================
 STOCK OPPORTUNITY SCREENER v1.0
=============================================================================
 Detecta empresas sólidas temporalmente infravaloradas con confirmación
 técnica. Estrategia tipo Gregorio Hernández (medio plazo).
 
 Uso:
   python screener.py                    # Escaneo completo
   python screener.py --markets EUROSTOXX SP500  # Solo mercados específicos
   python screener.py --quick             # QUICK_MARKETS (prueba rápida)
 
 Requisitos:
   pip install -r requirements.txt
=============================================================================
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

import numpy as np
import pandas as pd
import ta
import yfinance as yf
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.panel import Panel
from rich import box

import config as cfg
import database

warnings.filterwarnings("ignore")


def _configure_stdio_for_console() -> None:
    """Evita errores de codificación en consolas Windows no UTF-8."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


_configure_stdio_for_console()
console = Console()


# ===========================================================================
#  CACHÉ LOCAL
# ===========================================================================
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
CONFIG_HASH_FILE = Path(".config_hash")
_VERSIONING_LOCK = Lock()
_VERSIONING_CACHE: dict | None = None


def get_cache_path(ticker: str) -> Path:
    safe_name = ticker.replace(".", "_").replace("-", "_")
    return CACHE_DIR / f"{safe_name}.json"


def _is_valid_cached_ticker_data(data: dict | None) -> bool:
    """Valida que la entrada de cache tenga la estructura minima esperada."""
    if not isinstance(data, dict):
        return False

    info = data.get("info")
    history = data.get("history")
    if not isinstance(info, dict) or not isinstance(history, dict):
        return False

    closes = history.get("close")
    dates = history.get("dates")
    if not isinstance(closes, list) or not isinstance(dates, list):
        return False

    return len(closes) >= 60 and len(closes) == len(dates)


def load_from_cache(ticker: str) -> dict | None:
    path = get_cache_path(ticker)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
        expiry = timedelta(hours=cfg.EXECUTION["cache_expiry_hours"])
        if datetime.now() - cached_at > expiry:
            return None
        return data
    except Exception:
        return None


def save_to_cache(ticker: str, data: dict):
    payload = dict(data)
    payload["_cached_at"] = datetime.now().isoformat()
    path = get_cache_path(ticker)
    try:
        with open(path, "w") as f:
            json.dump(payload, f, default=str)
    except Exception:
        pass


def _compute_config_hash() -> str:
    """Calcula un hash estable de los umbrales de configuracion activos."""
    payload = {
        "FUNDAMENTAL": cfg.FUNDAMENTAL,
        "VALUATION": cfg.VALUATION,
        "TECHNICAL": cfg.TECHNICAL,
        "SCORING": cfg.SCORING,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    """Convierte una version tipo 1.0.3 en una tupla comparable."""
    if not version:
        return ()

    parts = []
    for chunk in str(version).split("."):
        if not chunk.isdigit():
            return ()
        parts.append(int(chunk))
    return tuple(parts)


def _max_version_string(base_version: str, stored_version: str) -> str:
    """Devuelve la version mas alta entre la base declarada y la persistida."""
    if not stored_version:
        return base_version

    base_parts = _parse_version_tuple(str(base_version))
    stored_parts = _parse_version_tuple(str(stored_version))
    if not base_parts or not stored_parts:
        return stored_version or base_version

    max_len = max(len(base_parts), len(stored_parts))
    padded_base = base_parts + (0,) * (max_len - len(base_parts))
    padded_stored = stored_parts + (0,) * (max_len - len(stored_parts))
    return base_version if padded_base >= padded_stored else stored_version


def _increment_version_string(version: str) -> str:
    """Incrementa el ultimo segmento numerico de una version."""
    text = str(version or "1.0")
    parts = text.split(".")

    for idx in range(len(parts) - 1, -1, -1):
        if parts[idx].isdigit():
            parts[idx] = str(int(parts[idx]) + 1)
            return ".".join(parts)

    return f"{text}.1"


def _load_config_hash_state() -> dict:
    """Carga el estado persistido del hash de configuracion."""
    if not CONFIG_HASH_FILE.exists():
        return {}

    try:
        with open(CONFIG_HASH_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_config_hash_state(state: dict) -> None:
    """Persiste hash y version de configuracion para futuras ejecuciones."""
    try:
        with open(CONFIG_HASH_FILE, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
    except Exception:
        pass


def get_versioning_metadata() -> dict:
    """
    Resuelve el versionado efectivo de evaluacion y auto-incrementa
    config_version si cambian los umbrales principales.
    """
    global _VERSIONING_CACHE

    with _VERSIONING_LOCK:
        if _VERSIONING_CACHE is not None:
            return dict(_VERSIONING_CACHE)

        current_hash = _compute_config_hash()
        stored_state = _load_config_hash_state()

        rules_version = str(cfg.VERSIONING.get("rules_version", "1.0"))
        model_version = str(cfg.VERSIONING.get("model_version", "script-v2.0"))
        base_config_version = str(cfg.VERSIONING.get("config_version", "1.0"))
        stored_config_version = str(stored_state.get("config_version", "")).strip()

        resolved_config_version = _max_version_string(
            base_config_version,
            stored_config_version,
        )
        stored_hash = stored_state.get("config_hash")
        if stored_hash and stored_hash != current_hash:
            resolved_config_version = _increment_version_string(resolved_config_version)

        persisted_state = {
            "config_hash": current_hash,
            "config_version": resolved_config_version,
            "rules_version": rules_version,
            "model_version": model_version,
        }
        comparable_stored_state = {
            "config_hash": stored_state.get("config_hash"),
            "config_version": stored_state.get("config_version"),
            "rules_version": stored_state.get("rules_version"),
            "model_version": stored_state.get("model_version"),
        }
        if persisted_state != comparable_stored_state:
            persisted_state["updated_at"] = datetime.now().astimezone().isoformat()
            _save_config_hash_state(persisted_state)

        _VERSIONING_CACHE = {
            "rules_version": rules_version,
            "model_version": model_version,
            "config_version": resolved_config_version,
        }
        return dict(_VERSIONING_CACHE)


# ===========================================================================
#  OBTENCIÓN DE DATOS
# ===========================================================================
def _safe_float(value: object) -> float | None:
    """Convierte un valor numérico potencialmente sucio en float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(number) or np.isinf(number):
        return None
    return number


def _normalize_yield_pct(raw_yield: object) -> float:
    """Normaliza dividendYield a porcentaje legible."""
    yield_value = _safe_float(raw_yield)
    if yield_value is None or yield_value <= 0:
        return 0.0
    return yield_value if yield_value > 0.3 else yield_value * 100


def _compute_current_dividend_yield_pct(info: dict,
                                        current_price: float | None = None) -> float:
    """Calcula yield actual usando dividendo anual / precio cuando sea posible."""
    if current_price is None:
        current_price = (
            _safe_float(info.get("regularMarketPrice")) or
            _safe_float(info.get("currentPrice")) or
            _safe_float(info.get("previousClose"))
        )

    annual_dividend_rate = (
        _safe_float(info.get("dividendRate")) or
        _safe_float(info.get("trailingAnnualDividendRate"))
    )
    if annual_dividend_rate is not None and current_price is not None and current_price > 0:
        return (annual_dividend_rate / current_price) * 100

    return _normalize_yield_pct(
        info.get("dividendYield") if info.get("dividendYield") is not None
        else info.get("trailingAnnualDividendYield")
    )


def _to_iso_date(value: object) -> str | None:
    """Normaliza fechas a formato ISO YYYY-MM-DD."""
    try:
        timestamp = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(timestamp):
        return None
    return timestamp.date().isoformat()


def _serialize_close_history(history: pd.DataFrame) -> dict:
    """Serializa un histórico de cierres para guardarlo en caché JSON."""
    if history is None or history.empty or "Close" not in history:
        return {"dates": [], "close": []}

    dates = []
    closes = []
    for date_value, close_value in zip(history.index, history["Close"].tolist()):
        date_str = _to_iso_date(date_value)
        close_float = _safe_float(close_value)
        if date_str is None or close_float is None:
            continue
        dates.append(date_str)
        closes.append(close_float)

    return {"dates": dates, "close": closes}


FINANCIAL_STATEMENT_ROWS = (
    "EBITDA",
    "Normalized EBITDA",
    "Total Revenue",
    "Operating Revenue",
    "Revenue",
    "Gross Profit",
    "Operating Income",
    "Operating Income As Reported",
    "EBIT",
    "Diluted EPS",
    "Basic EPS",
    "Net Income Common Stockholders",
    "Diluted NI Availto Com Stockholders",
    "Net Income",
    "Net Income From Continuing And Discontinued Operation",
    "Diluted Average Shares",
    "Basic Average Shares",
)

BALANCE_SHEET_ROWS = (
    "Total Debt",
    "Total Debt And Capital Lease Obligation",
    "Current Debt And Capital Lease Obligation",
    "Cash And Cash Equivalents",
    "Cash Cash Equivalents And Short Term Investments",
    "Cash And Short Term Investments",
    "Cash Equivalents",
)

EBITDA_ROWS = ("EBITDA", "Normalized EBITDA")
REVENUE_ROWS = ("Total Revenue", "Operating Revenue", "Revenue")
GROSS_PROFIT_ROWS = ("Gross Profit",)
OPERATING_INCOME_ROWS = ("Operating Income", "Operating Income As Reported", "EBIT")
QUARTERLY_EPS_ROWS = ("Diluted EPS", "Basic EPS")
QUARTERLY_NET_INCOME_ROWS = (
    "Net Income Common Stockholders",
    "Diluted NI Availto Com Stockholders",
    "Net Income",
    "Net Income From Continuing And Discontinued Operation",
)
QUARTERLY_AVERAGE_SHARES_ROWS = ("Diluted Average Shares", "Basic Average Shares")
TOTAL_DEBT_ROWS = (
    "Total Debt",
    "Total Debt And Capital Lease Obligation",
    "Current Debt And Capital Lease Obligation",
)
CASH_ROWS = (
    "Cash And Cash Equivalents",
    "Cash Cash Equivalents And Short Term Investments",
    "Cash And Short Term Investments",
    "Cash Equivalents",
)


def _serialize_statement(statement: pd.DataFrame, row_names: tuple[str, ...]) -> dict:
    """Serializa filas relevantes de un estado financiero a JSON simple."""
    if statement is None or statement.empty:
        return {"columns": [], "rows": {}}

    valid_columns = []
    column_labels = []
    for column in statement.columns:
        label = _to_iso_date(column)
        if label is None:
            continue
        valid_columns.append(column)
        column_labels.append(label)

    if not valid_columns:
        return {"columns": [], "rows": {}}

    rows = {}
    for row_name in row_names:
        if row_name not in statement.index:
            continue
        raw_values = statement.loc[row_name, valid_columns]
        if isinstance(raw_values, pd.DataFrame):
            raw_values = raw_values.iloc[0]
        values = pd.to_numeric(raw_values, errors="coerce")
        rows[row_name] = [_safe_float(value) for value in values.tolist()]

    return {
        "columns": column_labels,
        "rows": rows,
    }


def _get_statement_series(statement_data: dict,
                          candidate_rows: tuple[str, ...]) -> list[dict]:
    """Devuelve la primera fila disponible de un estado financiero serializado."""
    columns = statement_data.get("columns", [])
    rows = statement_data.get("rows", {})
    if not isinstance(columns, list) or not isinstance(rows, dict):
        return []

    for row_name in candidate_rows:
        values = rows.get(row_name)
        if not isinstance(values, list):
            continue

        series = []
        for idx, value in enumerate(values):
            if idx >= len(columns) or value is None:
                continue
            series.append({
                "date": columns[idx],
                "value": value,
                "row": row_name,
            })
        if series:
            return series

    return []


def _get_latest_statement_value(statement_data: dict,
                                candidate_rows: tuple[str, ...]) -> tuple[float | None, str | None]:
    """Obtiene el valor mas reciente disponible de una fila candidata."""
    series = _get_statement_series(statement_data, candidate_rows)
    if not series:
        return None, None
    return series[0]["value"], series[0]["row"]


def _extract_ebitda_value(info: dict, financials: dict,
                          quarterly_financials: dict) -> tuple[float | None, str | None]:
    """Obtiene EBITDA desde info y, si falta, desde financials."""
    ebitda = _safe_float(info.get("ebitda"))
    if ebitda is not None and ebitda > 0:
        return ebitda, "info.ebitda"

    ebitda, row_name = _get_latest_statement_value(financials, EBITDA_ROWS)
    if ebitda is not None and ebitda > 0:
        return ebitda, f"financials.{row_name}"

    quarterly_ebitda = _get_statement_series(quarterly_financials, EBITDA_ROWS)
    trailing_values = [
        item["value"]
        for item in quarterly_ebitda[:4]
        if item.get("value") is not None
    ]
    if len(trailing_values) >= 2:
        trailing_ebitda = float(sum(trailing_values))
        if trailing_ebitda > 0:
            return trailing_ebitda, "quarterly_financials_ttm"

    return None, None


def _extract_balance_sheet_value(info: dict, info_key: str, statement: dict,
                                 candidate_rows: tuple[str, ...]) -> tuple[float | None, str | None]:
    """Obtiene un valor de balance desde info con fallback a balance sheet."""
    value = _safe_float(info.get(info_key))
    if value is not None:
        return value, f"info.{info_key}"

    value, row_name = _get_latest_statement_value(statement, candidate_rows)
    if value is not None:
        return value, f"balance_sheet.{row_name}"

    return None, None


def _compute_margin_series(statement: dict,
                           numerator_rows: tuple[str, ...]) -> list[dict]:
    """Calcula una serie trimestral de margenes a partir del estado de resultados."""
    revenues = _get_statement_series(statement, REVENUE_ROWS)
    numerators = _get_statement_series(statement, numerator_rows)
    if not revenues or not numerators:
        return []

    revenue_by_date = {
        item["date"]: item["value"]
        for item in revenues
        if item.get("value") is not None and item["value"] > 0
    }

    margins = []
    for item in numerators:
        revenue = revenue_by_date.get(item["date"])
        numerator = item.get("value")
        if revenue is None or numerator is None:
            continue
        margins.append({
            "date": item["date"],
            "margin": numerator / revenue,
            "row": item["row"],
        })
    return margins


def _normalize_annual_eps(records: list[dict]) -> list[dict]:
    """Deduplica por año y devuelve como máximo 5 ejercicios ordenados."""
    by_year: dict[str, dict] = {}

    for record in records:
        date_str = record.get("date")
        eps_value = _safe_float(record.get("eps"))
        if not date_str or eps_value is None:
            continue

        year = date_str[:4]
        current = by_year.get(year)
        if current is None or date_str > current["date"]:
            by_year[year] = {
                "date": date_str,
                "eps": eps_value,
                "source": record.get("source"),
            }

    return sorted(by_year.values(), key=lambda item: item["date"], reverse=True)[:5]


def _extract_annual_eps_from_financials(financials: pd.DataFrame) -> list[dict]:
    """Extrae EPS anual desde financials, priorizando el EPS reportado."""
    if financials is None or financials.empty:
        return []

    eps_series = None
    for row_name in ("Diluted EPS", "Basic EPS"):
        if row_name in financials.index:
            eps_series = pd.to_numeric(financials.loc[row_name], errors="coerce")
            break

    if eps_series is None:
        income_row = next((
            row_name for row_name in (
                "Net Income Common Stockholders",
                "Diluted NI Availto Com Stockholders",
                "Net Income",
                "Net Income From Continuing And Discontinued Operation",
            )
            if row_name in financials.index
        ), None)
        shares_row = next((
            row_name for row_name in ("Diluted Average Shares", "Basic Average Shares")
            if row_name in financials.index
        ), None)

        if income_row and shares_row:
            net_income = pd.to_numeric(financials.loc[income_row], errors="coerce")
            avg_shares = pd.to_numeric(financials.loc[shares_row], errors="coerce").replace(0, np.nan)
            eps_series = net_income / avg_shares

    if eps_series is None:
        return []

    records = []
    for period_end, eps_value in eps_series.items():
        date_str = _to_iso_date(period_end)
        eps_float = _safe_float(eps_value)
        if date_str is None or eps_float is None:
            continue
        records.append({
            "date": date_str,
            "eps": eps_float,
            "source": "financials",
        })

    return _normalize_annual_eps(records)


def _extract_annual_eps_from_earnings_history(earnings_history: pd.DataFrame) -> list[dict]:
    """Agrupa EPS trimestral por año natural como fallback."""
    if earnings_history is None or earnings_history.empty or "epsActual" not in earnings_history.columns:
        return []

    if "quarter" in earnings_history.columns:
        report_dates = pd.to_datetime(earnings_history["quarter"], errors="coerce")
    else:
        report_dates = pd.to_datetime(earnings_history.index, errors="coerce")

    work = pd.DataFrame({
        "date": report_dates,
        "eps": pd.to_numeric(earnings_history["epsActual"], errors="coerce"),
    }).dropna(subset=["date", "eps"])

    if work.empty:
        return []

    work["year"] = work["date"].dt.year
    grouped = work.groupby("year").agg(
        eps=("eps", "sum"),
        reports=("eps", "count"),
        last_date=("date", "max"),
    )
    grouped = grouped[grouped["reports"] >= 3]

    records = []
    for _, row in grouped.iterrows():
        date_str = _to_iso_date(row["last_date"])
        eps_float = _safe_float(row["eps"])
        if date_str is None or eps_float is None:
            continue
        records.append({
            "date": date_str,
            "eps": eps_float,
            "source": "earnings_history",
        })

    return _normalize_annual_eps(records)


def _extract_annual_eps_from_earnings_dates(stock: yf.Ticker) -> list[dict]:
    """Usa earnings_dates como último fallback si Yahoo lo expone."""
    try:
        if hasattr(stock, "get_earnings_dates"):
            earnings_dates = stock.get_earnings_dates(limit=20)
        else:
            earnings_dates = stock.earnings_dates
    except Exception:
        return []

    if earnings_dates is None or earnings_dates.empty:
        return []

    eps_column = next((
        column_name for column_name in ("Reported EPS", "epsActual", "reportedEPS")
        if column_name in earnings_dates.columns
    ), None)
    if eps_column is None:
        return []

    work = pd.DataFrame({
        "date": pd.to_datetime(earnings_dates.index, errors="coerce"),
        "eps": pd.to_numeric(earnings_dates[eps_column], errors="coerce"),
    }).dropna(subset=["date", "eps"])

    if work.empty:
        return []

    work["year"] = work["date"].dt.year
    grouped = work.groupby("year").agg(
        eps=("eps", "sum"),
        reports=("eps", "count"),
        last_date=("date", "max"),
    )
    grouped = grouped[grouped["reports"] >= 3]

    records = []
    for _, row in grouped.iterrows():
        date_str = _to_iso_date(row["last_date"])
        eps_float = _safe_float(row["eps"])
        if date_str is None or eps_float is None:
            continue
        records.append({
            "date": date_str,
            "eps": eps_float,
            "source": "earnings_dates",
        })

    return _normalize_annual_eps(records)


def _extract_annual_eps_series(stock: yf.Ticker) -> list[dict]:
    """Selecciona la mejor serie anual disponible para estimar PER histórico."""
    candidates: list[tuple[int, int, list[dict]]] = []

    extractors = (
        lambda: _extract_annual_eps_from_financials(stock.financials),
        lambda: _extract_annual_eps_from_earnings_history(stock.earnings_history),
        lambda: _extract_annual_eps_from_earnings_dates(stock),
    )

    for priority, extractor in enumerate(extractors):
        try:
            series = extractor()
        except Exception:
            series = []
        if series:
            candidates.append((len(series), -priority, series))

    if not candidates:
        return []

    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _find_price_near_date(price_points: list[tuple[pd.Timestamp, float]],
                          target_date: str) -> float | None:
    """Busca el cierre más cercano al fin del ejercicio."""
    try:
        target = pd.Timestamp(target_date).normalize()
    except Exception:
        return None

    closest_price = None
    closest_delta = None
    for point_date, point_price in price_points:
        delta_days = abs((point_date - target).days)
        if closest_delta is None or delta_days < closest_delta:
            closest_delta = delta_days
            closest_price = point_price

    if closest_delta is not None and closest_delta <= 45:
        return closest_price

    prior_prices = [
        point_price
        for point_date, point_price in price_points
        if point_date <= target and (target - point_date).days <= 90
    ]
    if prior_prices:
        return prior_prices[-1]

    return None


def _compute_historical_pe_stats(current_pe: float | None,
                                 annual_eps: list[dict],
                                 valuation_history: dict) -> dict:
    """Calcula el PER medio histórico a partir de EPS anual y precio histórico."""
    stats = {
        "historical_avg_pe": None,
        "historical_pe_years": 0,
        "per_discount_pct": None,
        "per_discount_method": None,
        "historical_eps_source": None,
    }

    dates = valuation_history.get("dates", [])
    closes = valuation_history.get("close", [])
    if not annual_eps or not dates or not closes:
        return stats

    price_points = []
    for date_str, close_value in zip(dates, closes):
        close_float = _safe_float(close_value)
        if close_float is None or close_float <= 0:
            continue
        try:
            point_date = pd.Timestamp(date_str).normalize()
        except Exception:
            continue
        price_points.append((point_date, close_float))

    if not price_points:
        return stats

    price_points.sort(key=lambda item: item[0])

    annual_pes = []
    for record in annual_eps:
        eps_value = _safe_float(record.get("eps"))
        if eps_value is None or eps_value <= 0:
            continue

        date_str = record.get("date")
        if not date_str:
            continue

        historical_price = _find_price_near_date(price_points, date_str)
        if historical_price is None or historical_price <= 0:
            continue

        annual_pes.append(historical_price / eps_value)

    if len(annual_pes) < 3:
        return stats

    historical_avg_pe = float(np.mean(annual_pes[:5]))
    stats["historical_avg_pe"] = historical_avg_pe
    stats["historical_pe_years"] = min(len(annual_pes), 5)
    stats["per_discount_method"] = "historical_5y"
    stats["historical_eps_source"] = annual_eps[0].get("source")

    if current_pe is not None and current_pe > 0 and historical_avg_pe > 0:
        stats["per_discount_pct"] = ((historical_avg_pe - current_pe) / historical_avg_pe) * 100

    return stats


def _compute_historical_dividend_yield_stats(current_yield_pct: float,
                                             dividends: list[dict],
                                             valuation_history: dict) -> dict:
    """Calcula yield medio historico 5y = dividendos anuales / precio medio anual."""
    stats = {
        "historical_avg_div_yield_pct": None,
        "historical_div_yield_years": 0,
        "div_yield_premium_pct": None,
    }

    dates = valuation_history.get("dates", [])
    closes = valuation_history.get("close", [])
    if not dividends or not dates or not closes:
        return stats

    current_year = datetime.now().year
    target_years = {current_year - offset for offset in range(1, 6)}

    yearly_dividends: dict[int, float] = {}
    for record in dividends:
        date_str = record.get("Date")
        amount = _safe_float(record.get("Dividend"))
        if not date_str or amount is None or amount <= 0:
            continue
        try:
            year = pd.Timestamp(date_str).year
        except Exception:
            continue
        if year in target_years:
            yearly_dividends[year] = yearly_dividends.get(year, 0.0) + amount

    yearly_prices: dict[int, list[float]] = {}
    for date_str, close_value in zip(dates, closes):
        close_float = _safe_float(close_value)
        if not date_str or close_float is None or close_float <= 0:
            continue
        try:
            year = pd.Timestamp(date_str).year
        except Exception:
            continue
        if year in target_years:
            yearly_prices.setdefault(year, []).append(close_float)

    yearly_yields = []
    for year in sorted(target_years, reverse=True):
        total_dividends = yearly_dividends.get(year)
        prices = yearly_prices.get(year)
        if not total_dividends or not prices:
            continue
        avg_price = float(np.mean(prices))
        if avg_price <= 0:
            continue
        yearly_yields.append((year, (total_dividends / avg_price) * 100))

    if len(yearly_yields) < 3:
        return stats

    historical_avg_div_yield_pct = float(np.mean([value for _, value in yearly_yields[:5]]))
    stats["historical_avg_div_yield_pct"] = historical_avg_div_yield_pct
    stats["historical_div_yield_years"] = min(len(yearly_yields), 5)

    if current_yield_pct > 0 and historical_avg_div_yield_pct > 0:
        stats["div_yield_premium_pct"] = (
            (current_yield_pct - historical_avg_div_yield_pct) / historical_avg_div_yield_pct
        ) * 100

    return stats


def _compute_enterprise_value_metrics(info: dict, financials: dict,
                                      quarterly_financials: dict,
                                      quarterly_balance_sheet: dict) -> dict:
    """Calcula EV/EBITDA y deuda neta / EBITDA con fallbacks razonables."""
    market_cap = _safe_float(info.get("marketCap"))
    total_debt, total_debt_source = _extract_balance_sheet_value(
        info, "totalDebt", quarterly_balance_sheet, TOTAL_DEBT_ROWS
    )
    total_cash, total_cash_source = _extract_balance_sheet_value(
        info, "totalCash", quarterly_balance_sheet, CASH_ROWS
    )
    ebitda, ebitda_source = _extract_ebitda_value(info, financials, quarterly_financials)

    enterprise_value = None
    if market_cap is not None and total_debt is not None and total_cash is not None:
        enterprise_value = market_cap + total_debt - total_cash

    ev_ebitda = _safe_float(info.get("enterpriseToEbitda"))
    ev_ebitda_source = "info.enterpriseToEbitda" if ev_ebitda is not None else None
    if ev_ebitda is None and enterprise_value is not None and ebitda is not None and ebitda > 0:
        ev_ebitda = enterprise_value / ebitda
        ev_ebitda_source = "calculated"

    net_debt = None
    if total_debt is not None and total_cash is not None:
        net_debt = total_debt - total_cash

    net_debt_ebitda = None
    if net_debt is not None and ebitda is not None and ebitda > 0:
        net_debt_ebitda = net_debt / ebitda

    return {
        "market_cap": market_cap,
        "total_debt": total_debt,
        "total_debt_source": total_debt_source,
        "total_cash": total_cash,
        "total_cash_source": total_cash_source,
        "ebitda": ebitda,
        "ebitda_source": ebitda_source,
        "enterprise_value": enterprise_value,
        "ev_ebitda": ev_ebitda,
        "ev_ebitda_source": ev_ebitda_source,
        "net_debt": net_debt,
        "net_debt_ebitda": net_debt_ebitda,
    }


def _compute_quarterly_debt_change(info: dict, quarterly_balance_sheet: dict,
                                   quarterly_financials: dict) -> dict:
    """Compara la deuda actual con la del trimestre previo si esta disponible."""
    debt_series = _get_statement_series(quarterly_balance_sheet, TOTAL_DEBT_ROWS)
    source = "quarterly_balance_sheet"
    if len(debt_series) < 2:
        debt_series = _get_statement_series(quarterly_financials, TOTAL_DEBT_ROWS)
        source = "quarterly_financials"

    current_debt = _safe_float(info.get("totalDebt"))
    if current_debt is None and debt_series:
        current_debt = debt_series[0]["value"]

    previous_debt = debt_series[1]["value"] if len(debt_series) >= 2 else None
    change_pct = None
    if current_debt is not None and previous_debt is not None and previous_debt > 0:
        change_pct = ((current_debt - previous_debt) / previous_debt) * 100

    return {
        "current_debt": current_debt,
        "previous_debt": previous_debt,
        "change_pct": change_pct,
        "source": source if debt_series else None,
    }


def _compute_margin_variation(info: dict, quarterly_financials: dict) -> dict:
    """Compara margen actual vs promedio de los ultimos 4 trimestres disponibles."""
    candidates = []

    gross_current = _safe_float(info.get("grossMargins"))
    gross_series = _compute_margin_series(quarterly_financials, GROSS_PROFIT_ROWS)
    if gross_current is not None or gross_series:
        candidates.append(("gross", gross_current, gross_series))

    operating_current = _safe_float(info.get("operatingMargins"))
    operating_series = _compute_margin_series(quarterly_financials, OPERATING_INCOME_ROWS)
    if operating_current is not None or operating_series:
        candidates.append(("operating", operating_current, operating_series))

    for margin_type, current_margin, margin_series in candidates:
        recent_margins = [item["margin"] for item in margin_series[:4] if item.get("margin") is not None]
        if not recent_margins:
            continue

        if current_margin is None:
            current_margin = margin_series[0]["margin"]

        average_margin = float(np.mean(recent_margins))
        return {
            "margin_type": margin_type,
            "current_margin": current_margin,
            "avg_last_4q_margin": average_margin,
            "margin_delta_pp": (current_margin - average_margin) * 100,
        }

    return {
        "margin_type": None,
        "current_margin": gross_current if gross_current is not None else operating_current,
        "avg_last_4q_margin": None,
        "margin_delta_pp": None,
    }


def _format_error_message(error: Exception) -> str:
    """Normaliza excepciones a un mensaje corto legible."""
    detail = str(error).strip()
    if detail:
        return f"{type(error).__name__}: {detail}"
    return type(error).__name__


def fetch_ticker_data_with_status(ticker: str) -> tuple[dict | None, str | None]:
    """
    Descarga datos de un ticker y devuelve tambien el motivo del fallo si lo hay.
    """
    cached = load_from_cache(ticker)
    if _is_valid_cached_ticker_data(cached):
        return cached, None

    last_error = None

    for attempt in range(cfg.EXECUTION["retry_attempts"]):
        try:
            time.sleep(cfg.EXECUTION["request_delay"])
            stock = yf.Ticker(ticker)

            info = stock.info
            if not info or info.get("regularMarketPrice") is None:
                if info.get("currentPrice") is None and info.get("previousClose") is None:
                    return None, "Missing market price in yfinance info"

            hist = stock.history(period=cfg.TECHNICAL["history_period"])
            if hist.empty:
                return None, "Empty price history"
            if len(hist) < 60:
                return None, f"Insufficient price history ({len(hist)} rows)"

            try:
                valuation_hist = stock.history(period="6y", interval="1mo")
            except Exception:
                valuation_hist = pd.DataFrame()

            try:
                annual_eps = _extract_annual_eps_series(stock)
            except Exception:
                annual_eps = []

            try:
                financials = _serialize_statement(stock.financials, FINANCIAL_STATEMENT_ROWS)
            except Exception:
                financials = {"columns": [], "rows": {}}

            try:
                quarterly_financials = _serialize_statement(
                    stock.quarterly_financials,
                    FINANCIAL_STATEMENT_ROWS,
                )
            except Exception:
                quarterly_financials = {"columns": [], "rows": {}}

            try:
                quarterly_balance_sheet = _serialize_statement(
                    stock.quarterly_balance_sheet,
                    BALANCE_SHEET_ROWS,
                )
            except Exception:
                quarterly_balance_sheet = {"columns": [], "rows": {}}

            dividends = stock.dividends
            if dividends is not None and not dividends.empty:
                div_data = dividends.reset_index()
                div_data.columns = ["Date", "Dividend"]
                div_data["Date"] = div_data["Date"].astype(str)
                div_list = div_data.to_dict("records")
            else:
                div_list = []

            data = {
                "ticker": ticker,
                "info": {k: v for k, v in info.items()
                         if isinstance(v, (str, int, float, bool, type(None)))},
                "history": {
                    "dates": [str(d.date()) if hasattr(d, 'date') else str(d)
                              for d in hist.index],
                    "close": hist["Close"].tolist(),
                    "high": hist["High"].tolist(),
                    "low": hist["Low"].tolist(),
                    "volume": hist["Volume"].tolist(),
                    "open": hist["Open"].tolist(),
                },
                "valuation_history": _serialize_close_history(valuation_hist),
                "annual_eps": annual_eps,
                "financials": financials,
                "quarterly_financials": quarterly_financials,
                "quarterly_balance_sheet": quarterly_balance_sheet,
                "dividends": div_list,
            }

            save_to_cache(ticker, data)
            return data, None

        except Exception as error:
            last_error = _format_error_message(error)
            if attempt < cfg.EXECUTION["retry_attempts"] - 1:
                time.sleep(1)
            continue

    return None, last_error or "Unknown fetch error"


def fetch_ticker_data(ticker: str) -> dict | None:
    """
    Descarga todos los datos necesarios de un ticker vía yfinance.
    Devuelve un dict consolidado o None si falla.
    """
    data, _ = fetch_ticker_data_with_status(ticker)
    return data


# ===========================================================================
#  ANÁLISIS FUNDAMENTAL (Capa 1)
# ===========================================================================
def analyze_fundamental(data: dict) -> dict:
    """
    Evalúa solidez fundamental con foco en HISTORIAL DE CALIDAD.
    
    Filosofía: buscamos empresas que ERAN sólidas pagadoras de dividendo
    y están en un bache temporal. El dividendo actual puede estar reducido
    o suspendido — eso no las descarta, puede ser PARTE de la oportunidad.
    
    Lo que importa:
    - ¿Tiene historial de pagar dividendos durante años? (calidad pasada)
    - ¿Tiene deuda controlada? (capacidad de sobrevivir al bache)
    - ¿Tenía buena rentabilidad? (ROE, aunque ahora puede estar deprimido)
    - ¿Es una empresa de tamaño relevante? (no chicharros)
    
    Lo que NO descarta:
    - Dividendo actual bajo o cero (puede ser temporal)
    - ROE bajo si está por encima del suelo mínimo (bache temporal)
    - Payout ratio actual (irrelevante si ha cortado dividendo)
    """
    info = data.get("info", {})
    hist = data.get("history", {})
    financials = data.get("financials", {})
    quarterly_financials = data.get("quarterly_financials", {})
    quarterly_balance_sheet = data.get("quarterly_balance_sheet", {})
    result = {
        "passed": False,
        "score": 0,
        "metrics": {},
        "flags": [],
    }

    sector = info.get("sector", "Unknown")
    overrides = cfg.SECTOR_OVERRIDES.get(sector, {})

    # ── Dividendo ACTUAL (informativo, no eliminatorio) ──
    div_yield_pct = _compute_current_dividend_yield_pct(info)
    result["metrics"]["dividend_yield_pct"] = round(div_yield_pct, 2)

    # ── HISTORIAL de dividendos (esto sí importa) ──
    divs = data.get("dividends", [])
    div_history = _analyze_dividend_history(divs)
    result["metrics"]["div_years_in_last_10"] = div_history["years_with_div"]
    result["metrics"]["div_was_cut_recently"] = div_history["recently_cut"]
    result["metrics"]["peak_yield_estimated"] = div_history["peak_yield_estimated"]
    result["metrics"]["consecutive_div_years_before_cut"] = div_history["consecutive_before_cut"]

    # ── Payout ratio (solo informativo si paga dividendo) ──
    payout = _safe_float(info.get("payoutRatio"))
    payout_pct = (payout * 100) if payout is not None else None
    result["metrics"]["payout_ratio_pct"] = round(payout_pct, 1) if payout_pct else None

    # ── Deuda / Equity ──
    debt_equity = _safe_float(info.get("debtToEquity"))
    if debt_equity is not None:
        debt_equity = debt_equity / 100 if debt_equity > 10 else debt_equity
    max_de = overrides.get("max_debt_to_equity", cfg.FUNDAMENTAL["max_debt_to_equity"])
    result["metrics"]["debt_to_equity"] = round(debt_equity, 2) if debt_equity is not None else None

    # ── ROE ──
    roe = _safe_float(info.get("returnOnEquity"))
    roe_pct = (roe * 100) if roe is not None else None
    min_roe = overrides.get("min_roe", cfg.FUNDAMENTAL["min_roe"])
    roe_soft_floor = cfg.FUNDAMENTAL["roe_soft_floor"]
    result["metrics"]["roe_pct"] = round(roe_pct, 1) if roe_pct is not None else None

    # ── Market Cap ──
    market_cap = _safe_float(info.get("marketCap")) or 0
    market_cap_m = market_cap / 1_000_000
    result["metrics"]["market_cap_millions"] = round(market_cap_m, 0)

    volume_window = hist.get("volume", [])[-20:]
    clean_volumes = []
    for value in volume_window:
        normalized = _safe_float(value)
        if normalized is not None:
            clean_volumes.append(normalized)
    avg_volume_20d = float(np.mean(clean_volumes)) if clean_volumes else None
    avg_daily_volume = (
        _safe_float(info.get("averageVolume")) or
        _safe_float(info.get("averageVolume10days")) or
        avg_volume_20d
    )
    result["metrics"]["avg_daily_volume"] = round(avg_daily_volume, 0) if avg_daily_volume is not None else None
    result["metrics"]["avg_daily_volume_20d"] = (
        round(avg_volume_20d, 0) if avg_volume_20d is not None else None
    )

    leverage_metrics = _compute_enterprise_value_metrics(
        info,
        financials,
        quarterly_financials,
        quarterly_balance_sheet,
    )
    result["metrics"]["total_debt"] = leverage_metrics["total_debt"]
    result["metrics"]["total_cash"] = leverage_metrics["total_cash"]
    result["metrics"]["ebitda"] = leverage_metrics["ebitda"]
    result["metrics"]["net_debt"] = leverage_metrics["net_debt"]
    result["metrics"]["net_debt_ebitda"] = (
        round(leverage_metrics["net_debt_ebitda"], 2)
        if leverage_metrics["net_debt_ebitda"] is not None else None
    )

    debt_change = _compute_quarterly_debt_change(
        info,
        quarterly_balance_sheet,
        quarterly_financials,
    )
    result["metrics"]["quarterly_debt_change_pct"] = (
        round(debt_change["change_pct"], 1)
        if debt_change["change_pct"] is not None else None
    )

    margin_variation = _compute_margin_variation(info, quarterly_financials)
    result["metrics"]["margin_type"] = margin_variation["margin_type"]
    result["metrics"]["current_margin_pct"] = (
        round(margin_variation["current_margin"] * 100, 1)
        if margin_variation["current_margin"] is not None else None
    )
    result["metrics"]["avg_last_4q_margin_pct"] = (
        round(margin_variation["avg_last_4q_margin"] * 100, 1)
        if margin_variation["avg_last_4q_margin"] is not None else None
    )
    result["metrics"]["margin_delta_pp"] = (
        round(margin_variation["margin_delta_pp"], 1)
        if margin_variation["margin_delta_pp"] is not None else None
    )

    # ── SCORING ──
    score = 0
    max_score = 0

    # --- Historial de dividendos (30 puntos) - EL MÁS IMPORTANTE ---
    max_score += 30
    years_required = cfg.FUNDAMENTAL["min_historical_div_years"]
    years_actual = div_history["years_with_div"]

    if years_actual >= years_required:
        # Buena pagadora histórica
        base = 15 + min(15, (years_actual - years_required) * 2)
        score += base

        # ¿Cortó dividendo recientemente? No penaliza, pero es informativo
        if div_history["recently_cut"]:
            result["flags"].append(
                f"✓ Historial {years_actual} años div (recorte reciente → oportunidad?)")
        else:
            result["flags"].append(f"✓ Historial {years_actual} años de dividendo")

        # Bonus si el consecutive_before_cut es largo (era muy consistente)
        if div_history["consecutive_before_cut"] >= 8:
            score += 3  # Bonus por consistencia pasada
            result["flags"].append(
                f"  ↳ {div_history['consecutive_before_cut']} años consecutivos antes del corte")
    elif years_actual >= 3:
        # Historial corto pero existente
        score += 10
        result["flags"].append(f"~ Historial limitado ({years_actual} años div)")
    else:
        result["flags"].append(f"✗ Sin historial de dividendos ({years_actual} años)")

    # --- Dividendo ACTUAL: bonus, nunca penalización (10 puntos bonus) ---
    max_score += 10
    bonus_threshold = cfg.FUNDAMENTAL["current_div_bonus_threshold"]
    if div_yield_pct >= bonus_threshold:
        # Aún paga dividendo → bonus
        bonus = min(10, 5 + (div_yield_pct - bonus_threshold) * 2)
        score += bonus
        result["flags"].append(f"✓ Aún paga dividendo ({div_yield_pct:.1f}%) → bonus")
    elif div_yield_pct > 0:
        score += 3  # Paga algo, pequeño bonus
        result["flags"].append(f"~ Dividendo reducido ({div_yield_pct:.1f}%) — aceptable")
    else:
        score += 0  # No penaliza, simplemente no da bonus
        result["flags"].append("~ Sin dividendo actual — puede ser temporal")

    # --- Payout (10 puntos) - solo si aplica ---
    max_score += 10
    if payout_pct is not None and div_yield_pct > 0:
        if payout_pct <= cfg.FUNDAMENTAL["max_payout_ratio"]:
            score += 10 if payout_pct < 65 else 6
            result["flags"].append(f"✓ Payout {payout_pct:.0f}%")
        else:
            score += 2  # Payout alto pero no eliminatorio
            result["flags"].append(f"⚠ Payout alto ({payout_pct:.0f}%) — vigilar")
    else:
        score += 5  # Sin dato o sin dividendo: neutral

    # --- Deuda (25 puntos) - crítica para sobrevivir al bache ---
    max_score += 25
    if debt_equity is not None:
        if debt_equity <= max_de * 0.5:
            score += 25
            result["flags"].append(f"✓ D/E bajo {debt_equity:.1f} — buena posición")
        elif debt_equity <= max_de:
            score += 15
            result["flags"].append(f"✓ D/E {debt_equity:.1f} (aceptable)")
        elif debt_equity <= max_de * 1.3:
            score += 5  # Algo alta pero no eliminatoria
            result["flags"].append(f"⚠ D/E algo alta ({debt_equity:.1f})")
        else:
            result["flags"].append(f"✗ D/E excesiva ({debt_equity:.1f}) — riesgo")
    else:
        score += 12  # Sin dato: neutral

    # --- ROE (25 puntos) - con soft floor ---
    max_score += 25
    if roe_pct is not None:
        if roe_pct >= min_roe:
            score += min(25, 15 + (roe_pct - min_roe))
            result["flags"].append(f"✓ ROE {roe_pct:.1f}%")
        elif roe_pct >= roe_soft_floor:
            # ROE deprimido pero por encima del suelo → aceptable
            score += 8
            result["flags"].append(
                f"~ ROE deprimido ({roe_pct:.1f}%) — ¿temporal?")
        elif roe_pct >= 0:
            score += 2
            result["flags"].append(f"⚠ ROE muy bajo ({roe_pct:.1f}%)")
        else:
            result["flags"].append(f"✗ ROE negativo ({roe_pct:.1f}%) — pérdidas")
    else:
        score += 12

    # --- Market cap mínimo (eliminatorio) ---
    if market_cap_m < cfg.FUNDAMENTAL["min_market_cap_millions"]:
        result["flags"].append(f"✗ Cap demasiado bajo ({market_cap_m:.0f}M)")
        result["score"] = 0
        return result

    min_avg_daily_volume = cfg.FUNDAMENTAL["min_avg_daily_volume"]
    if avg_daily_volume is not None and avg_daily_volume < min_avg_daily_volume:
        result["flags"].append(
            f"âœ— Liquidez insuficiente ({avg_daily_volume:.0f} tÃ­t./dÃ­a)")
        result["score"] = 0
        return result
    if avg_daily_volume is not None:
        result["flags"].append(f"âœ“ Liquidez media diaria {avg_daily_volume:.0f}")
    else:
        result["flags"].append("~ Liquidez media diaria N/D")

    score_adjustment = 0

    net_debt_ebitda = leverage_metrics["net_debt_ebitda"]
    max_net_debt_ebitda = overrides.get(
        "max_net_debt_ebitda",
        cfg.FUNDAMENTAL["max_net_debt_ebitda"],
    )
    if max_net_debt_ebitda is None:
        result["flags"].append("~ Net Debt/EBITDA ignorado para Financial Services")
    elif net_debt_ebitda is None:
        result["flags"].append("~ Net Debt/EBITDA N/D")
    elif net_debt_ebitda <= 0:
        score_adjustment += 6
        result["flags"].append(f"âœ“ Caja neta / Net Debt-EBITDA {net_debt_ebitda:.2f}")
    elif net_debt_ebitda <= max_net_debt_ebitda * 0.5:
        score_adjustment += 6
        result["flags"].append(f"âœ“ Net Debt/EBITDA bajo ({net_debt_ebitda:.2f})")
    elif net_debt_ebitda <= max_net_debt_ebitda:
        score_adjustment += 3
        result["flags"].append(f"âœ“ Net Debt/EBITDA aceptable ({net_debt_ebitda:.2f})")
    elif net_debt_ebitda <= max_net_debt_ebitda * 1.25:
        score_adjustment -= 3
        result["flags"].append(f"âš  Net Debt/EBITDA algo alto ({net_debt_ebitda:.2f})")
    else:
        score_adjustment -= 8
        result["flags"].append(f"âœ— Net Debt/EBITDA exigente ({net_debt_ebitda:.2f})")

    debt_change_pct = debt_change["change_pct"]
    if debt_change_pct is None:
        result["flags"].append("~ VariaciÃ³n trimestral de deuda N/D")
    elif debt_change_pct > 10:
        score_adjustment -= 6
        result["flags"].append(f"âš  Deuda +{debt_change_pct:.1f}% trimestral")
    elif debt_change_pct > 0:
        score_adjustment -= 2
        result["flags"].append(f"~ Deuda +{debt_change_pct:.1f}% trimestral")
    elif debt_change_pct <= -10:
        score_adjustment += 2
        result["flags"].append(f"âœ“ Deuda reduciÃ©ndose ({debt_change_pct:.1f}% t/t)")
    else:
        score_adjustment += 1
        result["flags"].append(f"âœ“ Deuda estable ({debt_change_pct:.1f}% t/t)")

    margin_delta_pp = margin_variation["margin_delta_pp"]
    margin_label = (
        "margen bruto" if margin_variation["margin_type"] == "gross"
        else "margen operativo"
    )
    if margin_delta_pp is None:
        result["flags"].append("~ VariaciÃ³n de mÃ¡rgenes N/D")
    elif margin_delta_pp <= -3:
        score_adjustment -= 6
        result["flags"].append(f"âš  CaÃ­da de {margin_label} ({margin_delta_pp:.1f} pp)")
    elif margin_delta_pp < 0:
        score_adjustment -= 2
        result["flags"].append(f"~ Deterioro leve de {margin_label} ({margin_delta_pp:.1f} pp)")
    elif margin_delta_pp <= 3:
        score_adjustment += 1
        result["flags"].append(f"âœ“ {margin_label.capitalize()} estable ({margin_delta_pp:.1f} pp)")
    else:
        score_adjustment += 2
        result["flags"].append(f"âœ“ Mejora de {margin_label} (+{margin_delta_pp:.1f} pp)")

    base_score = round((score / max_score) * 100) if max_score > 0 else 0
    result["metrics"]["score_adjustment_points"] = score_adjustment
    result["score"] = int(max(0, min(100, round(base_score + score_adjustment))))
    result["passed"] = result["score"] >= 35  # Umbral más bajo: aceptamos empresas en bache
    return result


def _analyze_dividend_history(dividends: list) -> dict:
    """
    Analiza el historial de dividendos buscando CALIDAD PASADA,
    no solo situación actual.
    
    Devuelve:
    - years_with_div: años con al menos un pago en los últimos 10
    - recently_cut: True si dejó de pagar en los últimos 2 años
    - peak_yield_estimated: yield máximo estimado (dividendo anual / precio medio)
    - consecutive_before_cut: años consecutivos que pagó antes del último corte
    """
    result = {
        "years_with_div": 0,
        "recently_cut": False,
        "peak_yield_estimated": 0,
        "consecutive_before_cut": 0,
    }

    if not dividends:
        return result

    try:
        current_year = datetime.now().year
        year_divs = {}  # {año: suma de dividendos}

        for d in dividends:
            date_str = d.get("Date", "")
            amount = d.get("Dividend", 0)
            if date_str and amount:
                year = int(date_str[:4])
                year_divs[year] = year_divs.get(year, 0) + amount

        if not year_divs:
            return result

        # Años con dividendo en los últimos 10
        last_10_years = range(current_year - 10, current_year + 1)
        years_paying = [y for y in last_10_years if y in year_divs]
        result["years_with_div"] = len(years_paying)

        # ¿Recorte reciente? (pagó antes pero no en últimos 1-2 años)
        paid_before = any(y in year_divs for y in range(current_year - 5, current_year - 1))
        paid_recently = (current_year in year_divs) or (current_year - 1 in year_divs)
        if paid_before and not paid_recently:
            result["recently_cut"] = True

        # También detectar reducción significativa (no solo eliminación)
        if not result["recently_cut"] and len(years_paying) >= 3:
            recent_years = sorted([y for y in years_paying if y >= current_year - 2])
            older_years = sorted([y for y in years_paying if y < current_year - 2])
            if recent_years and older_years:
                avg_recent = np.mean([year_divs[y] for y in recent_years])
                avg_older = np.mean([year_divs.get(y, 0) for y in older_years[-3:]])
                if avg_older > 0 and avg_recent < avg_older * 0.5:
                    result["recently_cut"] = True  # Reducción > 50%

        # Años consecutivos antes del corte (o hasta hoy si no hubo corte)
        consecutive = 0
        for y in range(current_year, current_year - 20, -1):
            if y in year_divs:
                consecutive += 1
            else:
                break
        # Si hubo corte, contar hacia atrás desde antes del corte
        if result["recently_cut"] and consecutive == 0:
            for y in range(current_year - 2, current_year - 20, -1):
                if y in year_divs:
                    consecutive += 1
                else:
                    break
        result["consecutive_before_cut"] = consecutive

        # Peak yield estimado (simplificado: max dividendo anual observado)
        if year_divs:
            max_annual_div = max(year_divs.values())
            result["peak_yield_estimated"] = round(max_annual_div, 2)
            # Nota: esto es dividendo absoluto, no %. El % real necesitaría
            # precio histórico que no siempre tenemos aquí.

    except Exception:
        pass

    return result


# ===========================================================================
#  ANÁLISIS DE VALORACIÓN (Capa 2)
# ===========================================================================
def _analyze_valuation_legacy(data: dict) -> dict:
    """
    Compat wrapper. Mantiene backward compatibility sin duplicar lógica.
    """
    return analyze_valuation(data)

    info = data.get("info", {})
    hist = data.get("history", {})
    result = {
        "passed": False,
        "score": 0,
        "metrics": {},
        "flags": [],
    }

    sector = info.get("sector", "Unknown")
    overrides = cfg.SECTOR_OVERRIDES.get(sector, {})

    closes = hist.get("close", [])
    highs = hist.get("high", [])
    valuation_history = data.get("valuation_history", {})
    annual_eps = data.get("annual_eps", [])
    dividends = data.get("dividends", [])
    if not closes or len(closes) < 60:
        return result

    current_price = closes[-1]

    # ── PER actual vs máximo ──
    per = info.get("trailingPE") or info.get("forwardPE")
    max_per = overrides.get("max_per", cfg.VALUATION["max_per"])
    result["metrics"]["per"] = round(per, 1) if per else None

    # ── Estimación de descuento PER (vs media implícita) ──
    # Usamos forward PE y trailing PE para estimar descuento
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    per_discount = None
    per_discount_method = None

    historical_pe_stats = _compute_historical_pe_stats(per, annual_eps, valuation_history)
    historical_avg_pe = historical_pe_stats["historical_avg_pe"]

    if historical_pe_stats["per_discount_pct"] is not None:
        per_discount = historical_pe_stats["per_discount_pct"]
        per_discount_method = historical_pe_stats["per_discount_method"]
    elif trailing_pe and forward_pe and trailing_pe > 0 and forward_pe > 0:
        # Backward compatibility: reutilizar el mÃ©todo implÃ­cito si no hay histÃ³rico real
        per_discount = ((trailing_pe - forward_pe) / trailing_pe) * 100
        per_discount_method = "trailing_vs_forward"

    result["metrics"]["historical_avg_pe"] = (
        round(historical_avg_pe, 1) if historical_avg_pe is not None else None
    )
    result["metrics"]["historical_pe_years"] = historical_pe_stats["historical_pe_years"]
    result["metrics"]["historical_eps_source"] = historical_pe_stats["historical_eps_source"]
    result["metrics"]["per_discount_method"] = per_discount_method
    result["metrics"]["per_discount_pct"] = (
        round(per_discount, 1) if per_discount is not None else None
    )

    # ── Rentabilidad por dividendo vs histórica ──
    div_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield") or 0
    div_yield_pct = div_yield * 100 if div_yield else 0
    fwd_div_yield = info.get("dividendYield", 0) or 0
    trailing_div_yield = info.get("trailingAnnualDividendYield", 0) or 0
    # Si yield actual > trailing, sugiere que el precio ha caído
    if trailing_div_yield > 0 and div_yield_pct > 0:
        yield_premium = ((div_yield_pct - (trailing_div_yield * 100)) /
                         (trailing_div_yield * 100)) * 100 if trailing_div_yield else 0
    else:
        yield_premium = 0
    result["metrics"]["div_yield_premium_pct"] = round(yield_premium, 1)

    # ── Caída desde máximo 52 semanas ──
    high_52w = info.get("fiftyTwoWeekHigh") or (max(highs[-252:]) if len(highs) >= 252 else max(highs))
    if high_52w and high_52w > 0:
        drop_from_high = ((high_52w - current_price) / high_52w) * 100
    else:
        drop_from_high = 0
    result["metrics"]["drop_from_52w_high_pct"] = round(drop_from_high, 1)

    # ── Price to Book ──
    ptb = info.get("priceToBook")
    max_ptb = overrides.get("max_price_to_book", cfg.VALUATION["max_price_to_book"])
    result["metrics"]["price_to_book"] = round(ptb, 2) if ptb else None

    # ── Distancia a media móvil 200 ──
    if len(closes) >= 200:
        sma200 = np.mean(closes[-200:])
        dist_sma200 = ((current_price - sma200) / sma200) * 100
    else:
        sma200 = np.mean(closes)
        dist_sma200 = ((current_price - sma200) / sma200) * 100
    result["metrics"]["dist_sma200_pct"] = round(dist_sma200, 1)

    # ── SCORING ──
    score = 0
    max_score = 0

    # PER (25 puntos)
    max_score += 25
    per_discount_threshold = cfg.VALUATION["per_discount_vs_historical"]
    if per is not None:
        if per < 0:
            result["flags"].append("✗ PER negativo (pérdidas)")
        elif per <= max_per:
            per_score = 15 if per < max_per * 0.6 else 10
            if per_discount is not None:
                if per_discount >= per_discount_threshold:
                    per_score += 10
                elif per_discount > 0:
                    per_score += 5
            per_score = min(25, per_score)
            score += per_score
            if historical_avg_pe is not None and per_discount is not None:
                result["flags"].append(
                    f"âœ“ PER {per:.1f} vs media 5a {historical_avg_pe:.1f} ({per_discount:.0f}% desc.)")
            elif per_discount is not None:
                result["flags"].append(
                    f"âœ“ PER {per:.1f} (desc. implÃ­cito {per_discount:.0f}% vs forward)")
            result["flags"].append(f"✓ PER {per:.1f} (max {max_per})")
        else:
            result["flags"].append(f"✗ PER alto ({per:.1f})")

    # Caída desde máximos (30 puntos - el más importante)
    max_score += 30
    min_drop = cfg.VALUATION["min_drop_from_52w_high"]
    max_drop = cfg.VALUATION["max_drop_from_52w_high"]
    if min_drop <= drop_from_high <= max_drop:
        # Más caída (dentro del rango) = más puntos
        drop_score = 15 + (drop_from_high - min_drop) / (max_drop - min_drop) * 15
        score += min(30, drop_score)
        result["flags"].append(f"✓ Caída {drop_from_high:.1f}% desde máx 52s")
    elif drop_from_high < min_drop:
        result["flags"].append(f"~ Caída insuficiente ({drop_from_high:.1f}%)")
    else:
        result["flags"].append(f"✗ Caída excesiva ({drop_from_high:.1f}%) - posible trampa")

    # Price to Book (20 puntos)
    max_score += 20
    if ptb is not None:
        if ptb <= max_ptb:
            ptb_score = 20 if ptb < 1.0 else (15 if ptb < 1.5 else 10)
            score += ptb_score
            result["flags"].append(f"✓ P/B {ptb:.2f}")
        else:
            result["flags"].append(f"✗ P/B alto ({ptb:.2f})")
    else:
        score += 10

    # Distancia a SMA200 (25 puntos)
    max_score += 25
    if dist_sma200 < -10:
        score += 25  # Muy por debajo de SMA200
        result["flags"].append(f"✓ Precio {abs(dist_sma200):.1f}% bajo SMA200")
    elif dist_sma200 < 0:
        score += 15
        result["flags"].append(f"✓ Precio bajo SMA200 ({dist_sma200:.1f}%)")
    elif dist_sma200 < 5:
        score += 8
        result["flags"].append(f"~ Precio cerca de SMA200 (+{dist_sma200:.1f}%)")
    else:
        result["flags"].append(f"✗ Precio lejos de SMA200 (+{dist_sma200:.1f}%)")

    score_adjustment = 0

    if ev_ebitda is None:
        result["flags"].append("[~] EV/EBITDA N/D")
    elif ev_ebitda <= max_ev_ebitda * 0.7:
        score_adjustment += 6
        result["flags"].append(f"[OK] EV/EBITDA muy atractivo ({ev_ebitda:.1f})")
    elif ev_ebitda <= max_ev_ebitda:
        score_adjustment += 3
        result["flags"].append(f"[OK] EV/EBITDA aceptable ({ev_ebitda:.1f})")
    elif ev_ebitda <= max_ev_ebitda * 1.25:
        score_adjustment -= 3
        result["flags"].append(f"[~] EV/EBITDA algo alto ({ev_ebitda:.1f})")
    else:
        score_adjustment -= 6
        result["flags"].append(f"[X] EV/EBITDA exigente ({ev_ebitda:.1f})")

    if drop_from_multiyear_high is None:
        result["flags"].append("[~] Caida multianual N/D")
    elif min_drop <= drop_from_multiyear_high <= (max_drop + 10):
        score_adjustment += 4
        result["flags"].append(
            f"[OK] Caida {drop_from_multiyear_high:.1f}% desde max multianual")
    elif drop_from_multiyear_high < min_drop:
        result["flags"].append(
            f"[~] Caida multianual insuficiente ({drop_from_multiyear_high:.1f}%)")
    else:
        score_adjustment -= 3
        result["flags"].append(
            f"[X] Caida multianual excesiva ({drop_from_multiyear_high:.1f}%)")

    base_score = round((score / max_score) * 100) if max_score > 0 else 0
    result["metrics"]["score_adjustment_points"] = score_adjustment
    result["score"] = int(max(0, min(100, round(base_score + score_adjustment))))
    result["passed"] = result["score"] >= 30
    return result


# ===========================================================================
#  ANÁLISIS TÉCNICO (Capa 3)
# ===========================================================================
def analyze_valuation(data: dict) -> dict:
    """
    Evalua si la empresa esta temporalmente infravalorada.
    """
    info = data.get("info", {})
    hist = data.get("history", {})
    financials = data.get("financials", {})
    quarterly_financials = data.get("quarterly_financials", {})
    quarterly_balance_sheet = data.get("quarterly_balance_sheet", {})
    result = {
        "passed": False,
        "score": 0,
        "metrics": {},
        "flags": [],
    }

    sector = info.get("sector", "Unknown")
    overrides = cfg.SECTOR_OVERRIDES.get(sector, {})

    closes = hist.get("close", [])
    highs = hist.get("high", [])
    valuation_history = data.get("valuation_history", {})
    annual_eps = data.get("annual_eps", [])
    dividends = data.get("dividends", [])
    if not closes or len(closes) < 60:
        return result

    current_price = closes[-1]

    per = info.get("trailingPE") or info.get("forwardPE")
    max_per = overrides.get("max_per", cfg.VALUATION["max_per"])
    result["metrics"]["per"] = round(per, 1) if per is not None else None

    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    per_discount = None
    per_discount_method = None

    historical_pe_stats = _compute_historical_pe_stats(per, annual_eps, valuation_history)
    historical_avg_pe = historical_pe_stats["historical_avg_pe"]
    if historical_pe_stats["per_discount_pct"] is not None:
        per_discount = historical_pe_stats["per_discount_pct"]
        per_discount_method = historical_pe_stats["per_discount_method"]
    elif trailing_pe and forward_pe and trailing_pe > 0 and forward_pe > 0:
        per_discount = ((trailing_pe - forward_pe) / trailing_pe) * 100
        per_discount_method = "trailing_vs_forward"

    result["metrics"]["historical_avg_pe"] = (
        round(historical_avg_pe, 1) if historical_avg_pe is not None else None
    )
    result["metrics"]["historical_pe_years"] = historical_pe_stats["historical_pe_years"]
    result["metrics"]["historical_eps_source"] = historical_pe_stats["historical_eps_source"]
    result["metrics"]["per_discount_method"] = per_discount_method
    result["metrics"]["per_discount_pct"] = (
        round(per_discount, 1) if per_discount is not None else None
    )

    div_yield_pct = _compute_current_dividend_yield_pct(info, current_price)

    historical_div_yield_stats = _compute_historical_dividend_yield_stats(
        div_yield_pct, dividends, valuation_history
    )
    historical_avg_div_yield_pct = historical_div_yield_stats["historical_avg_div_yield_pct"]
    yield_premium = historical_div_yield_stats["div_yield_premium_pct"]
    yield_premium_method = None

    trailing_div_yield_pct = _normalize_yield_pct(info.get("trailingAnnualDividendYield"))
    if yield_premium is not None:
        yield_premium_method = "historical_5y"
    elif trailing_div_yield_pct > 0 and div_yield_pct > 0:
        yield_premium = ((div_yield_pct - trailing_div_yield_pct) / trailing_div_yield_pct) * 100
        yield_premium_method = "current_vs_trailing"

    result["metrics"]["dividend_yield_pct"] = round(div_yield_pct, 2) if div_yield_pct > 0 else 0
    result["metrics"]["historical_avg_div_yield_pct"] = (
        round(historical_avg_div_yield_pct, 2)
        if historical_avg_div_yield_pct is not None else None
    )
    result["metrics"]["historical_div_yield_years"] = (
        historical_div_yield_stats["historical_div_yield_years"]
    )
    result["metrics"]["div_yield_premium_method"] = yield_premium_method
    result["metrics"]["div_yield_premium_pct"] = (
        round(yield_premium, 1) if yield_premium is not None else None
    )

    high_52w = info.get("fiftyTwoWeekHigh")
    if not high_52w:
        high_52w = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    result["metrics"]["high_52w"] = round(high_52w, 2) if high_52w is not None else None
    if high_52w and high_52w > 0:
        drop_from_high = ((high_52w - current_price) / high_52w) * 100
    else:
        drop_from_high = 0
    result["metrics"]["drop_from_52w_high_pct"] = round(drop_from_high, 1)

    multi_year_high = max(highs) if highs else (max(closes) if closes else None)
    if multi_year_high and multi_year_high > 0:
        drop_from_multiyear_high = ((multi_year_high - current_price) / multi_year_high) * 100
    else:
        drop_from_multiyear_high = None
    result["metrics"]["drop_from_multiyear_high_pct"] = (
        round(drop_from_multiyear_high, 1)
        if drop_from_multiyear_high is not None else None
    )

    ptb = info.get("priceToBook")
    max_ptb = overrides.get("max_price_to_book", cfg.VALUATION["max_price_to_book"])
    result["metrics"]["price_to_book"] = round(ptb, 2) if ptb is not None else None

    leverage_metrics = _compute_enterprise_value_metrics(
        info,
        financials,
        quarterly_financials,
        quarterly_balance_sheet,
    )
    ev_ebitda = leverage_metrics["ev_ebitda"]
    max_ev_ebitda = overrides.get("max_ev_ebitda", cfg.VALUATION["max_ev_ebitda"])
    result["metrics"]["ev_ebitda"] = round(ev_ebitda, 2) if ev_ebitda is not None else None
    result["metrics"]["enterprise_value"] = leverage_metrics["enterprise_value"]

    sma200 = np.mean(closes[-200:]) if len(closes) >= 200 else np.mean(closes)
    dist_sma200 = ((current_price - sma200) / sma200) * 100
    result["metrics"]["dist_sma200_pct"] = round(dist_sma200, 1)

    score = 0
    max_score = 0

    max_score += 25
    per_discount_threshold = cfg.VALUATION["per_discount_vs_historical"]
    if per is not None:
        if per < 0:
            result["flags"].append("[X] PER negativo (perdidas)")
        elif per <= max_per:
            per_score = 15 if per < max_per * 0.6 else 10
            if per_discount is not None:
                if per_discount >= per_discount_threshold:
                    per_score += 10
                elif per_discount > 0:
                    per_score += 5
            per_score = min(25, per_score)
            score += per_score

            if historical_avg_pe is not None and per_discount is not None:
                result["flags"].append(
                    f"[OK] PER {per:.1f} vs media 5a {historical_avg_pe:.1f} ({per_discount:.0f}% vs media)")
            elif per_discount is not None:
                result["flags"].append(
                    f"[OK] PER {per:.1f} (desc. implicito {per_discount:.0f}% vs forward)")
            else:
                result["flags"].append(f"[OK] PER {per:.1f} (max {max_per})")
        else:
            if historical_avg_pe is not None and per_discount is not None and \
               per_discount >= per_discount_threshold:
                score += 5
                result["flags"].append(
                    f"[~] PER {per:.1f} algo alto, pero {per_discount:.0f}% bajo media 5a")
            else:
                result["flags"].append(f"[X] PER alto ({per:.1f})")

    max_score += 15
    div_yield_threshold = cfg.VALUATION["div_yield_premium_vs_historical"]
    if historical_avg_div_yield_pct is not None and yield_premium is not None and div_yield_pct > 0:
        if yield_premium >= div_yield_threshold:
            score += 15
            result["flags"].append(
                f"[OK] Yield {div_yield_pct:.2f}% vs media 5a {historical_avg_div_yield_pct:.2f}% "
                f"(+{yield_premium:.0f}%)")
        elif yield_premium > 0:
            score += 10
            result["flags"].append(
                f"[~] Yield {div_yield_pct:.2f}% sobre media 5a (+{yield_premium:.0f}%)")
        elif yield_premium > -20:
            score += 5
            result["flags"].append(
                f"[~] Yield {div_yield_pct:.2f}% ligeramente por debajo de media 5a ({yield_premium:.0f}%)")
        else:
            result["flags"].append(
                f"[X] Yield {div_yield_pct:.2f}% por debajo de media 5a ({yield_premium:.0f}%)")
    else:
        score += 5

    max_score += 30
    min_drop = cfg.VALUATION["min_drop_from_52w_high"]
    max_drop = cfg.VALUATION["max_drop_from_52w_high"]
    if min_drop <= drop_from_high <= max_drop:
        drop_score = 15 + (drop_from_high - min_drop) / (max_drop - min_drop) * 15
        score += min(30, drop_score)
        result["flags"].append(f"[OK] Caida {drop_from_high:.1f}% desde max 52s")
    elif drop_from_high < min_drop:
        result["flags"].append(f"[~] Caida insuficiente ({drop_from_high:.1f}%)")
    else:
        result["flags"].append(f"[X] Caida excesiva ({drop_from_high:.1f}%) - posible trampa")

    max_score += 20
    if ptb is not None:
        if ptb <= max_ptb:
            ptb_score = 20 if ptb < 1.0 else (15 if ptb < 1.5 else 10)
            score += ptb_score
            result["flags"].append(f"[OK] P/B {ptb:.2f}")
        else:
            result["flags"].append(f"[X] P/B alto ({ptb:.2f})")
    else:
        score += 10

    max_score += 25
    if dist_sma200 < -10:
        score += 25
        result["flags"].append(f"[OK] Precio {abs(dist_sma200):.1f}% bajo SMA200")
    elif dist_sma200 < 0:
        score += 15
        result["flags"].append(f"[OK] Precio bajo SMA200 ({dist_sma200:.1f}%)")
    elif dist_sma200 < 5:
        score += 8
        result["flags"].append(f"[~] Precio cerca de SMA200 (+{dist_sma200:.1f}%)")
    else:
        result["flags"].append(f"[X] Precio lejos de SMA200 (+{dist_sma200:.1f}%)")

    score_adjustment = 0

    if ev_ebitda is None:
        result["flags"].append("[~] EV/EBITDA N/D")
    elif ev_ebitda <= max_ev_ebitda * 0.7:
        score_adjustment += 6
        result["flags"].append(f"[OK] EV/EBITDA muy atractivo ({ev_ebitda:.1f})")
    elif ev_ebitda <= max_ev_ebitda:
        score_adjustment += 3
        result["flags"].append(f"[OK] EV/EBITDA aceptable ({ev_ebitda:.1f})")
    elif ev_ebitda <= max_ev_ebitda * 1.25:
        score_adjustment -= 3
        result["flags"].append(f"[~] EV/EBITDA algo alto ({ev_ebitda:.1f})")
    else:
        score_adjustment -= 6
        result["flags"].append(f"[X] EV/EBITDA exigente ({ev_ebitda:.1f})")

    if drop_from_multiyear_high is None:
        result["flags"].append("[~] Caida multianual N/D")
    elif min_drop <= drop_from_multiyear_high <= (max_drop + 10):
        score_adjustment += 4
        result["flags"].append(
            f"[OK] Caida {drop_from_multiyear_high:.1f}% desde max multianual")
    elif drop_from_multiyear_high < min_drop:
        result["flags"].append(
            f"[~] Caida multianual insuficiente ({drop_from_multiyear_high:.1f}%)")
    else:
        score_adjustment -= 3
        result["flags"].append(
            f"[X] Caida multianual excesiva ({drop_from_multiyear_high:.1f}%)")

    base_score = round((score / max_score) * 100) if max_score > 0 else 0
    result["metrics"]["score_adjustment_points"] = score_adjustment
    result["score"] = int(max(0, min(100, round(base_score + score_adjustment))))
    result["passed"] = result["score"] >= 30
    return result


def _find_local_lows(values: list[float], left: int = 2, right: int = 2) -> list[int]:
    """Detecta minimos locales simples en una serie numerica."""
    if len(values) < left + right + 1:
        return []

    lows = []
    for idx in range(left, len(values) - right):
        current = values[idx]
        if current is None:
            continue
        left_values = values[idx - left:idx]
        right_values = values[idx + 1:idx + 1 + right]
        if any(v is None for v in left_values + right_values):
            continue
        if all(current <= v for v in left_values) and all(current <= v for v in right_values):
            lows.append(idx)
    return lows


def _detect_double_bottom(closes: list[float], rsi_series: pd.Series) -> dict:
    """Detecta un doble suelo básico con confirmación por RSI."""
    result = {
        "detected": False,
        "first_idx": None,
        "second_idx": None,
        "first_price": None,
        "second_price": None,
        "midpoint_high": None,
        "rsi_first": None,
        "rsi_second": None,
        "days_apart": None,
    }

    if len(closes) < 80 or len(rsi_series) < 80:
        return result

    rsi_values = [_safe_float(value) for value in rsi_series.tolist()]
    local_lows = _find_local_lows(closes)
    if len(local_lows) < 2:
        return result

    window_start = max(0, len(closes) - 120)
    recent_lows = [idx for idx in local_lows if idx >= window_start]
    if len(recent_lows) < 2:
        return result

    for second_idx in reversed(recent_lows):
        if second_idx < len(closes) - 60:
            continue
        for first_idx in reversed([idx for idx in recent_lows if idx < second_idx]):
            spacing = second_idx - first_idx
            if spacing < 15 or spacing > 90:
                continue

            first_price = closes[first_idx]
            second_price = closes[second_idx]
            if first_price <= 0 or second_price <= 0:
                continue

            distance_pct = abs(second_price - first_price) / min(first_price, second_price)
            if distance_pct > 0.03:
                continue

            midpoint_high = max(closes[first_idx:second_idx + 1])
            if midpoint_high < max(first_price, second_price) * 1.05:
                continue

            first_rsi = rsi_values[first_idx]
            second_rsi = rsi_values[second_idx]
            if first_rsi is None or second_rsi is None or second_rsi <= first_rsi:
                continue

            result.update({
                "detected": True,
                "first_idx": first_idx,
                "second_idx": second_idx,
                "first_price": round(first_price, 2),
                "second_price": round(second_price, 2),
                "midpoint_high": round(midpoint_high, 2),
                "rsi_first": round(first_rsi, 1),
                "rsi_second": round(second_rsi, 1),
                "days_apart": spacing,
            })
            return result

    return result


def _detect_trendline_break_proxy(closes: list[float], sma_short: int) -> dict:
    """Usa la pendiente de la SMA50 como proxy de ruptura de directriz bajista."""
    result = {
        "detected": False,
        "sma50_current": None,
        "sma50_past_20": None,
        "slope_pct": None,
    }

    if len(closes) < sma_short + 20:
        return result

    sma50_current = float(np.mean(closes[-sma_short:]))
    sma50_past_20 = float(np.mean(closes[-(sma_short + 20):-20]))
    if sma50_past_20 <= 0:
        return result

    slope_pct = ((sma50_current - sma50_past_20) / sma50_past_20) * 100
    detected = closes[-1] > sma50_current and sma50_current > sma50_past_20 and slope_pct > 0

    result.update({
        "detected": detected,
        "sma50_current": round(sma50_current, 2),
        "sma50_past_20": round(sma50_past_20, 2),
        "slope_pct": round(slope_pct, 2),
    })
    return result


def _detect_bullish_rsi_divergence(closes: list[float], rsi_series: pd.Series) -> dict:
    """Busca divergencia alcista RSI: precio mas bajo y RSI mas alto."""
    result = {
        "detected": False,
        "first_idx": None,
        "second_idx": None,
        "bars_apart": None,
        "price_first": None,
        "price_second": None,
        "rsi_first": None,
        "rsi_second": None,
    }

    min_window = cfg.TECHNICAL["rsi_divergence_min_window"]
    max_window = cfg.TECHNICAL["rsi_divergence_max_window"]

    if len(closes) < max_window + 5 or len(rsi_series) < max_window + 5:
        return result

    rsi_values = []
    for value in rsi_series.tolist():
        normalized = _safe_float(value)
        rsi_values.append(normalized)

    price_lows = _find_local_lows(closes)
    if len(price_lows) < 2:
        return result

    recent_limit = len(closes) - min_window
    recent_candidates = [idx for idx in price_lows if idx >= recent_limit]
    if not recent_candidates:
        return result

    for second_idx in reversed(recent_candidates):
        second_rsi = rsi_values[second_idx]
        if second_rsi is None:
            continue

        previous_candidates = [
            idx for idx in price_lows
            if min_window <= (second_idx - idx) <= max_window
        ]
        for first_idx in reversed(previous_candidates):
            first_rsi = rsi_values[first_idx]
            if first_rsi is None:
                continue

            first_price = closes[first_idx]
            second_price = closes[second_idx]
            if second_price >= first_price:
                continue
            if second_rsi <= first_rsi:
                continue

            result.update({
                "detected": True,
                "first_idx": first_idx,
                "second_idx": second_idx,
                "bars_apart": second_idx - first_idx,
                "price_first": round(first_price, 2),
                "price_second": round(second_price, 2),
                "rsi_first": round(first_rsi, 1),
                "rsi_second": round(second_rsi, 1),
            })
            return result

    return result


def analyze_technical(data: dict) -> dict:
    """
    Analiza señales técnicas: RSI, MACD, medias móviles, volumen, soportes.
    """
    hist = data.get("history", {})
    result = {
        "passed": False,
        "score": 0,
        "status": "pendiente",
        "metrics": {},
        "flags": [],
        "signals": [],
    }

    closes = hist.get("close", [])
    volumes = hist.get("volume", [])
    highs = hist.get("high", [])
    lows = hist.get("low", [])

    if len(closes) < 60:
        return result

    df = pd.DataFrame({
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
    })
    dates = hist.get("dates", [])
    weekly_df = pd.DataFrame()
    if len(dates) == len(df):
        date_index = pd.to_datetime(dates, errors="coerce")
        if not pd.isna(date_index).any():
            df.index = date_index
            weekly_df = (
                df.resample("W-FRI")
                .agg({
                    "close": "last",
                    "high": "max",
                    "low": "min",
                    "volume": "sum",
                })
                .dropna()
            )

    # ── RSI ──
    rsi_series = ta.momentum.RSIIndicator(
        df["close"], window=cfg.TECHNICAL["rsi_period"]
    ).rsi()
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50
    prev_rsi = rsi_series.iloc[-5] if len(rsi_series) > 5 else current_rsi
    current_price = closes[-1]
    result["metrics"]["rsi_14"] = round(current_rsi, 1)
    result["metrics"]["current_price"] = round(current_price, 2)

    rsi_divergence = _detect_bullish_rsi_divergence(closes, rsi_series)
    result["metrics"]["rsi_bullish_divergence"] = rsi_divergence["detected"]
    result["metrics"]["rsi_divergence_bars"] = rsi_divergence["bars_apart"]
    result["metrics"]["rsi_divergence_price_first"] = rsi_divergence["price_first"]
    result["metrics"]["rsi_divergence_price_second"] = rsi_divergence["price_second"]
    result["metrics"]["rsi_divergence_rsi_first"] = rsi_divergence["rsi_first"]
    result["metrics"]["rsi_divergence_rsi_second"] = rsi_divergence["rsi_second"]

    # ── MACD ──
    macd_indicator = ta.trend.MACD(
        df["close"],
        window_slow=cfg.TECHNICAL["macd_slow"],
        window_fast=cfg.TECHNICAL["macd_fast"],
        window_sign=cfg.TECHNICAL["macd_signal"],
    )
    macd_line = macd_indicator.macd()
    macd_signal = macd_indicator.macd_signal()
    macd_hist = macd_indicator.macd_diff()

    current_macd = macd_line.iloc[-1] if not macd_line.empty else 0
    current_signal = macd_signal.iloc[-1] if not macd_signal.empty else 0
    current_hist = macd_hist.iloc[-1] if not macd_hist.empty else 0
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0

    result["metrics"]["macd"] = round(current_macd, 4)
    result["metrics"]["macd_signal"] = round(current_signal, 4)
    result["metrics"]["macd_histogram"] = round(current_hist, 4)

    # MACD crossover detection
    macd_crossover = False
    macd_converging = False
    if len(macd_line) > 2 and len(macd_signal) > 2:
        # Cruce alcista reciente (últimas 5 sesiones)
        for i in range(-5, 0):
            if (i - 1) >= -len(macd_line):
                if macd_line.iloc[i - 1] < macd_signal.iloc[i - 1] and \
                   macd_line.iloc[i] >= macd_signal.iloc[i]:
                    macd_crossover = True
                    break
        # Histograma mejorando (convergencia)
        if current_hist > prev_hist and current_hist < 0:
            macd_converging = True

    result["metrics"]["macd_crossover"] = macd_crossover
    result["metrics"]["macd_converging"] = macd_converging

    stochastic = ta.momentum.StochasticOscillator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
        smooth_window=3,
    )
    stoch_k = stochastic.stoch()
    stoch_d = stochastic.stoch_signal()
    current_k = stoch_k.iloc[-1] if not stoch_k.empty else None
    current_d = stoch_d.iloc[-1] if not stoch_d.empty else None
    prev_k = stoch_k.iloc[-2] if len(stoch_k) > 1 else current_k
    prev_d = stoch_d.iloc[-2] if len(stoch_d) > 1 else current_d
    stochastic_bullish_turn = bool(
        current_k is not None and
        current_d is not None and
        prev_k is not None and
        prev_d is not None and
        current_k < 20 and
        prev_k < prev_d and
        current_k >= current_d
    )
    result["metrics"]["stoch_k"] = round(float(current_k), 1) if current_k is not None else None
    result["metrics"]["stoch_d"] = round(float(current_d), 1) if current_d is not None else None
    result["metrics"]["stochastic_bullish_turn"] = stochastic_bullish_turn

    weekly_macd_turning_up = False
    current_weekly_macd = None
    current_weekly_signal = None
    weekly_ma40 = None
    price_vs_ma40_weekly = None
    weekly_ma40_support = False
    if len(weekly_df) >= max(cfg.TECHNICAL["macd_slow"] + cfg.TECHNICAL["macd_signal"], 40):
        weekly_macd_indicator = ta.trend.MACD(
            weekly_df["close"],
            window_slow=cfg.TECHNICAL["macd_slow"],
            window_fast=cfg.TECHNICAL["macd_fast"],
            window_sign=cfg.TECHNICAL["macd_signal"],
        )
        weekly_macd_line = weekly_macd_indicator.macd()
        weekly_macd_signal = weekly_macd_indicator.macd_signal()
        weekly_macd_hist = weekly_macd_indicator.macd_diff()

        current_weekly_macd = _safe_float(weekly_macd_line.iloc[-1]) if not weekly_macd_line.empty else None
        current_weekly_signal = _safe_float(weekly_macd_signal.iloc[-1]) if not weekly_macd_signal.empty else None
        prev_weekly_macd = _safe_float(weekly_macd_line.iloc[-2]) if len(weekly_macd_line) > 1 else current_weekly_macd
        current_weekly_hist = _safe_float(weekly_macd_hist.iloc[-1]) if not weekly_macd_hist.empty else None
        prev_weekly_hist = _safe_float(weekly_macd_hist.iloc[-2]) if len(weekly_macd_hist) > 1 else current_weekly_hist

        weekly_macd_turning_up = bool(
            current_weekly_macd is not None and
            prev_weekly_macd is not None and
            current_weekly_hist is not None and
            prev_weekly_hist is not None and
            current_weekly_macd < 0 and
            current_weekly_macd > prev_weekly_macd and
            current_weekly_hist > prev_weekly_hist
        )

        weekly_ma40 = _safe_float(weekly_df["close"].rolling(40).mean().iloc[-1]) if len(weekly_df) >= 40 else None
        if weekly_ma40 is not None and weekly_ma40 > 0:
            price_vs_ma40_weekly = ((current_price - weekly_ma40) / weekly_ma40) * 100
            weekly_ma40_support = -10 <= price_vs_ma40_weekly <= 3

    result["metrics"]["weekly_macd"] = round(current_weekly_macd, 4) if current_weekly_macd is not None else None
    result["metrics"]["weekly_macd_signal"] = round(current_weekly_signal, 4) if current_weekly_signal is not None else None
    result["metrics"]["weekly_macd_turning_up"] = weekly_macd_turning_up
    result["metrics"]["weekly_ma40"] = round(weekly_ma40, 2) if weekly_ma40 is not None else None
    result["metrics"]["price_vs_weekly_ma40"] = round(price_vs_ma40_weekly, 1) if price_vs_ma40_weekly is not None else None
    result["metrics"]["weekly_ma40_support"] = weekly_ma40_support

    double_bottom = _detect_double_bottom(closes, rsi_series)
    result["metrics"]["base_pattern_detected"] = double_bottom["detected"]
    result["metrics"]["double_bottom_days_apart"] = double_bottom["days_apart"]
    result["metrics"]["double_bottom_first_price"] = double_bottom["first_price"]
    result["metrics"]["double_bottom_second_price"] = double_bottom["second_price"]
    result["metrics"]["double_bottom_midpoint_high"] = double_bottom["midpoint_high"]

    sma_short = cfg.TECHNICAL["sma_short"]
    sma_long = cfg.TECHNICAL["sma_long"]
    trendline_break = _detect_trendline_break_proxy(closes, sma_short)
    result["metrics"]["trendline_break"] = trendline_break["detected"]
    result["metrics"]["trendline_sma50_current"] = trendline_break["sma50_current"]
    result["metrics"]["trendline_sma50_past_20"] = trendline_break["sma50_past_20"]
    result["metrics"]["trendline_slope_pct"] = trendline_break["slope_pct"]

    # ── Medias Móviles ──
    if len(closes) >= sma_long:
        sma_s = np.mean(closes[-sma_short:])
        sma_l = np.mean(closes[-sma_long:])
        result["metrics"]["sma_50"] = round(sma_s, 2)
        result["metrics"]["sma_200"] = round(sma_l, 2)
        result["metrics"]["price_vs_sma50"] = round(
            ((current_price - sma_s) / sma_s) * 100, 1
        )
        result["metrics"]["price_vs_sma200"] = round(
            ((current_price - sma_l) / sma_l) * 100, 1
        )

        # SMA50 girando al alza
        if len(closes) >= sma_short + 10:
            sma50_prev = np.mean(closes[-(sma_short + 10):-10])
            sma50_turning_up = sma_s > sma50_prev
        else:
            sma50_turning_up = False
        result["metrics"]["sma50_turning_up"] = sma50_turning_up

    # ── Volumen ──
    if len(volumes) >= 20:
        avg_vol_20 = np.mean(volumes[-20:])
        current_vol = np.mean(volumes[-3:])  # Media últimas 3 sesiones
        vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1
        result["metrics"]["volume_ratio"] = round(vol_ratio, 2)
    else:
        vol_ratio = 1
        result["metrics"]["volume_ratio"] = 1

    # ── Soporte ──
    lookback = min(cfg.TECHNICAL["support_lookback_days"], len(lows))
    recent_lows = lows[-lookback:]
    if recent_lows:
        # Identificar niveles de soporte como mínimos locales
        support_level = _find_support(recent_lows, closes[-1])
        if support_level:
            proximity = abs(closes[-1] - support_level) / closes[-1] * 100
            result["metrics"]["support_level"] = round(support_level, 2)
            result["metrics"]["support_proximity_pct"] = round(proximity, 1)
            near_support = proximity <= cfg.TECHNICAL["support_proximity_pct"]
        else:
            near_support = False
            result["metrics"]["support_level"] = None
            result["metrics"]["support_proximity_pct"] = None
    else:
        near_support = False

    # ── SCORING TÉCNICO ──
    score = 0
    max_score = 0

    # RSI (25 puntos)
    max_score += 25
    if current_rsi <= cfg.TECHNICAL["rsi_oversold"]:
        score += 25
        result["signals"].append("🔵 RSI en sobreventa")
        result["flags"].append(f"✓ RSI {current_rsi:.0f} (sobreventa)")
    elif current_rsi <= cfg.TECHNICAL["rsi_recovery_zone"]:
        # Bonus si viene de sobreventa (RSI subiendo)
        if prev_rsi < current_rsi:
            score += 20
            result["signals"].append("🔵 RSI recuperándose de sobreventa")
        else:
            score += 12
        result["flags"].append(f"✓ RSI {current_rsi:.0f} (zona baja)")
    elif current_rsi <= 55:
        score += 5
        result["flags"].append(f"~ RSI {current_rsi:.0f} (neutral)")
    else:
        result["flags"].append(f"✗ RSI {current_rsi:.0f} (alto)")

    # Divergencia RSI (bonus)
    divergence_bonus = cfg.TECHNICAL["rsi_divergence_bonus_points"]
    max_score += divergence_bonus
    if rsi_divergence["detected"]:
        score += divergence_bonus
        result["signals"].append("🟢 Divergencia alcista RSI")
        result["flags"].append(
            f"✓ Precio {rsi_divergence['price_second']:.2f} < {rsi_divergence['price_first']:.2f} "
            f"con RSI {rsi_divergence['rsi_second']:.1f} > {rsi_divergence['rsi_first']:.1f}"
        )

    # MACD (25 puntos)
    max_score += 25
    if macd_crossover:
        score += 25
        result["signals"].append("🟢 Cruce alcista MACD")
        result["flags"].append("✓ MACD cruce alcista reciente")
    elif macd_converging:
        score += 15
        result["signals"].append("🟡 MACD convergiendo")
        result["flags"].append("✓ MACD convergiendo (histograma mejora)")
    elif current_macd > current_signal:
        score += 8
        result["flags"].append("~ MACD positivo")
    else:
        result["flags"].append("✗ MACD negativo")

    # Medias móviles (20 puntos)
    max_score += 20
    price_vs_sma200 = result["metrics"].get("price_vs_sma200", 0)
    sma50_up = result["metrics"].get("sma50_turning_up", False)

    if price_vs_sma200 < -5 and sma50_up:
        score += 20
        result["signals"].append("🟢 Bajo SMA200 con SMA50 girando")
        result["flags"].append("✓ Bajo SMA200, SMA50 girando al alza")
    elif price_vs_sma200 < 0:
        score += 12
        result["flags"].append(f"✓ Bajo SMA200 ({price_vs_sma200:.1f}%)")
    elif price_vs_sma200 < 5:
        score += 5
        result["flags"].append(f"~ Cerca de SMA200")
    else:
        result["flags"].append(f"✗ Lejos de SMA200 (+{price_vs_sma200:.1f}%)")

    # Volumen (15 puntos)
    max_score += 15
    if vol_ratio >= cfg.TECHNICAL["volume_increase_threshold"]:
        score += 15
        result["signals"].append("🟢 Volumen creciente")
        result["flags"].append(f"✓ Volumen x{vol_ratio:.1f} vs media")
    elif vol_ratio >= 1.0:
        score += 8
        result["flags"].append(f"~ Volumen normal (x{vol_ratio:.1f})")
    else:
        score += 3
        result["flags"].append(f"✗ Volumen bajo (x{vol_ratio:.1f})")

    # Soporte (15 puntos)
    max_score += 15
    if near_support:
        score += 15
        prox = result["metrics"].get("support_proximity_pct", 0)
        result["signals"].append("🟢 Cerca de soporte")
        result["flags"].append(f"✓ A {prox:.1f}% de soporte")
    else:
        score += 5

    bonus_points = 0
    if weekly_macd_turning_up:
        bonus_points += 10
        result["signals"].append("🟢 MACD semanal girando al alza")
        result["flags"].append("✓ MACD semanal bajo cero con giro alcista")

    if stochastic_bullish_turn:
        bonus_points += 6
        result["signals"].append("🟢 Estocástico sale de sobreventa")
        result["flags"].append(
            f"✓ Estocástico %K {float(current_k):.1f} cruza sobre %D {float(current_d):.1f}"
        )

    if weekly_ma40_support and price_vs_ma40_weekly is not None:
        bonus_points += 5
        result["signals"].append("🟡 Apoyo en MA40 semanal")
        result["flags"].append(f"✓ Precio vs MA40 semanal {price_vs_ma40_weekly:+.1f}%")

    if double_bottom["detected"]:
        bonus_points += 12
        result["signals"].append("🟢 base_pattern_detected")
        result["flags"].append(
            f"✓ Doble suelo confirmado en {double_bottom['days_apart']} sesiones"
        )

    if trendline_break["detected"]:
        bonus_points += 6
        result["signals"].append("🟡 trendline_break")
        result["flags"].append(
            f"✓ SMA50 sube {trendline_break['slope_pct']:+.2f}% vs hace 20 sesiones"
        )

    result["metrics"]["near_support"] = near_support
    result["metrics"]["macd_positive"] = current_macd > 0
    result["metrics"]["bonus_points"] = bonus_points
    base_score = round((score / max_score) * 100) if max_score > 0 else 0
    result["metrics"]["base_score"] = base_score
    result["score"] = int(max(0, min(100, round(base_score + bonus_points))))
    result["passed"] = result["score"] >= 25

    if result["score"] >= 70:
        result["status"] = "fuerte"
    elif result["score"] >= 45:
        result["status"] = "razonable"
    elif result["score"] >= 25:
        result["status"] = "incompleto"
    else:
        result["status"] = "sin_suelo"
        result["flags"].append("✗ Sin suelo técnico identificado")
    return result


def _find_support(lows: list, current_price: float) -> float | None:
    """
    Identifica el nivel de soporte más cercano al precio actual
    basándose en mínimos locales recurrentes.
    """
    if len(lows) < 10:
        return None

    arr = np.array(lows)
    # Encontrar mínimos locales (ventana de 5 períodos)
    local_mins = []
    for i in range(2, len(arr) - 2):
        if arr[i] <= arr[i - 1] and arr[i] <= arr[i - 2] and \
           arr[i] <= arr[i + 1] and arr[i] <= arr[i + 2]:
            local_mins.append(arr[i])

    if not local_mins:
        return min(lows)

    # Agrupar mínimos cercanos (clustering simple)
    local_mins.sort()
    clusters = []
    current_cluster = [local_mins[0]]
    for m in local_mins[1:]:
        if (m - current_cluster[-1]) / current_cluster[-1] < 0.03:  # 3% de proximidad
            current_cluster.append(m)
        else:
            clusters.append(np.mean(current_cluster))
            current_cluster = [m]
    clusters.append(np.mean(current_cluster))

    # Encontrar soporte más cercano POR DEBAJO del precio actual
    supports_below = [c for c in clusters if c < current_price]
    if supports_below:
        return max(supports_below)  # El soporte más cercano por debajo
    return None


# ===========================================================================
#  SCORING COMPUESTO
# ===========================================================================
CLASSIFICATION_ORDER = {
    "descarte": 0,
    "seguimiento": 1,
    "pendiente_confirmacion": 2,
    "entrada_escalada": 3,
    "entrada_directa": 4,
}

CLASSIFICATION_LABELS = {
    "descarte": "⚪ DESCARTE",
    "seguimiento": "🟣 SEGUIMIENTO",
    "pendiente_confirmacion": "🟠 PENDIENTE CONFIRMACIÓN",
    "vigilar": "🔵 VIGILAR",
    "oportunidad_moderada": "🟡 OPORTUNIDAD MODERADA",
    "oportunidad_fuerte": "🟢 OPORTUNIDAD FUERTE",
}

PASSING_CLASSIFICATIONS = {
    "vigilar",
    "oportunidad_moderada",
    "oportunidad_fuerte",
}

# Reglas categóricas v2 del plan operativo.
CLASSIFICATION_ORDER = {
    "descarte": 0,
    "seguimiento": 1,
    "pendiente_confirmacion": 2,
    "entrada_escalada": 3,
    "entrada_directa": 4,
}

CLASSIFICATION_LABELS = {
    "descarte": "descarte",
    "seguimiento": "seguimiento",
    "pendiente_confirmacion": "pendiente_confirmacion",
    "entrada_escalada": "entrada_escalada",
    "entrada_directa": "entrada_directa",
}

PASSING_CLASSIFICATIONS = {
    "seguimiento",
    "pendiente_confirmacion",
    "entrada_escalada",
    "entrada_directa",
}


def _score_to_classification(total_score: float) -> str:
    """Convierte el score numérico base en una clasificación ordinal."""
    if total_score >= 75:
        return "oportunidad_fuerte"
    if total_score >= 60:
        return "oportunidad_moderada"
    if total_score >= cfg.SCORING["min_total_score"]:
        return "vigilar"
    return "descarte"


def _classification_to_label(classification: str) -> str:
    """Devuelve la etiqueta visual asociada a la clasificación."""
    return CLASSIFICATION_LABELS.get(classification, "descarte")


def _classification_to_label(classification: str) -> str:
    """Devuelve la etiqueta visual asociada a la clasificación."""
    return CLASSIFICATION_LABELS.get(classification, "⚪ DESCARTE")


def _classification_to_label(classification: str) -> str:
    """Devuelve la etiqueta visual asociada a la clasificación."""
    return CLASSIFICATION_LABELS.get(classification, "descarte")


def _cap_classification(current: str, maximum_allowed: str) -> str:
    """Limita una clasificación a un máximo permitido."""
    current_rank = CLASSIFICATION_ORDER.get(current, 0)
    max_rank = CLASSIFICATION_ORDER.get(maximum_allowed, 0)
    return current if current_rank <= max_rank else maximum_allowed


def _downgrade_classification(current: str, steps: int = 1) -> str:
    """Penaliza una clasificación un número discreto de escalones."""
    current_rank = CLASSIFICATION_ORDER.get(current, 0)
    return next(
        classification
        for classification, rank in CLASSIFICATION_ORDER.items()
        if rank == max(current_rank - steps, 0)
    )


def apply_hard_rules(layers_results: dict) -> dict:
    """
    Aplica reglas duras tras el scoring base y antes de la clasificación final.
    """
    layer_1_quantitative = layers_results.get("layer_1_quantitative", {})
    layer_2_causal = layers_results.get("layer_2_causal", {})
    layer_3_recovery = layers_results.get("layer_3_recovery", {})
    layer_4_technical = layers_results.get("layer_4_technical", {})
    base_classification = layers_results.get("base_classification", "descarte")
    hard_rules_applied: list[str] = []
    final_classification = base_classification

    if layer_1_quantitative.get("status") == "fail":
        hard_rules_applied.append("No supera filtrado cuantitativo mínimo")
        final_classification = "descarte"

    if layer_2_causal.get("causal_classification") == "potencialmente_estructural":
        hard_rules_applied.append("Problema posiblemente estructural")
        final_classification = _cap_classification(final_classification, "seguimiento")

    if layer_3_recovery.get("recovery_status") == "ausente":
        hard_rules_applied.append("Sin señales de recuperación")
        final_classification = _cap_classification(final_classification, "pendiente_confirmacion")

    if layer_4_technical.get("status") == "sin_suelo":
        hard_rules_applied.append("Sin suelo técnico identificado")
        final_classification = _cap_classification(final_classification, "seguimiento")

    quarterly_debt_change_pct = _safe_float(
        layer_1_quantitative.get("fundamental", {})
        .get("metrics", {})
        .get("quarterly_debt_change_pct")
    )
    guidance_negative = any((
        layer_2_causal.get("guidance_negative") is True,
        layer_2_causal.get("guidance_status") == "negativo",
        layer_2_causal.get("guidance_classification") == "negativo",
        layer_2_causal.get("management_guidance") == "negativo",
    ))
    if (
        quarterly_debt_change_pct is not None and
        quarterly_debt_change_pct > 10 and
        guidance_negative
    ):
        hard_rules_applied.append("Deuda trimestral al alza con guidance negativo")
        final_classification = _downgrade_classification(final_classification, steps=1)

    return {
        "base_classification": base_classification,
        "final_classification": final_classification,
        "hard_rules_applied": hard_rules_applied,
        "label": _classification_to_label(final_classification),
    }


def _format_price_zone(min_value: float | None, max_value: float | None) -> str:
    """Devuelve una zona de precios legible."""
    values = [value for value in (min_value, max_value) if value is not None]
    if not values:
        return ""
    low = min(values)
    high = max(values)
    if abs(high - low) < 0.005:
        return f"{low:.2f}"
    return f"{low:.2f} - {high:.2f}"


def _update_plan_explanation(plan: dict, final_classification: str) -> dict:
    """Sincroniza la explicación corta con la clasificación final ajustada."""
    updated = dict(plan)
    updated["final_classification"] = final_classification

    for key in ("short_explanation", "summary_explanation"):
        explanation = updated.get(key)
        if not explanation:
            continue
        marker = "Clasificación:"
        if marker in explanation:
            prefix = explanation.split(marker, 1)[0].rstrip()
            updated[key] = f"{prefix} Clasificación: {final_classification}."

    return updated


RECOVERY_SIGNAL_POINTS = {
    "alta": 5,
    "media": 3,
    "baja": 1,
}


def _build_recovery_signal(signal_type: str, strength: str, evidence: str) -> dict:
    """Construye una señal de recuperación homogénea."""
    return {
        "type": signal_type,
        "strength": strength,
        "evidence": evidence,
        "points": RECOVERY_SIGNAL_POINTS.get(strength, 0),
    }


def _format_recovery_signal(signal: dict) -> str:
    """Convierte una señal de recuperación a texto legible."""
    signal_type = signal.get("type", "unknown")
    strength = signal.get("strength", "")
    evidence = signal.get("evidence", "")
    base = f"{signal_type} ({strength})" if strength else signal_type
    return f"{base}: {evidence}" if evidence else base


def _compute_margin_stabilization(quarterly_financials: dict) -> dict:
    """Compara el margen del último trimestre con el trimestre anterior."""
    for margin_type, numerator_rows in (
        ("gross", GROSS_PROFIT_ROWS),
        ("operating", OPERATING_INCOME_ROWS),
    ):
        margin_series = _compute_margin_series(quarterly_financials, numerator_rows)
        if len(margin_series) < 2:
            continue

        latest_margin = margin_series[0]["margin"]
        previous_margin = margin_series[1]["margin"]
        delta_pp = (latest_margin - previous_margin) * 100

        return {
            "margin_type": margin_type,
            "latest_margin": latest_margin,
            "previous_margin": previous_margin,
            "delta_pp": delta_pp,
            "stabilized": delta_pp > -0.5,
        }

    return {
        "margin_type": None,
        "latest_margin": None,
        "previous_margin": None,
        "delta_pp": None,
        "stabilized": False,
    }


def _extract_quarterly_eps_series(statement_data: dict) -> list[dict]:
    """Obtiene EPS trimestral desde quarterly_financials o lo deriva si es posible."""
    eps_series = _get_statement_series(statement_data, QUARTERLY_EPS_ROWS)
    if eps_series:
        return [
            {
                "date": item["date"],
                "eps": item["value"],
                "source": item["row"],
            }
            for item in eps_series
            if item.get("value") is not None
        ]

    net_income_series = _get_statement_series(statement_data, QUARTERLY_NET_INCOME_ROWS)
    shares_series = _get_statement_series(statement_data, QUARTERLY_AVERAGE_SHARES_ROWS)
    if not net_income_series or not shares_series:
        return []

    shares_by_date = {
        item["date"]: item["value"]
        for item in shares_series
        if item.get("value") not in (None, 0)
    }

    derived_series = []
    for item in net_income_series:
        shares = shares_by_date.get(item["date"])
        income = item.get("value")
        if shares in (None, 0) or income is None:
            continue
        derived_series.append({
            "date": item["date"],
            "eps": income / shares,
            "source": "derived_quarterly_eps",
        })

    return derived_series


def analyze_quantitative(data: dict) -> dict:
    """
    Agrupa fundamentales y valoracion dentro del filtrado cuantitativo.
    """
    fundamental = analyze_fundamental(data)
    valuation = analyze_valuation(data)

    quantitative_weight = (
        cfg.SCORING["weight_fundamental"] + cfg.SCORING["weight_valuation"]
    )
    weighted_score = (
        fundamental.get("score", 0) * cfg.SCORING["weight_fundamental"] +
        valuation.get("score", 0) * cfg.SCORING["weight_valuation"]
    )
    quantitative_score = (
        round(weighted_score / quantitative_weight, 1)
        if quantitative_weight > 0 else 0
    )
    quantitative_status = "pass" if quantitative_score >= 25 else "fail"

    return {
        "passed": fundamental.get("passed", False) and valuation.get("passed", False),
        "status": quantitative_status,
        "score": quantitative_score,
        "fundamental": fundamental,
        "valuation": valuation,
        "metrics": {
            "fundamental_score": fundamental.get("score", 0),
            "valuation_score": valuation.get("score", 0),
        },
        "flags": fundamental.get("flags", []) + valuation.get("flags", []),
    }


def analyze_causal(data: dict, quantitative: dict | None = None) -> dict:
    """
    Stub de clasificacion causal.
    """
    return {
        "causal_classification": "pendiente",
        "causal_confidence": 0,
        "problem_type": "desconocido",
        "justification": "Pendiente de implementar",
    }


def analyze_recovery(data: dict, quantitative: dict | None = None,
                     causal: dict | None = None) -> dict:
    """
    Evalúa señales objetivas de recuperación usando solo datos de yfinance.
    """
    info = data.get("info", {})
    quarterly_financials = data.get("quarterly_financials", {})
    quarterly_balance_sheet = data.get("quarterly_balance_sheet", {})
    annual_eps = data.get("annual_eps", [])

    fundamental_metrics = (quantitative or {}).get("fundamental", {}).get("metrics", {})
    valuation_metrics = (quantitative or {}).get("valuation", {}).get("metrics", {})

    result = {
        "recovery_status": "ausente",
        "recovery_score": 0,
        "signals": [],
        "metrics": {},
    }

    detected_signals: list[dict] = []
    total_points = 0

    margin_stabilization = _compute_margin_stabilization(quarterly_financials)
    result["metrics"]["margin_stabilization_type"] = margin_stabilization["margin_type"]
    result["metrics"]["margin_stabilization_delta_pp"] = (
        round(margin_stabilization["delta_pp"], 2)
        if margin_stabilization["delta_pp"] is not None else None
    )
    if margin_stabilization["delta_pp"] is not None and margin_stabilization["stabilized"]:
        signal = _build_recovery_signal(
            "margin_stabilization",
            "media",
            (
                f"Margen {margin_stabilization['margin_type']} "
                f"{margin_stabilization['latest_margin'] * 100:.1f}% vs "
                f"{margin_stabilization['previous_margin'] * 100:.1f}% "
                f"({margin_stabilization['delta_pp']:+.1f} pp)"
            ),
        )
        detected_signals.append(signal)
        total_points += signal["points"]

    quarterly_eps = _extract_quarterly_eps_series(quarterly_financials)
    eps_source = None
    current_eps = None
    previous_eps = None
    if len(quarterly_eps) >= 2:
        current_eps = _safe_float(quarterly_eps[0].get("eps"))
        previous_eps = _safe_float(quarterly_eps[1].get("eps"))
        eps_source = quarterly_eps[0].get("source")
    elif len(annual_eps) >= 2:
        current_eps = _safe_float(annual_eps[0].get("eps"))
        previous_eps = _safe_float(annual_eps[1].get("eps"))
        eps_source = "annual_eps_fallback"

    result["metrics"]["eps_current"] = round(current_eps, 3) if current_eps is not None else None
    result["metrics"]["eps_previous"] = round(previous_eps, 3) if previous_eps is not None else None
    result["metrics"]["eps_source"] = eps_source
    if (
        current_eps is not None and
        previous_eps is not None and
        current_eps >= previous_eps
    ):
        signal = _build_recovery_signal(
            "eps_stabilization",
            "media",
            f"EPS {current_eps:.2f} vs {previous_eps:.2f} ({eps_source})",
        )
        detected_signals.append(signal)
        total_points += signal["points"]

    debt_change = _compute_quarterly_debt_change(
        info,
        quarterly_balance_sheet,
        quarterly_financials,
    )
    result["metrics"]["debt_current"] = (
        round(debt_change["current_debt"], 0)
        if debt_change["current_debt"] is not None else None
    )
    result["metrics"]["debt_previous"] = (
        round(debt_change["previous_debt"], 0)
        if debt_change["previous_debt"] is not None else None
    )
    if (
        debt_change["current_debt"] is not None and
        debt_change["previous_debt"] is not None and
        debt_change["current_debt"] < debt_change["previous_debt"]
    ):
        signal = _build_recovery_signal(
            "debt_reduction",
            "alta",
            (
                f"Deuda {debt_change['current_debt'] / 1_000_000:.1f}M "
                f"vs {debt_change['previous_debt'] / 1_000_000:.1f}M"
            ),
        )
        detected_signals.append(signal)
        total_points += signal["points"]

    dividend_yield_pct = _safe_float(fundamental_metrics.get("dividend_yield_pct"))
    drop_from_high_pct = _safe_float(valuation_metrics.get("drop_from_52w_high_pct"))
    if dividend_yield_pct is None:
        dividend_yield_pct = _compute_current_dividend_yield_pct(info)
    if dividend_yield_pct is not None and dividend_yield_pct > 0:
        drop_text = f" con caída del {drop_from_high_pct:.1f}%" if drop_from_high_pct is not None else ""
        signal = _build_recovery_signal(
            "dividend_maintained",
            "baja",
            f"Dividendo actual {dividend_yield_pct:.2f}%{drop_text}",
        )
        detected_signals.append(signal)
        total_points += signal["points"]

    held_percent_insiders = _safe_float(info.get("heldPercentInsiders"))
    previous_insiders = (
        _safe_float(info.get("heldPercentInsidersPrevious")) or
        _safe_float(info.get("heldPercentInsidersPrior")) or
        _safe_float(info.get("heldPercentInsidersLastYear"))
    )
    result["metrics"]["held_percent_insiders"] = held_percent_insiders
    if (
        held_percent_insiders is not None and
        previous_insiders is not None and
        held_percent_insiders > previous_insiders
    ):
        signal = _build_recovery_signal(
            "insider_buying",
            "media",
            (
                f"Insiders {held_percent_insiders * 100:.2f}% "
                f"vs {previous_insiders * 100:.2f}%"
            ),
        )
        detected_signals.append(signal)
        total_points += signal["points"]

    current_price = (
        _safe_float(info.get("regularMarketPrice")) or
        _safe_float(info.get("currentPrice")) or
        _safe_float(info.get("previousClose"))
    )
    target_mean_price = _safe_float(info.get("targetMeanPrice"))
    recommendation_mean = _safe_float(info.get("recommendationMean"))
    recommendation_key = info.get("recommendationKey")
    result["metrics"]["target_mean_price"] = target_mean_price
    result["metrics"]["recommendation_mean"] = recommendation_mean
    result["metrics"]["recommendation_key"] = recommendation_key
    if (
        current_price is not None and
        current_price > 0 and
        target_mean_price is not None and
        target_mean_price > current_price * 1.2
    ):
        upside_pct = ((target_mean_price - current_price) / current_price) * 100
        evidence_parts = [f"Target {target_mean_price:.2f} vs precio {current_price:.2f} (+{upside_pct:.0f}%)"]
        if recommendation_mean is not None:
            evidence_parts.append(f"recMean {recommendation_mean:.2f}")
        if recommendation_key:
            evidence_parts.append(f"recKey {recommendation_key}")
        signal = _build_recovery_signal(
            "analyst_upgrade",
            "media",
            ", ".join(evidence_parts),
        )
        detected_signals.append(signal)
        total_points += signal["points"]

    result["signals"] = detected_signals
    result["recovery_score"] = total_points
    if total_points >= 12:
        result["recovery_status"] = "confirmada"
    elif total_points >= 6:
        result["recovery_status"] = "parcial"
    else:
        result["recovery_status"] = "ausente"

    return result


def generate_operational_plan(layer_1_quantitative: dict,
                              layer_2_causal: dict,
                              layer_3_recovery: dict,
                              layer_4_technical: dict,
                              company_name: str | None = None) -> dict:
    """
    Genera la clasificación operativa, zonas, invalidaciones y tesis resumida.
    """
    company_name = company_name or "La acción"
    quantitative_score = _safe_float(layer_1_quantitative.get("score")) or 0
    technical_score = _safe_float(layer_4_technical.get("score")) or 0
    causal_confidence = _safe_float(layer_2_causal.get("causal_confidence")) or 0
    recovery_score = _safe_float(layer_3_recovery.get("recovery_score")) or 0

    fundamental_metrics = layer_1_quantitative.get("fundamental", {}).get("metrics", {})
    valuation_metrics = layer_1_quantitative.get("valuation", {}).get("metrics", {})
    technical_metrics = layer_4_technical.get("metrics", {})

    causal_classification = layer_2_causal.get("causal_classification", "pendiente")
    recovery_status = layer_3_recovery.get("recovery_status", "ausente")
    technical_status = layer_4_technical.get("status", "pendiente")

    causal_pending = causal_classification == "pendiente"
    causal_strong = causal_pending or causal_confidence > 60
    recovery_strong = recovery_status in {"confirmada", "pendiente"}
    causal_pass = causal_pending or (
        causal_confidence >= 40 and causal_classification != "potencialmente_estructural"
    )
    recovery_pass = recovery_status in {"confirmada", "parcial", "pendiente"}

    layer_1_strong = quantitative_score > 60
    layer_1_pass = quantitative_score >= 40
    layer_4_strong = technical_status == "fuerte"
    layer_4_reasonable = technical_status in {"fuerte", "razonable"}
    layer_4_incomplete = technical_status == "incompleto"

    if not layer_1_pass:
        final_classification = "descarte"
    elif layer_1_strong and causal_strong and recovery_strong and layer_4_strong:
        final_classification = "entrada_directa"
    elif layer_1_strong and causal_strong and recovery_strong and layer_4_reasonable:
        final_classification = "entrada_escalada"
    elif layer_1_pass and causal_pass and recovery_pass and layer_4_incomplete:
        final_classification = "pendiente_confirmacion"
    elif layer_1_strong:
        final_classification = "seguimiento"
    else:
        final_classification = "descarte"

    current_price = _safe_float(technical_metrics.get("current_price"))
    support_level = _safe_float(technical_metrics.get("support_level"))
    sma_50 = _safe_float(technical_metrics.get("sma_50"))
    sma_200 = _safe_float(technical_metrics.get("sma_200"))
    high_52w = _safe_float(valuation_metrics.get("high_52w"))
    drop_from_52w_high_pct = _safe_float(valuation_metrics.get("drop_from_52w_high_pct"))

    if high_52w is None and current_price is not None and drop_from_52w_high_pct is not None and drop_from_52w_high_pct < 100:
        high_52w = current_price / (1 - (drop_from_52w_high_pct / 100))

    if current_price is not None:
        entry_zone_min = support_level if support_level is not None else current_price * 0.95
        entry_zone_max = sma_50 if sma_50 is not None and sma_50 < current_price else current_price
    else:
        entry_zone_min = support_level
        entry_zone_max = sma_50

    entry_candidates = [value for value in (entry_zone_min, entry_zone_max) if value is not None]
    if entry_candidates:
        entry_zone_min = min(entry_candidates)
        entry_zone_max = max(entry_candidates)

    exit_targets = [
        value for value in (
            sma_200,
            high_52w * 0.85 if high_52w is not None else None,
        )
        if value is not None
    ]
    if exit_targets:
        exit_zone_min = min(exit_targets)
        exit_zone_max = max(exit_targets)
    else:
        exit_zone_min = None
        exit_zone_max = None

    support_reference = support_level if support_level is not None else entry_zone_min
    invalidation_conditions = []
    if support_reference is not None:
        invalidation_conditions.append(f"Pérdida del soporte en {support_reference:.2f}")
    invalidation_conditions.extend([
        "ROE negativo durante 2 trimestres consecutivos",
        "Ampliación de capital dilutiva",
        "Recorte de rating a bono basura",
    ])

    if drop_from_52w_high_pct is None:
        estimated_horizon_months = "12-18"
    elif drop_from_52w_high_pct < 25:
        estimated_horizon_months = "6-12"
    elif drop_from_52w_high_pct <= 40:
        estimated_horizon_months = "12-18"
    else:
        estimated_horizon_months = "18-24"

    roe_pct = _safe_float(fundamental_metrics.get("roe_pct"))
    debt_to_equity = _safe_float(fundamental_metrics.get("debt_to_equity"))
    net_debt_ebitda = _safe_float(fundamental_metrics.get("net_debt_ebitda"))
    dividend_yield_pct = _safe_float(fundamental_metrics.get("dividend_yield_pct"))

    if quantitative_score > 60:
        fundamental_view = "sólida"
    elif quantitative_score >= 40:
        fundamental_view = "aceptable"
    else:
        fundamental_view = "débil"

    key_metrics = []
    if roe_pct is not None:
        key_metrics.append(f"ROE {roe_pct:.1f}%")
    if net_debt_ebitda is not None:
        key_metrics.append(f"deuda neta/EBITDA {net_debt_ebitda:.1f}x")
    elif debt_to_equity is not None:
        key_metrics.append(f"D/E {debt_to_equity:.2f}")
    if dividend_yield_pct is not None and dividend_yield_pct > 0:
        key_metrics.append(f"dividendo {dividend_yield_pct:.1f}%")
    key_metrics_text = ", ".join(key_metrics[:2]) if key_metrics else "métricas mixtas"

    technical_signals = layer_4_technical.get("signals", [])
    if technical_signals:
        technical_text = ", ".join(technical_signals[:2])
    elif technical_status == "sin_suelo":
        technical_text = "sin suelo técnico identificado"
    elif technical_status == "razonable":
        technical_text = "con timing razonable pero aún sin gatillo pleno"
    elif technical_status == "incompleto":
        technical_text = "con señales incipientes pero confirmación incompleta"
    else:
        technical_text = "sin confirmación técnica suficiente"

    drop_text = f"{drop_from_52w_high_pct:.1f}%" if drop_from_52w_high_pct is not None else "N/D"
    short_explanation = (
        f"{company_name} está un {drop_text} por debajo de su máximo 52s. "
        f"Fundamentalmente {fundamental_view} con {key_metrics_text}. "
        f"Técnicamente {technical_text}. "
        f"Clasificación: {final_classification}."
    )

    return {
        "final_classification": final_classification,
        "entry_zone_min": round(entry_zone_min, 2) if entry_zone_min is not None else None,
        "entry_zone_max": round(entry_zone_max, 2) if entry_zone_max is not None else None,
        "entry_zone": _format_price_zone(entry_zone_min, entry_zone_max),
        "exit_zone_min": round(exit_zone_min, 2) if exit_zone_min is not None else None,
        "exit_zone_max": round(exit_zone_max, 2) if exit_zone_max is not None else None,
        "exit_zone": _format_price_zone(exit_zone_min, exit_zone_max),
        "invalidation_conditions": invalidation_conditions,
        "estimated_horizon_months": estimated_horizon_months,
        "short_explanation": short_explanation,
        "summary_explanation": short_explanation,
    }


def compute_composite_score(layer_1_quantitative: dict, layer_2_causal: dict,
                            layer_3_recovery: dict, layer_4_technical: dict,
                            layer_5_operational_plan: dict) -> dict:
    """
    Calcula score final ponderado y aplica reglas duras sobre la clasificación.
    """
    w = cfg.SCORING
    fundamental = layer_1_quantitative.get("fundamental", {})
    valuation = layer_1_quantitative.get("valuation", {})
    technical = layer_4_technical
    f_score = fundamental.get("score", 0)
    v_score = valuation.get("score", 0)
    t_score = technical.get("score", 0)

    total = (
        f_score * w["weight_fundamental"] +
        v_score * w["weight_valuation"] +
        t_score * w["weight_technical"]
    )
    total = round(total, 1)

    # Señales técnicas acumuladas
    signals = technical.get("signals", [])
    base_classification = layer_5_operational_plan.get("final_classification", "descarte")
    hard_rules_result = apply_hard_rules({
        "layer_1_quantitative": layer_1_quantitative,
        "layer_2_causal": layer_2_causal,
        "layer_3_recovery": layer_3_recovery,
        "layer_4_technical": layer_4_technical,
        "layer_5_operational_plan": layer_5_operational_plan,
        "base_classification": base_classification,
    })
    final_classification = hard_rules_result["final_classification"]

    return {
        "total_score": total,
        "quantitative_score": layer_1_quantitative.get("score", 0),
        "fundamental_score": f_score,
        "valuation_score": v_score,
        "causal_score": layer_2_causal.get("causal_confidence", 0),
        "recovery_score": layer_3_recovery.get("recovery_score", 0),
        "technical_score": t_score,
        "operational_plan_status": final_classification,
        "base_classification": base_classification,
        "final_classification": final_classification,
        "label": hard_rules_result["label"],
        "hard_rules_applied": hard_rules_result["hard_rules_applied"],
        "signals": signals,
        "passed": final_classification in PASSING_CLASSIFICATIONS,
    }


# ===========================================================================
#  ANÁLISIS COMPLETO DE UN TICKER
# ===========================================================================
def analyze_ticker(ticker: str) -> dict | None:
    """Pipeline completo para un ticker."""
    data = fetch_ticker_data(ticker)
    if data is None:
        return None
    return _build_ticker_result(ticker, data)


# ===========================================================================
#  EJECUCIÓN PRINCIPAL
# ===========================================================================
def analyze_ticker_with_status(ticker: str) -> tuple[dict | None, str | None]:
    """Pipeline completo para un ticker, devolviendo tambien el error si falla."""
    data, fetch_error = fetch_ticker_data_with_status(ticker)
    if data is None:
        return None, fetch_error or "No data returned"

    try:
        return _build_ticker_result(ticker, data), None
    except Exception as error:
        return None, _format_error_message(error)


def _run_analysis_layers(data: dict) -> dict:
    """
    Ejecuta las 5 capas del analisis en orden.
    """
    info = data.get("info", {})
    company_name = info.get("shortName") or info.get("longName") or "La acción"
    layer_1_quantitative = analyze_quantitative(data)
    layer_2_causal = analyze_causal(data, layer_1_quantitative)
    layer_3_recovery = analyze_recovery(data, layer_1_quantitative, layer_2_causal)
    layer_4_technical = analyze_technical(data)
    layer_5_operational_plan = generate_operational_plan(
        layer_1_quantitative,
        layer_2_causal,
        layer_3_recovery,
        layer_4_technical,
        company_name,
    )
    composite = compute_composite_score(
        layer_1_quantitative,
        layer_2_causal,
        layer_3_recovery,
        layer_4_technical,
        layer_5_operational_plan,
    )
    layer_5_operational_plan = _update_plan_explanation(
        layer_5_operational_plan,
        composite.get("final_classification", "descarte"),
    )

    return {
        "layer_1_quantitative": layer_1_quantitative,
        "layer_2_causal": layer_2_causal,
        "layer_3_recovery": layer_3_recovery,
        "layer_4_technical": layer_4_technical,
        "layer_5_operational_plan": layer_5_operational_plan,
        # Compatibilidad con la estructura anterior
        "fundamental": layer_1_quantitative.get("fundamental", {}),
        "valuation": layer_1_quantitative.get("valuation", {}),
        "technical": layer_4_technical,
        "composite": composite,
    }


def _build_ticker_result(ticker: str, data: dict) -> dict:
    """Compone el resultado final del ticker con las 5 capas."""
    info = data.get("info", {})
    layers = _run_analysis_layers(data)
    versioning = get_versioning_metadata()

    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName", ticker),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "country": info.get("country", "N/A"),
        "currency": info.get("currency", "N/A"),
        "price": info.get("regularMarketPrice") or info.get("currentPrice")
                 or info.get("previousClose"),
        "price_history": data.get("history", {}),
        "rules_version": versioning.get("rules_version"),
        "model_version": versioning.get("model_version"),
        "config_version": versioning.get("config_version"),
        "evaluation_timestamp": datetime.now().astimezone().isoformat(),
        **layers,
    }


def run_screener(markets: list[str] | None = None):
    """Ejecuta el screener completo."""

    console.print(Panel.fit(
        "[bold cyan]STOCK OPPORTUNITY SCREENER v1.0[/bold cyan]\n"
        "Detector de valor temporal deprimido\n"
        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        border_style="cyan"
    ))

    # Construir universo de tickers
    active = markets or cfg.ACTIVE_MARKETS
    all_tickers = []
    for market_name in active:
        tickers = cfg.MARKETS.get(market_name, [])
        all_tickers.extend([(t, market_name) for t in tickers])
        console.print(f"  📊 {market_name}: {len(tickers)} tickers")

    console.print(f"\n  [bold]Total: {len(all_tickers)} tickers a analizar[/bold]\n")

    # Analizar con progreso
    results = []
    failed = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analizando...", total=len(all_tickers))

        with ThreadPoolExecutor(max_workers=cfg.EXECUTION["max_workers"]) as executor:
            future_map = {}
            for ticker, market in all_tickers:
                future = executor.submit(analyze_ticker_with_status, ticker)
                future_map[future] = (ticker, market)

            for future in as_completed(future_map):
                ticker, market = future_map[future]
                try:
                    result, error = future.result()
                    if result:
                        result["market"] = market
                        results.append(result)
                    else:
                        failed.append({
                            "ticker": ticker,
                            "market": market,
                            "error": error or "Unknown analysis error",
                        })
                except Exception as error:
                    failed.append({
                        "ticker": ticker,
                        "market": market,
                        "error": _format_error_message(error),
                    })
                progress.update(task, advance=1,
                                description=f"Analizando {ticker}...")

    # Filtrar y ordenar resultados
    passed = [r for r in results if r["composite"]["passed"]]
    passed.sort(key=lambda x: x["composite"]["total_score"], reverse=True)

    # Mostrar resultados
    _display_results(passed, failed, results)

    # Exportar
    _export_results(passed, results, failed)
    generated_alerts = _persist_results_to_database(results)
    _export_alerts(generated_alerts)
    _display_generated_alerts(generated_alerts)

    return passed


def _persist_results_to_database(results: list[dict]) -> list[dict]:
    """Guarda el historial de evaluaciones en SQLite sin romper el flujo principal."""
    try:
        database.init_db()
        for result in results:
            database.save_evaluation(result)
    except Exception as error:
        console.print(
            f"  [yellow]Aviso SQLite: no se pudo persistir el historial ({error})[/yellow]"
        )
        return

    console.print(
        f"  💾 SQLite: [bold]{database.DB_PATH}[/bold] "
        f"({len(results)} evaluaciones guardadas)"
    )


def _display_results(passed: list, failed: list, all_results: list):
    """Muestra resultados en consola con Rich."""
    console.print(f"\n{'='*80}")
    console.print(
        f"  [bold green]RESULTADOS: {len(passed)} oportunidades detectadas[/bold green] "
        f"(de {len(all_results)} analizadas, {len(failed)} fallidas)"
    )
    console.print(f"{'='*80}\n")

    if failed:
        failed_table = Table(
            title="Fallos de analisis",
            box=box.SIMPLE,
            title_style="bold yellow",
        )
        failed_table.add_column("Ticker", style="bold", width=10)
        failed_table.add_column("Mercado", width=10)
        failed_table.add_column("Error", overflow="fold")

        for item in failed[:10]:
            failed_table.add_row(
                item.get("ticker", ""),
                item.get("market", ""),
                item.get("error", ""),
            )
        console.print(failed_table)

    if not passed:
        console.print("[yellow]No se encontraron oportunidades con la clasificación actual.[/yellow]")
        console.print("Considera relajar los umbrales en config.py")
        return

    table = Table(
        title="TOP OPORTUNIDADES",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("Rank", justify="center", width=4)
    table.add_column("Ticker", style="bold", width=10)
    table.add_column("Nombre", width=24)
    table.add_column("Mercado", width=8)
    table.add_column("Precio", justify="right", width=10)
    table.add_column("Clasif.", width=23)
    table.add_column("Score", justify="center", width=7)
    table.add_column("Señal", width=18)

    top_n = cfg.OUTPUT["top_n_results"]
    for i, r in enumerate(passed[:top_n], 1):
        comp = r["composite"]
        score = comp["total_score"]
        if score >= 75:
            score_str = f"[bold green]{score:.0f}[/bold green]"
        elif score >= 60:
            score_str = f"[bold yellow]{score:.0f}[/bold yellow]"
        else:
            score_str = f"[cyan]{score:.0f}[/cyan]"

        signals = " ".join(comp.get("signals", [])[:2]) or "-"
        price = r.get("price")
        price_str = f"{price:.2f}" if price else "N/A"

        table.add_row(
            str(i),
            r["ticker"],
            (r["name"] or "")[:24],
            r.get("market", ""),
            price_str,
            comp.get("final_classification", "descarte"),
            score_str,
            signals[:18],
        )

    console.print(table)

    console.print(f"\n{'─'*80}")
    console.print("[bold]DETALLE TOP 10[/bold]\n")

    for i, r in enumerate(passed[:10], 1):
        comp = r["composite"]
        l5 = r.get("layer_5_operational_plan", {})
        console.print(
            f"[bold]{i}. {r['ticker']} - {r['name']}[/bold] "
            f"({r.get('sector', 'N/A')}, {r.get('country', 'N/A')})"
        )
        console.print(
            f"   Clasificación: {comp.get('final_classification', 'descarte')}  |  "
            f"Score: {comp['total_score']:.0f}/100"
        )
        console.print(
            f"   Precio: {r.get('price', 'N/A')}  |  Moneda: {r.get('currency', 'N/A')}"
        )
        console.print(
            f"   Entrada: {l5.get('entry_zone', 'N/A')}  |  "
            f"Salida: {l5.get('exit_zone', 'N/A')}  |  "
            f"Horizonte: {l5.get('estimated_horizon_months', 'N/A')} meses"
        )

        fm = r["fundamental"].get("metrics", {})
        vm = r["valuation"].get("metrics", {})
        tm = r["technical"].get("metrics", {})

        console.print(
            f"   [dim]Fund:[/dim] DivActual={fm.get('dividend_yield_pct', 'N/A')}%  "
            f"HistDiv={fm.get('div_years_in_last_10', 'N/A')}/10años  "
            f"Recorte={'SÍ' if fm.get('div_was_cut_recently') else 'NO'}  "
            f"ROE={fm.get('roe_pct', 'N/A')}%  "
            f"D/E={fm.get('debt_to_equity', 'N/A')}"
        )
        console.print(
            f"   [dim]Valor:[/dim] PER={vm.get('per', 'N/A')}  "
            f"P/B={vm.get('price_to_book', 'N/A')}  "
            f"Caída 52s={vm.get('drop_from_52w_high_pct', 'N/A')}%  "
            f"vs SMA200={vm.get('dist_sma200_pct', 'N/A')}%"
        )
        console.print(
            f"   [dim]Técn:[/dim] RSI={tm.get('rsi_14', 'N/A')}  "
            f"MACD cruce={'SÍ' if tm.get('macd_crossover') else 'NO'}  "
            f"Vol x{tm.get('volume_ratio', 'N/A')}"
        )

        if l5.get("short_explanation"):
            console.print(f"   [dim]Tesis:[/dim] {l5['short_explanation']}")
        if comp.get("signals"):
            console.print(f"   [bold]Señales: {' | '.join(comp['signals'])}[/bold]")
        if l5.get("invalidation_conditions"):
            console.print(
                f"   [dim]Invalidación:[/dim] "
                f"{' | '.join(l5['invalidation_conditions'][:2])}"
            )
        if comp.get("hard_rules_applied"):
            console.print(
                f"   [dim]Hard rules:[/dim] {' | '.join(comp['hard_rules_applied'])}"
            )
        console.print()


REPORT_METRIC_LABELS = {
    "dividend_yield_pct": "Dividend yield actual",
    "div_years_in_last_10": "Anos con dividendo en ultimos 10",
    "div_was_cut_recently": "Recorte reciente",
    "peak_yield_estimated": "Pico historico de dividendo estimado",
    "consecutive_div_years_before_cut": "Anos consecutivos antes del corte",
    "payout_ratio_pct": "Payout actual",
    "debt_to_equity": "Deuda / Equity",
    "roe_pct": "ROE",
    "market_cap_millions": "Capitalizacion",
    "avg_daily_volume": "Volumen medio diario",
    "net_debt": "Deuda neta",
    "net_debt_ebitda": "Deuda neta / EBITDA",
    "quarterly_debt_change_pct": "Variacion deuda trimestral",
    "margin_type": "Tipo de margen",
    "current_margin_pct": "Margen actual",
    "avg_last_4q_margin_pct": "Margen medio ultimos 4T",
    "margin_delta_pp": "Variacion margen",
    "score_adjustment_points": "Ajuste de score",
    "per": "PER",
    "historical_pe_avg": "PER historico medio",
    "pe_discount_vs_historical_pct": "Descuento vs PER historico",
    "price_to_book": "Price to Book",
    "ev_ebitda": "EV / EBITDA",
    "drop_from_52w_high_pct": "Caida desde maximo 52s",
    "drop_from_multiyear_high_pct": "Caida desde maximo multianual",
    "dist_sma200_pct": "Distancia a SMA200",
    "high_52w": "Maximo 52 semanas",
    "multiyear_high": "Maximo multianual",
}


def _slugify_filename(value: str) -> str:
    """Normaliza nombres de archivo sin depender de caracteres especiales."""
    text = str(value or "").strip()
    allowed = []
    for char in text:
        if char.isalnum():
            allowed.append(char)
        elif char in {"-", "_"}:
            allowed.append(char)
        else:
            allowed.append("_")
    normalized = "".join(allowed).strip("_")
    return normalized or "empresa"


def _humanize_metric_key(key: str) -> str:
    """Convierte claves internas en etiquetas legibles para la ficha."""
    if key in REPORT_METRIC_LABELS:
        return REPORT_METRIC_LABELS[key]

    label = key.replace("_pct", " pct").replace("_pp", " pp").replace("_", " ")
    return label.capitalize()


def _format_metric_value(key: str, value: object) -> str:
    """Formatea metricas para markdown sin perder contexto."""
    if value is None or value == "":
        return "N/D"

    if isinstance(value, bool):
        return "Si" if value else "No"

    if key == "margin_type":
        mapping = {"gross": "bruto", "operating": "operativo"}
        return mapping.get(str(value), str(value))

    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        numeric = float(value)
        if key.endswith("_pct"):
            return f"{numeric:.2f}%"
        if key.endswith("_pp"):
            return f"{numeric:.2f} pp"
        if key.endswith("_millions"):
            return f"{numeric:,.0f} M".replace(",", ".")
        if key in {"avg_daily_volume", "net_debt", "high_52w", "multiyear_high"}:
            return f"{numeric:,.2f}".rstrip("0").rstrip(".").replace(",", ".")
        return f"{numeric:.2f}".rstrip("0").rstrip(".")

    return str(value)


def _render_metric_lines(metrics: dict, prefix: str) -> list[str]:
    """Serializa todas las metricas de una capa en formato bullet."""
    if not metrics:
        return [f"- {prefix}: sin metricas disponibles."]

    lines = []
    for key, value in metrics.items():
        lines.append(
            f"- {prefix} | {_humanize_metric_key(key)}: {_format_metric_value(key, value)}"
        )
    return lines


def _format_recovery_signal_for_report(signal: dict) -> str:
    """Convierte una senal de recuperacion en una linea legible."""
    signal_type = str(signal.get("type", "signal")).replace("_", " ")
    strength = signal.get("strength", "N/D")
    evidence = signal.get("evidence", "Sin evidencia detallada")
    return f"- {signal_type} ({strength}): {evidence}"


def _looks_negative_flag(text: str) -> bool:
    """Heuristica simple para identificar flags de riesgo."""
    sample = str(text or "").strip().lower()
    if not sample:
        return False

    negative_markers = [
        "✗", "âœ—", "⚠", "Ã¢Å¡Â ", "sin suelo", "negativo",
        "insuficiente", "deterioro", "caida", "caída", "lejos",
        "alto", "bajo", "ausente", "recorte", "problema",
        "deuda +", "no supera", "warning",
    ]
    return any(marker in sample for marker in negative_markers)


def _collect_negative_risks(result: dict) -> list[str]:
    """Agrupa flags negativos y reglas duras para la ficha."""
    l1 = result.get("layer_1_quantitative", {})
    l2 = result.get("layer_2_causal", {})
    l3 = result.get("layer_3_recovery", {})
    l4 = result.get("layer_4_technical", {})
    comp = result.get("composite", {})

    collected: list[str] = []

    for flag in l1.get("fundamental", {}).get("flags", []):
        if _looks_negative_flag(flag):
            collected.append(f"Capa 1: {flag}")
    for flag in l1.get("valuation", {}).get("flags", []):
        if _looks_negative_flag(flag):
            collected.append(f"Capa 1: {flag}")
    for flag in l4.get("flags", []):
        if _looks_negative_flag(flag):
            collected.append(f"Capa 4: {flag}")

    causal_classification = l2.get("causal_classification")
    if causal_classification and causal_classification not in {"pendiente", "temporal"}:
        justification = l2.get("justification") or causal_classification
        collected.append(f"Capa 2: {justification}")

    recovery_status = l3.get("recovery_status")
    if recovery_status == "ausente":
        collected.append("Capa 3: Sin senales objetivas de recuperacion")
    elif recovery_status == "parcial":
        collected.append("Capa 3: Recuperacion solo parcial")

    for reason in comp.get("hard_rules_applied", []):
        collected.append(f"Hard rule: {reason}")

    deduped: list[str] = []
    seen = set()
    for item in collected:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def generate_company_report(result: dict) -> str:
    """Genera una ficha Markdown individual para una empresa."""
    comp = result.get("composite", {})
    l1 = result.get("layer_1_quantitative", {})
    l3 = result.get("layer_3_recovery", {})
    l4 = result.get("layer_4_technical", {})
    l5 = result.get("layer_5_operational_plan", {})

    fundamental = l1.get("fundamental", {})
    valuation = l1.get("valuation", {})
    fm = fundamental.get("metrics", {})
    vm = valuation.get("metrics", {})
    technical_signals = l4.get("signals", [])
    technical_flags = l4.get("flags", [])
    recovery_signals = l3.get("signals", [])

    ticker = result.get("ticker", "N/D")
    name = result.get("name", ticker)
    classification = comp.get("final_classification", "descarte")
    total_score = comp.get("total_score", 0)
    price_text = _format_metric_value("price", result.get("price"))
    currency = result.get("currency", "N/D")

    entry_zone = l5.get("entry_zone") or _format_price_zone(
        l5.get("entry_zone_min"),
        l5.get("entry_zone_max"),
    ) or "N/D"
    exit_zone = l5.get("exit_zone") or _format_price_zone(
        l5.get("exit_zone_min"),
        l5.get("exit_zone_max"),
    ) or "N/D"
    horizon = l5.get("estimated_horizon_months")
    horizon_text = f"{horizon} meses" if horizon else "N/D"

    report_lines = [
        "---",
        f"## {ticker} - {name}",
        f"**Clasificacion: {classification}** | Score: {total_score}/100",
        (
            f"**Sector:** {result.get('sector', 'N/D')} | "
            f"**Pais:** {result.get('country', 'N/D')} | "
            f"**Precio:** {price_text} {currency}"
        ),
        "",
        "### Diagnostico cuantitativo",
        f"- Score Capa 1: {l1.get('score', 'N/D')} / 100",
        f"- Estado Capa 1: {l1.get('status', 'N/D')}",
    ]
    report_lines.extend(_render_metric_lines(fm, "Fundamental"))
    report_lines.append(
        f"- Flags fundamentales: {' | '.join(fundamental.get('flags', [])) or 'Sin flags'}"
    )
    report_lines.extend(_render_metric_lines(vm, "Valoracion"))
    report_lines.append(
        f"- Flags valoracion: {' | '.join(valuation.get('flags', [])) or 'Sin flags'}"
    )

    report_lines.extend([
        "",
        "### Senales de recuperacion",
        f"- Estado recuperacion: {l3.get('recovery_status', 'N/D')}",
        f"- Score recuperacion: {l3.get('recovery_score', 'N/D')}",
    ])
    if recovery_signals:
        report_lines.extend(
            _format_recovery_signal_for_report(signal) for signal in recovery_signals
        )
    else:
        report_lines.append("- Sin senales de recuperacion objetivas detectadas.")

    report_lines.extend([
        "",
        "### Lectura tecnica",
        f"- Estado tecnico: {l4.get('status', 'N/D')}",
        f"- Score tecnico: {l4.get('score', 'N/D')} / 100",
    ])
    if technical_signals:
        report_lines.extend(f"- {signal}" for signal in technical_signals)
    elif technical_flags:
        report_lines.extend(f"- {flag}" for flag in technical_flags[:5])
    else:
        report_lines.append("- Sin senales tecnicas positivas detectadas.")

    report_lines.extend([
        "",
        "### Plan operativo",
        f"- Zona entrada: {entry_zone}",
        f"- Zona salida: {exit_zone}",
        f"- Horizonte: {horizon_text}",
        (
            f"- Invalidacion: "
            f"{' | '.join(l5.get('invalidation_conditions', [])) or 'N/D'}"
        ),
        "",
        "### Tesis resumida",
        l5.get("short_explanation") or "Sin tesis resumida disponible.",
        "",
        "### Riesgos",
    ])

    risk_lines = _collect_negative_risks(result)
    if risk_lines:
        report_lines.extend(f"- {risk}" for risk in risk_lines)
    else:
        report_lines.append("- No se detectan flags negativos relevantes en esta evaluacion.")

    report_lines.extend(["---", ""])
    return "\n".join(report_lines)


def _export_company_reports(passed: list, results_dir: Path, timestamp: str) -> None:
    """Genera fichas Markdown individuales y un resumen consolidado."""
    if not passed:
        return

    top_n = min(cfg.OUTPUT["top_n_results"], len(passed))
    report_dir = results_dir / f"fichas_{timestamp}"
    report_dir.mkdir(exist_ok=True)

    consolidated_reports = ["# Fichas resumen", ""]
    for rank, result in enumerate(passed[:top_n], 1):
        report_body = generate_company_report(result)
        filename = f"{rank:02d}_{_slugify_filename(result.get('ticker', 'empresa'))}.md"
        report_path = report_dir / filename
        report_path.write_text(report_body, encoding="utf-8")
        consolidated_reports.append(report_body.rstrip())
        consolidated_reports.append("")

    summary_path = report_dir / "fichas_resumen.md"
    summary_path.write_text("\n".join(consolidated_reports).rstrip() + "\n", encoding="utf-8")

    console.print(f"  ðŸ“ Fichas: [bold]{report_dir}[/bold]")
    console.print(f"  ðŸ“ Resumen fichas: [bold]{summary_path}[/bold]")


def _build_price_history_dataframe(history_payload: dict) -> pd.DataFrame:
    """Convierte el historico serializado del ticker en un DataFrame exportable."""
    if not isinstance(history_payload, dict):
        return pd.DataFrame()

    dates = history_payload.get("dates", [])
    closes = history_payload.get("close", [])
    opens = history_payload.get("open", [])
    highs = history_payload.get("high", [])
    lows = history_payload.get("low", [])
    volumes = history_payload.get("volume", [])

    if not dates or not closes or len(dates) != len(closes):
        return pd.DataFrame()

    row_count = len(dates)

    def _normalize_series(values: list) -> list:
        if not isinstance(values, list) or len(values) != row_count:
            return [None] * row_count
        return values

    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(dates, errors="coerce"),
            "Open": pd.to_numeric(_normalize_series(opens), errors="coerce"),
            "High": pd.to_numeric(_normalize_series(highs), errors="coerce"),
            "Low": pd.to_numeric(_normalize_series(lows), errors="coerce"),
            "Close": pd.to_numeric(closes, errors="coerce"),
            "Volume": pd.to_numeric(_normalize_series(volumes), errors="coerce"),
        }
    )
    df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
    if df.empty:
        return df

    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    return df


def _safe_ticker_filename(ticker: str) -> str:
    """Genera un nombre de fichero seguro en Windows para un ticker."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(ticker or "").strip())
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return "ticker"

    stem = cleaned.split(".")[0].upper()
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    if stem in reserved:
        cleaned = f"ticker_{cleaned}"

    return cleaned


def _export_price_history_files(passed: list, results_dir: Path) -> None:
    """Exporta historicos diarios por ticker para uso del dashboard cloud."""
    if not passed:
        return

    history_dir = results_dir / "price_history"
    history_dir.mkdir(exist_ok=True)
    exported_count = 0

    for result in passed:
        ticker = result.get("ticker")
        if not ticker:
            continue

        history_payload = result.get("price_history", {})
        history_df = _build_price_history_dataframe(history_payload)
        if history_df.empty:
            continue

        path = history_dir / f"{_safe_ticker_filename(ticker)}.csv"
        history_df.to_csv(path, index=False)
        exported_count += 1

    if exported_count:
        console.print(
            f"  Historicos precio: [bold]{history_dir}[/bold] "
            f"({exported_count} tickers)"
        )


def _export_results(passed: list, all_results: list, failed: list):
    """Exporta resultados a Excel y/o CSV."""

    results_dir = Path(cfg.OUTPUT["results_dir"])
    results_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    versioning = get_versioning_metadata()

    rows = []
    for r in passed:
        comp = r["composite"]
        l1 = r.get("layer_1_quantitative", {})
        l2 = r.get("layer_2_causal", {})
        l3 = r.get("layer_3_recovery", {})
        l4 = r.get("layer_4_technical", {})
        l5 = r.get("layer_5_operational_plan", {})
        fm = r["fundamental"].get("metrics", {})
        vm = r["valuation"].get("metrics", {})
        tm = l4.get("metrics", {})

        rows.append({
            "Rank": len(rows) + 1,
            "Ticker": r["ticker"],
            "Nombre": r.get("name", ""),
            "Mercado": r.get("market", ""),
            "Sector": r.get("sector", ""),
            "Industria": r.get("industry", ""),
            "País": r.get("country", ""),
            "Moneda": r.get("currency", ""),
            "Precio": r.get("price"),
            "Rules_Version": r.get("rules_version", versioning.get("rules_version")),
            "Model_Version": r.get("model_version", versioning.get("model_version")),
            "Config_Version": r.get("config_version", versioning.get("config_version")),
            "Evaluation_Timestamp": r.get("evaluation_timestamp", ""),
            "Score_Total": comp["total_score"],
            "Score_Cuantitativo": comp.get("quantitative_score"),
            "Score_Fundamental": comp["fundamental_score"],
            "Score_Valoracion": comp["valuation_score"],
            "Score_Causal": comp.get("causal_score"),
            "Score_Recuperacion": comp.get("recovery_score"),
            "Score_Tecnico": comp["technical_score"],
            "Clasificacion": comp.get("final_classification"),
            "Clasificacion_Base": comp.get("base_classification"),
            "hard_rules_applied": " | ".join(comp.get("hard_rules_applied", [])),
            "Capa1_Pasa": l1.get("passed"),
            "Capa1_Status": l1.get("status"),
            "Capa2_Causal_Classification": l2.get("causal_classification"),
            "Capa2_Causal_Confidence": l2.get("causal_confidence"),
            "Capa2_Problem_Type": l2.get("problem_type"),
            "Capa2_Justification": l2.get("justification"),
            "Capa3_Recovery_Status": l3.get("recovery_status"),
            "Capa3_Recovery_Signals": " | ".join(
                _format_recovery_signal(signal) for signal in l3.get("signals", [])
            ),
            "Capa4_Status": l4.get("status"),
            "Capa5_Final_Classification": l5.get("final_classification"),
            "Capa5_Entry_Zone_Min": l5.get("entry_zone_min"),
            "Capa5_Entry_Zone_Max": l5.get("entry_zone_max"),
            "Capa5_Entry_Zone": l5.get("entry_zone"),
            "Capa5_Exit_Zone_Min": l5.get("exit_zone_min"),
            "Capa5_Exit_Zone_Max": l5.get("exit_zone_max"),
            "Capa5_Exit_Zone": l5.get("exit_zone"),
            "Capa5_Invalidation_Conditions": " | ".join(l5.get("invalidation_conditions", [])),
            "Capa5_Estimated_Horizon_Months": l5.get("estimated_horizon_months"),
            "Capa5_Short_Explanation": l5.get("short_explanation"),
            "Capa5_Summary_Explanation": l5.get("summary_explanation"),
            "Señales": " | ".join(comp.get("signals", [])),
            # Fundamentales
            "Div_Yield_Actual_%": fm.get("dividend_yield_pct"),
            "Historial_Div_Años_10": fm.get("div_years_in_last_10"),
            "Consec_Antes_Corte": fm.get("consecutive_div_years_before_cut"),
            "Recorte_Reciente": fm.get("div_was_cut_recently"),
            "Payout_%": fm.get("payout_ratio_pct"),
            "D/E": fm.get("debt_to_equity"),
            "Vol_Medio_Diario": fm.get("avg_daily_volume"),
            "Net_Debt": fm.get("net_debt"),
            "Net_Debt_EBITDA": fm.get("net_debt_ebitda"),
            "Variacion_Deuda_Trimestral_%": fm.get("quarterly_debt_change_pct"),
            "Tipo_Margen": fm.get("margin_type"),
            "Margen_Actual_%": fm.get("current_margin_pct"),
            "Margen_Medio_4T_%": fm.get("avg_last_4q_margin_pct"),
            "Variacion_Margen_pp": fm.get("margin_delta_pp"),
            "ROE_%": fm.get("roe_pct"),
            "Cap_Millones": fm.get("market_cap_millions"),
            # Valoración
            "PER": vm.get("per"),
            "P/B": vm.get("price_to_book"),
            "EV_EBITDA": vm.get("ev_ebitda"),
            "Caida_52s_%": vm.get("drop_from_52w_high_pct"),
            "Caida_Max_Multianual_%": vm.get("drop_from_multiyear_high_pct"),
            "Dist_SMA200_%": vm.get("dist_sma200_pct"),
            # Técnicos
            "RSI_14": tm.get("rsi_14"),
            "MACD_Cruce": tm.get("macd_crossover"),
            "MACD_Convergiendo": tm.get("macd_converging"),
            "MACD_Semanal": tm.get("weekly_macd"),
            "MACD_Semanal_Giro": tm.get("weekly_macd_turning_up"),
            "Estocastico_K": tm.get("stoch_k"),
            "Estocastico_D": tm.get("stoch_d"),
            "Estocastico_Giro": tm.get("stochastic_bullish_turn"),
            "MA40_Semanal": tm.get("weekly_ma40"),
            "Dist_MA40_Semanal_%": tm.get("price_vs_weekly_ma40"),
            "Base_Pattern_Detected": tm.get("base_pattern_detected"),
            "Trendline_Break": tm.get("trendline_break"),
            "Technical_Base_Score": tm.get("base_score"),
            "Technical_Bonus_Points": tm.get("bonus_points"),
            "Vol_Ratio": tm.get("volume_ratio"),
            "Soporte": tm.get("support_level"),
            "SMA50_Girando": tm.get("sma50_turning_up"),
        })

    df = pd.DataFrame(rows)

    if cfg.OUTPUT["export_xlsx"]:
        xlsx_path = results_dir / f"oportunidades_{timestamp}.xlsx"
        df.to_excel(xlsx_path, index=False, sheet_name="Oportunidades")
        console.print(f"\n  📁 Excel: [bold]{xlsx_path}[/bold]")

    if cfg.OUTPUT["export_csv"]:
        csv_path = results_dir / f"oportunidades_{timestamp}.csv"
        df.to_csv(csv_path, index=False)
        console.print(f"  📁 CSV: [bold]{csv_path}[/bold]")

    # Exportar también análisis completo
    _export_price_history_files(passed, results_dir)
    _export_company_reports(passed, results_dir, timestamp)

    all_rows = []
    for r in all_results:
        comp = r.get("composite", {})
        l2 = r.get("layer_2_causal", {})
        l3 = r.get("layer_3_recovery", {})
        l5 = r.get("layer_5_operational_plan", {})
        all_rows.append({
            "Ticker": r["ticker"],
            "Nombre": r.get("name", ""),
            "Mercado": r.get("market", ""),
            "Rules_Version": r.get("rules_version", versioning.get("rules_version")),
            "Model_Version": r.get("model_version", versioning.get("model_version")),
            "Config_Version": r.get("config_version", versioning.get("config_version")),
            "Evaluation_Timestamp": r.get("evaluation_timestamp", ""),
            "Score": comp.get("total_score", 0),
            "Score_Cuantitativo": comp.get("quantitative_score"),
            "Score_Fundamental": comp.get("fundamental_score"),
            "Score_Valoracion": comp.get("valuation_score"),
            "Score_Causal": comp.get("causal_score"),
            "Score_Recuperacion": comp.get("recovery_score"),
            "Score_Tecnico": comp.get("technical_score"),
            "Score_Tecnico_Base": r.get("technical", {}).get("metrics", {}).get("base_score"),
            "Score_Tecnico_Bonus": r.get("technical", {}).get("metrics", {}).get("bonus_points"),
            "Vol_Medio_Diario": r.get("fundamental", {}).get("metrics", {}).get("avg_daily_volume"),
            "Net_Debt_EBITDA": r.get("fundamental", {}).get("metrics", {}).get("net_debt_ebitda"),
            "Variacion_Deuda_Trimestral_%": r.get("fundamental", {}).get("metrics", {}).get("quarterly_debt_change_pct"),
            "Variacion_Margen_pp": r.get("fundamental", {}).get("metrics", {}).get("margin_delta_pp"),
            "EV_EBITDA": r.get("valuation", {}).get("metrics", {}).get("ev_ebitda"),
            "Caida_Max_Multianual_%": r.get("valuation", {}).get("metrics", {}).get("drop_from_multiyear_high_pct"),
            "MACD_Semanal": r.get("technical", {}).get("metrics", {}).get("weekly_macd"),
            "MACD_Semanal_Giro": r.get("technical", {}).get("metrics", {}).get("weekly_macd_turning_up"),
            "Estocastico_K": r.get("technical", {}).get("metrics", {}).get("stoch_k"),
            "Estocastico_D": r.get("technical", {}).get("metrics", {}).get("stoch_d"),
            "Estocastico_Giro": r.get("technical", {}).get("metrics", {}).get("stochastic_bullish_turn"),
            "MA40_Semanal": r.get("technical", {}).get("metrics", {}).get("weekly_ma40"),
            "Dist_MA40_Semanal_%": r.get("technical", {}).get("metrics", {}).get("price_vs_weekly_ma40"),
            "Base_Pattern_Detected": r.get("technical", {}).get("metrics", {}).get("base_pattern_detected"),
            "Trendline_Break": r.get("technical", {}).get("metrics", {}).get("trendline_break"),
            "Paso_Filtro": comp.get("passed", False),
            "hard_rules_applied": " | ".join(comp.get("hard_rules_applied", [])),
            "Capa1_Status": r.get("layer_1_quantitative", {}).get("status"),
            "Base_Classification": comp.get("base_classification"),
            "Causal_Classification": l2.get("causal_classification"),
            "Causal_Confidence": l2.get("causal_confidence"),
            "Problem_Type": l2.get("problem_type"),
            "Causal_Justification": l2.get("justification"),
            "Recovery_Status": l3.get("recovery_status"),
            "Recovery_Signals": " | ".join(
                _format_recovery_signal(signal) for signal in l3.get("signals", [])
            ),
            "Technical_Status": r.get("layer_4_technical", {}).get("status"),
            "Final_Classification": l5.get("final_classification"),
            "Entry_Zone_Min": l5.get("entry_zone_min"),
            "Entry_Zone_Max": l5.get("entry_zone_max"),
            "Entry_Zone": l5.get("entry_zone"),
            "Exit_Zone_Min": l5.get("exit_zone_min"),
            "Exit_Zone_Max": l5.get("exit_zone_max"),
            "Exit_Zone": l5.get("exit_zone"),
            "Invalidation_Conditions": " | ".join(l5.get("invalidation_conditions", [])),
            "Estimated_Horizon_Months": l5.get("estimated_horizon_months"),
            "Short_Explanation": l5.get("short_explanation"),
            "Summary_Explanation": l5.get("summary_explanation"),
            "Estado": "OK",
            "Error": "",
        })
    for item in failed:
        all_rows.append({
            "Ticker": item.get("ticker", ""),
            "Nombre": "",
            "Mercado": item.get("market", ""),
            "Rules_Version": versioning.get("rules_version"),
            "Model_Version": versioning.get("model_version"),
            "Config_Version": versioning.get("config_version"),
            "Evaluation_Timestamp": "",
            "Score": None,
            "Score_Cuantitativo": None,
            "Score_Fundamental": None,
            "Score_Valoracion": None,
            "Score_Causal": None,
            "Score_Recuperacion": None,
            "Score_Tecnico": None,
            "Score_Tecnico_Base": None,
            "Score_Tecnico_Bonus": None,
            "Vol_Medio_Diario": None,
            "Net_Debt_EBITDA": None,
            "Variacion_Deuda_Trimestral_%": None,
            "Variacion_Margen_pp": None,
            "EV_EBITDA": None,
            "Caida_Max_Multianual_%": None,
            "MACD_Semanal": None,
            "MACD_Semanal_Giro": None,
            "Estocastico_K": None,
            "Estocastico_D": None,
            "Estocastico_Giro": None,
            "MA40_Semanal": None,
            "Dist_MA40_Semanal_%": None,
            "Base_Pattern_Detected": None,
            "Trendline_Break": None,
            "Paso_Filtro": False,
            "hard_rules_applied": "",
            "Capa1_Status": "",
            "Base_Classification": "",
            "Causal_Classification": "",
            "Causal_Confidence": None,
            "Problem_Type": "",
            "Causal_Justification": "",
            "Recovery_Status": "",
            "Recovery_Signals": "",
            "Technical_Status": "",
            "Final_Classification": "",
            "Entry_Zone_Min": None,
            "Entry_Zone_Max": None,
            "Entry_Zone": "",
            "Exit_Zone_Min": None,
            "Exit_Zone_Max": None,
            "Exit_Zone": "",
            "Invalidation_Conditions": "",
            "Estimated_Horizon_Months": None,
            "Short_Explanation": "",
            "Summary_Explanation": "",
            "Estado": "ERROR",
            "Error": item.get("error", ""),
        })
    df_all = pd.DataFrame(all_rows)
    if not df_all.empty and "Score" in df_all.columns:
        df_all.sort_values("Score", ascending=False, inplace=True, na_position="last")
    all_path = results_dir / f"analisis_completo_{timestamp}.csv"
    df_all.to_csv(all_path, index=False)
    console.print(f"  📁 Análisis completo: [bold]{all_path}[/bold]")

def _persist_results_to_database(results: list[dict]) -> None:
    """Guarda evaluaciones, sincroniza watchlist y devuelve alertas nuevas."""
    try:
        database.init_db()
        transitions = []
        generated_alerts = []
        for result in results:
            previous_evaluation = database.get_previous_evaluation(result.get("ticker", ""))
            database.save_evaluation(result)
            transition = database.sync_watchlist_state(result, previous_evaluation)
            if transition:
                transitions.append(transition)
            generated_alerts.extend(
                database.generate_alerts_for_evaluation(result, previous_evaluation)
            )
    except Exception as error:
        console.print(
            f"  [yellow]Aviso SQLite: no se pudo persistir el historial ({error})[/yellow]"
        )
        return []

    console.print(
        f"  SQLite: [bold]{database.DB_PATH}[/bold] "
        f"({len(results)} evaluaciones guardadas)"
    )
    if transitions:
        console.print(f"  Watchlist: [bold]{len(transitions)} transiciones registradas[/bold]")
    if generated_alerts:
        console.print(f"  Alertas nuevas: [bold]{len(generated_alerts)}[/bold]")

    return generated_alerts


def _display_watchlist() -> None:
    """Muestra la watchlist actual guardada en SQLite."""
    database.init_db()
    items = database.get_watchlist()

    console.print("\n[bold cyan]WATCHLIST ACTUAL[/bold cyan]\n")
    if not items:
        console.print("[yellow]La watchlist todavia no tiene registros.[/yellow]")
        return

    table = Table(box=box.ROUNDED, show_lines=True, title="Watchlist persistente")
    table.add_column("Ticker", style="bold", width=10)
    table.add_column("Estado", width=12)
    table.add_column("Prioridad", width=10)
    table.add_column("Clasificacion", width=24)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Manual", justify="center", width=8)
    table.add_column("Motivo", overflow="fold")

    for item in items:
        score = item.get("total_score")
        score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "-"
        table.add_row(
            item.get("ticker", ""),
            item.get("state", ""),
            item.get("priority", ""),
            item.get("final_classification", "") or "-",
            score_text,
            "SI" if item.get("manual_override") else "NO",
            item.get("reason", "") or "",
        )

    console.print(table)


def _apply_watchlist_override(ticker: str, state: str, reason: str) -> None:
    """Aplica un override manual persistente sobre la watchlist."""
    database.init_db()
    override = database.set_watchlist_override(ticker, state, reason)
    console.print("\n[bold cyan]WATCHLIST OVERRIDE[/bold cyan]\n")
    console.print(f"Ticker: [bold]{override['ticker']}[/bold]")
    console.print(f"Estado: [bold]{override['state']}[/bold]")
    console.print(f"Prioridad: {override['priority']}")
    console.print(f"Motivo: {override['reason']}")
    console.print(f"Manual override: {'SI' if override.get('manual_override') else 'NO'}")


def _display_alerts(alerts: list[dict], title: str = "ALERTAS") -> None:
    """Muestra alertas en formato tabla."""
    console.print(f"\n[bold magenta]{title}[/bold magenta]\n")
    if not alerts:
        console.print("[yellow]No hay alertas para mostrar.[/yellow]")
        return

    table = Table(box=box.ROUNDED, show_lines=True, title=title.title())
    table.add_column("Ticker", style="bold", width=10)
    table.add_column("Tipo", width=24)
    table.add_column("Severidad", width=10)
    table.add_column("Titulo", width=28)
    table.add_column("Mensaje", overflow="fold")

    for alert in alerts:
        table.add_row(
            alert.get("ticker", ""),
            alert.get("alert_type", ""),
            alert.get("severity", ""),
            alert.get("title", ""),
            alert.get("message", ""),
        )

    console.print(table)


def _display_generated_alerts(alerts: list[dict]) -> None:
    """Muestra las alertas recién generadas al final del screener."""
    if not alerts:
        console.print("\n[dim]Alertas: ninguna transición relevante en esta ejecución.[/dim]")
        return
    _display_alerts(alerts, title="ALERTAS NUEVAS")


def _show_unread_alerts() -> None:
    """Muestra alertas no leídas y las marca como leídas."""
    database.init_db()
    alerts = database.get_alerts(unread_only=True)
    _display_alerts(alerts, title="ALERTAS NO LEIDAS")
    database.mark_alerts_as_read([
        alert.get("id") for alert in alerts if alert.get("id") is not None
    ])


def _export_alerts(alerts: list[dict]) -> None:
    """Exporta las alertas nuevas de la ejecución actual a CSV."""
    results_dir = Path(cfg.OUTPUT["results_dir"])
    results_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    rows = []

    for alert in alerts:
        rows.append({
            "Ticker": alert.get("ticker"),
            "Alert_Type": alert.get("alert_type"),
            "Severity": alert.get("severity"),
            "Title": alert.get("title"),
            "Message": alert.get("message"),
            "Triggered_At": alert.get("triggered_at"),
            "Is_Read": alert.get("is_read"),
        })

    df_alerts = pd.DataFrame(
        rows,
        columns=[
            "Ticker",
            "Alert_Type",
            "Severity",
            "Title",
            "Message",
            "Triggered_At",
            "Is_Read",
        ],
    )
    alerts_path = results_dir / f"alerts_{timestamp}.csv"
    df_alerts.to_csv(alerts_path, index=False)
    console.print(f"  Alertas CSV: [bold]{alerts_path}[/bold]")


# ===========================================================================
#  CLI
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Stock Opportunity Screener - Detector de valor temporal deprimido"
    )
    parser.add_argument(
        "--markets", nargs="+",
        choices=list(cfg.MARKETS.keys()),
        help="Mercados a escanear (por defecto: todos los activos en config)"
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Escaneo rápido (mercados configurados en QUICK_MARKETS)"
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="Borrar caché antes de ejecutar"
    )

    parser.add_argument(
        "--watchlist", action="store_true",
        help="Mostrar la watchlist persistida en SQLite"
    )
    parser.add_argument(
        "--override", nargs=3, metavar=("TICKER", "ESTADO", "MOTIVO"),
        help="Aplicar override manual a la watchlist"
    )
    parser.add_argument(
        "--alerts", action="store_true",
        help="Mostrar alertas no leidas"
    )

    args = parser.parse_args()

    if args.override:
        try:
            _apply_watchlist_override(*args.override)
            return
        except Exception as error:
            console.print(f"\n[bold red]Error override watchlist: {error}[/bold red]")
            raise

    if args.watchlist:
        _display_watchlist()
        return

    if args.alerts:
        _show_unread_alerts()
        return

    if args.clear_cache:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            CACHE_DIR.mkdir()
            console.print("[yellow]Caché borrada[/yellow]")

    if args.quick:
        markets = cfg.QUICK_MARKETS or cfg.ACTIVE_MARKETS[:1]
    else:
        markets = args.markets

    try:
        results = run_screener(markets)
        console.print(f"\n[bold green]✅ Screener completado[/bold green]")
        console.print(f"   {len(results)} oportunidades encontradas\n")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido por el usuario[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        raise


if __name__ == "__main__":
    main()
