from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

import config as cfg
import database


PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / cfg.OUTPUT["results_dir"]
PRICE_HISTORY_DIR = RESULTS_DIR / "price_history"
SCREENER_PATH = PROJECT_ROOT / "screener.py"
DEFAULT_TIMEZONE = "Europe/Madrid"

st.set_page_config(
    page_title="Stock Opportunity Screener",
    page_icon=":bar_chart:",
    layout="wide",
)


def run_scan(quick_scan: bool, markets: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta el screener solo en entornos locales."""
    command = [sys.executable, str(SCREENER_PATH)]
    if quick_scan:
        command.append("--quick")
    elif markets:
        command.extend(["--markets", *markets])

    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def is_cloud_mode() -> bool:
    """Detecta si el dashboard corre en modo cloud."""
    cloud_env = (
        os.environ.get("STREAMLIT_CLOUD")
        or os.environ.get("STREAMLIT_RUNTIME_ENV")
        or os.environ.get("STREAMLIT_SHARING_MODE")
    )
    if cloud_env:
        return True
    return not os.path.exists(PROJECT_ROOT / "screener.db")


def get_secret_text(section: str, key: str, default: str | None = None) -> str | None:
    """Lee texto desde st.secrets de forma defensiva."""
    try:
        value = st.secrets[section][key]
    except Exception:
        return default

    text = str(value).strip()
    return text or default


def get_dashboard_timezone() -> str:
    """Devuelve la zona horaria de presentacion."""
    return get_secret_text("general", "timezone", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE


def require_authentication() -> None:
    """Protege el dashboard con password basica via Streamlit secrets."""
    expected_password = get_secret_text("auth", "password")
    if not expected_password:
        st.title("Stock Opportunity Screener")
        st.error("No hay password configurado en Streamlit secrets.")
        st.info(
            "Configura st.secrets['auth']['password'] en Streamlit Cloud o crea "
            ".streamlit/secrets.toml a partir de secrets.toml.example para uso local."
        )
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("Acceso privado")
    st.caption("Introduce la password configurada en Streamlit Cloud.")

    with st.form("login_form", clear_on_submit=False):
        entered_password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Entrar", use_container_width=True)

    if submitted:
        if entered_password == expected_password:
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Password incorrecta.")

    st.stop()


def show_logout_button() -> None:
    """Permite cerrar la sesion actual."""
    if st.sidebar.button("Cerrar sesion", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state.pop("selected_ticker", None)
        st.rerun()


@st.cache_data(ttl=3600)
def list_opportunity_files() -> list[str]:
    """Lista los CSV operativos disponibles, ordenados del mas reciente al mas antiguo."""
    if not RESULTS_DIR.exists():
        return []

    files = sorted(
        RESULTS_DIR.glob("oportunidades_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [str(path) for path in files]


def get_latest_opportunity_file() -> Path | None:
    """Devuelve el CSV operativo mas reciente."""
    files = list_opportunity_files()
    if not files:
        return None
    return Path(files[0])


def extract_result_timestamp(path: Path) -> str:
    """Extrae el timestamp del nombre del fichero de resultados."""
    if path.stem.startswith("oportunidades_"):
        return path.stem[len("oportunidades_"):]
    if path.stem.startswith("analisis_completo_"):
        return path.stem[len("analisis_completo_"):]
    return ""


def format_result_timestamp(timestamp: str, timezone_name: str) -> str:
    """Formatea un timestamp YYYYMMDD_HHMM para la UI."""
    try:
        parsed = datetime.strptime(timestamp, "%Y%m%d_%H%M")
    except ValueError:
        return timestamp or "N/A"
    return f"{parsed:%Y-%m-%d %H:%M} ({timezone_name})"


def format_iso_timestamp(value: object, timezone_name: str) -> str:
    """Formatea un ISO timestamp y lo convierte a la zona deseada."""
    if value is None:
        return "N/A"
    text = str(value).strip()
    if not text:
        return "N/A"

    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo(timezone_name))
        return f"{parsed:%Y-%m-%d %H:%M} ({timezone_name})"
    except Exception:
        return text


def _coalesce_column(df: pd.DataFrame, target: str, candidates: list[str], default: object) -> None:
    """Crea una columna normalizada a partir de varias alternativas."""
    for column_name in candidates:
        if column_name in df.columns:
            df[target] = df[column_name]
            return
    if target not in df.columns:
        df[target] = default


def _json_to_pipe_text(value: object) -> str:
    """Convierte listas JSON o texto en un formato legible con pipes."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, list):
        return " | ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _build_zone_text(min_value: object, max_value: object) -> str:
    """Construye un texto de rango si hay datos numericos."""
    min_number = pd.to_numeric(min_value, errors="coerce")
    max_number = pd.to_numeric(max_value, errors="coerce")
    if pd.isna(min_number) and pd.isna(max_number):
        return ""
    if pd.isna(min_number):
        return f"{float(max_number):.2f}"
    if pd.isna(max_number):
        return f"{float(min_number):.2f}"
    return f"{float(min_number):.2f} - {float(max_number):.2f}"


def _format_recovery_signal(signal: object) -> str:
    """Normaliza una senal de recuperacion procedente de JSON o CSV."""
    if isinstance(signal, dict):
        signal_type = str(signal.get("type", "signal")).strip()
        strength = str(signal.get("strength", "media")).strip()
        evidence = str(signal.get("evidence", "")).strip()
        if evidence:
            return f"{signal_type} ({strength}): {evidence}"
        return f"{signal_type} ({strength})"
    return str(signal).strip()


def normalize_results_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza columnas para que el dashboard funcione con CSV o SQLite."""
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "Ticker",
                "Nombre",
                "Mercado",
                "Sector",
                "Pais",
                "Moneda",
                "Precio",
                "Score_Total",
                "Clasificacion",
                "Recovery_Status",
                "Recovery_Signals",
                "Technical_Status",
                "Entry_Zone",
                "Exit_Zone",
                "Estimated_Horizon_Months",
                "Short_Explanation",
                "Summary_Explanation",
                "Invalidation_Conditions",
                "Rules_Version",
                "Model_Version",
                "Config_Version",
                "Evaluation_Timestamp",
                "hard_rules_applied",
                "Senales",
                "PER",
                "P/B",
                "Dist_SMA200_%",
                "RSI_14",
                "Vol_Ratio",
                "Soporte",
                "Entry_Zone_Min",
                "Entry_Zone_Max",
                "Exit_Zone_Min",
                "Exit_Zone_Max",
            ]
        )

    normalized = df.copy()
    _coalesce_column(normalized, "Score_Total", ["Score_Total", "Score", "total_score"], pd.NA)
    _coalesce_column(
        normalized,
        "Clasificacion",
        ["Clasificacion", "Final_Classification", "Capa5_Final_Classification", "final_classification"],
        "N/A",
    )
    _coalesce_column(normalized, "Senales", ["Senales", "Señales", "SeÃ±ales"], "")
    _coalesce_column(normalized, "Pais", ["Pais", "País", "PaÃ­s"], "N/A")
    _coalesce_column(normalized, "Moneda", ["Moneda"], "N/A")
    _coalesce_column(
        normalized,
        "Recovery_Status",
        ["Recovery_Status", "Capa3_Recovery_Status", "recovery_status"],
        "N/A",
    )
    _coalesce_column(
        normalized,
        "Recovery_Signals",
        ["Recovery_Signals", "Capa3_Recovery_Signals", "recovery_signals"],
        "",
    )
    _coalesce_column(
        normalized,
        "Technical_Status",
        ["Technical_Status", "Capa4_Status", "technical_status"],
        "N/A",
    )
    _coalesce_column(normalized, "Entry_Zone_Min", ["Entry_Zone_Min", "Capa5_Entry_Zone_Min"], pd.NA)
    _coalesce_column(normalized, "Entry_Zone_Max", ["Entry_Zone_Max", "Capa5_Entry_Zone_Max"], pd.NA)
    _coalesce_column(normalized, "Exit_Zone_Min", ["Exit_Zone_Min", "Capa5_Exit_Zone_Min"], pd.NA)
    _coalesce_column(normalized, "Exit_Zone_Max", ["Exit_Zone_Max", "Capa5_Exit_Zone_Max"], pd.NA)
    _coalesce_column(normalized, "Entry_Zone", ["Entry_Zone", "Capa5_Entry_Zone"], "")
    _coalesce_column(normalized, "Exit_Zone", ["Exit_Zone", "Capa5_Exit_Zone"], "")
    _coalesce_column(
        normalized,
        "Estimated_Horizon_Months",
        ["Estimated_Horizon_Months", "Capa5_Estimated_Horizon_Months"],
        pd.NA,
    )
    _coalesce_column(
        normalized,
        "Short_Explanation",
        ["Short_Explanation", "Capa5_Short_Explanation"],
        "",
    )
    _coalesce_column(
        normalized,
        "Summary_Explanation",
        ["Summary_Explanation", "Capa5_Summary_Explanation"],
        "",
    )
    _coalesce_column(
        normalized,
        "Invalidation_Conditions",
        ["Invalidation_Conditions", "Capa5_Invalidation_Conditions"],
        "",
    )
    _coalesce_column(normalized, "Rules_Version", ["Rules_Version", "rules_version"], "")
    _coalesce_column(normalized, "Model_Version", ["Model_Version", "model_version"], "")
    _coalesce_column(normalized, "Config_Version", ["Config_Version", "config_version"], "")
    _coalesce_column(
        normalized,
        "Evaluation_Timestamp",
        ["Evaluation_Timestamp", "evaluation_timestamp", "evaluation_date"],
        "",
    )
    _coalesce_column(normalized, "hard_rules_applied", ["hard_rules_applied", "hard_rules_json"], "")

    default_columns = {
        "Ticker": "",
        "Nombre": "",
        "Mercado": "N/A",
        "Sector": "N/A",
        "Industria": "N/A",
        "Pais": "N/A",
        "Moneda": "N/A",
        "Precio": pd.NA,
        "Score_Total": pd.NA,
        "Clasificacion": "N/A",
        "Recovery_Status": "N/A",
        "Recovery_Signals": "",
        "Technical_Status": "N/A",
        "Entry_Zone_Min": pd.NA,
        "Entry_Zone_Max": pd.NA,
        "Exit_Zone_Min": pd.NA,
        "Exit_Zone_Max": pd.NA,
        "Entry_Zone": "",
        "Exit_Zone": "",
        "Estimated_Horizon_Months": pd.NA,
        "Short_Explanation": "",
        "Summary_Explanation": "",
        "Rules_Version": "",
        "Model_Version": "",
        "Config_Version": "",
        "Evaluation_Timestamp": "",
        "hard_rules_applied": "",
        "Senales": "",
        "PER": pd.NA,
        "P/B": pd.NA,
        "Dist_SMA200_%": pd.NA,
        "RSI_14": pd.NA,
        "Vol_Ratio": pd.NA,
        "Soporte": pd.NA,
        "SMA50_Girando": pd.NA,
    }
    for column_name, default_value in default_columns.items():
        if column_name not in normalized.columns:
            normalized[column_name] = default_value

    numeric_columns = [
        "Precio",
        "Score_Total",
        "Estimated_Horizon_Months",
        "PER",
        "P/B",
        "Dist_SMA200_%",
        "RSI_14",
        "Vol_Ratio",
        "Soporte",
        "Entry_Zone_Min",
        "Entry_Zone_Max",
        "Exit_Zone_Min",
        "Exit_Zone_Max",
    ]
    for column_name in numeric_columns:
        if column_name in normalized.columns:
            normalized[column_name] = pd.to_numeric(normalized[column_name], errors="coerce")

    normalized["Recovery_Signals"] = normalized["Recovery_Signals"].apply(_json_to_pipe_text)
    normalized["hard_rules_applied"] = normalized["hard_rules_applied"].apply(_json_to_pipe_text)
    normalized["Senales"] = normalized["Senales"].apply(_json_to_pipe_text)

    missing_entry_zone = normalized["Entry_Zone"].astype(str).str.strip().eq("")
    normalized.loc[missing_entry_zone, "Entry_Zone"] = normalized.loc[missing_entry_zone].apply(
        lambda row: _build_zone_text(row.get("Entry_Zone_Min"), row.get("Entry_Zone_Max")),
        axis=1,
    )
    missing_exit_zone = normalized["Exit_Zone"].astype(str).str.strip().eq("")
    normalized.loc[missing_exit_zone, "Exit_Zone"] = normalized.loc[missing_exit_zone].apply(
        lambda row: _build_zone_text(row.get("Exit_Zone_Min"), row.get("Exit_Zone_Max")),
        axis=1,
    )

    return normalized.sort_values("Score_Total", ascending=False, na_position="last")


@st.cache_data(ttl=3600)
def load_results_file(path_str: str) -> pd.DataFrame:
    """Carga un CSV operativo y normaliza su esquema."""
    path = Path(path_str)
    dataframe = pd.read_csv(path)
    return normalize_results_schema(dataframe)


@st.cache_data(ttl=3600)
def load_sqlite_results() -> pd.DataFrame:
    """Carga la ultima evaluacion por ticker desde SQLite para uso local."""
    rows = database.get_latest_evaluations(exclude_discarded=True)
    serialized_rows = []

    for row in rows:
        signals_payload = row.get("signals_json") or {}
        hard_rules = row.get("hard_rules_json") or []
        recovery_signals = signals_payload.get("recovery_signals") or []
        technical_signals = signals_payload.get("technical_signals") or []

        serialized_rows.append(
            {
                "Ticker": row.get("ticker", ""),
                "Score_Total": row.get("total_score"),
                "Clasificacion": row.get("final_classification"),
                "Recovery_Status": signals_payload.get("recovery_status"),
                "Recovery_Signals": " | ".join(
                    _format_recovery_signal(signal) for signal in recovery_signals
                ),
                "Technical_Status": signals_payload.get("technical_status"),
                "Senales": " | ".join(str(signal).strip() for signal in technical_signals if str(signal).strip()),
                "Precio": signals_payload.get("price"),
                "Soporte": signals_payload.get("support_level"),
                "Variacion_Deuda_Trimestral_%": signals_payload.get("quarterly_debt_change_pct"),
                "Entry_Zone_Min": row.get("entry_zone_min"),
                "Entry_Zone_Max": row.get("entry_zone_max"),
                "Exit_Zone_Min": row.get("exit_zone_min"),
                "Exit_Zone_Max": row.get("exit_zone_max"),
                "Entry_Zone": _build_zone_text(row.get("entry_zone_min"), row.get("entry_zone_max")),
                "Exit_Zone": _build_zone_text(row.get("exit_zone_min"), row.get("exit_zone_max")),
                "Evaluation_Timestamp": row.get("evaluation_date"),
                "Rules_Version": row.get("rules_version"),
                "Config_Version": row.get("config_version"),
                "hard_rules_applied": " | ".join(str(item).strip() for item in hard_rules if str(item).strip()),
            }
        )

    dataframe = pd.DataFrame(serialized_rows)
    return normalize_results_schema(dataframe)


def _prepare_for_merge(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Convierte strings vacios a NA para facilitar el combine_first."""
    prepared = dataframe.copy()
    for column_name in prepared.columns:
        if pd.api.types.is_object_dtype(prepared[column_name]) or pd.api.types.is_string_dtype(prepared[column_name]):
            prepared[column_name] = prepared[column_name].replace("", pd.NA)
    return prepared


@st.cache_data(ttl=3600)
def load_dashboard_dataset() -> tuple[pd.DataFrame, str, str]:
    """Resuelve el dataset operativo para local o cloud."""
    latest_csv = get_latest_opportunity_file()
    csv_dataframe = load_results_file(str(latest_csv)) if latest_csv else normalize_results_schema(pd.DataFrame())

    if database.database_exists():
        sqlite_dataframe = load_sqlite_results()
        if not sqlite_dataframe.empty:
            if csv_dataframe.empty:
                return sqlite_dataframe, "sqlite", str(latest_csv) if latest_csv else ""

            sqlite_prepared = _prepare_for_merge(sqlite_dataframe).set_index("Ticker")
            csv_prepared = _prepare_for_merge(csv_dataframe).set_index("Ticker")
            merged = sqlite_prepared.combine_first(csv_prepared).reset_index()
            return normalize_results_schema(merged), "sqlite", str(latest_csv) if latest_csv else ""

    return csv_dataframe, "csv", str(latest_csv) if latest_csv else ""


def parse_pipe_list(value: object) -> list[str]:
    """Normaliza listas guardadas como texto con pipes."""
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []

    text = str(value).strip()
    if not text or text == "-" or text == "N/A":
        return []
    return [item.strip() for item in text.split("|") if item.strip()]


@st.cache_data(ttl=3600)
def load_markdown_file(path_str: str) -> str:
    """Carga una ficha Markdown si existe."""
    path = Path(path_str)
    return path.read_text(encoding="utf-8")


@st.cache_data(ttl=3600)
def load_exported_price_history(ticker: str) -> pd.DataFrame:
    """Carga historico de precios pregenerado por el screener si existe."""
    path = PRICE_HISTORY_DIR / f"{ticker}.csv"
    if not path.exists():
        return pd.DataFrame()

    history = pd.read_csv(path)
    if history.empty or "Date" not in history.columns or "Close" not in history.columns:
        return pd.DataFrame()

    history["Date"] = pd.to_datetime(history["Date"], errors="coerce").dt.tz_localize(None)
    history["Close"] = pd.to_numeric(history["Close"], errors="coerce")
    if "SMA50" in history.columns:
        history["SMA50"] = pd.to_numeric(history["SMA50"], errors="coerce")
    if "SMA200" in history.columns:
        history["SMA200"] = pd.to_numeric(history["SMA200"], errors="coerce")
    history = history.dropna(subset=["Date", "Close"])
    if history.empty:
        return history

    if "SMA50" not in history.columns:
        history["SMA50"] = history["Close"].rolling(50).mean()
    if "SMA200" not in history.columns:
        history["SMA200"] = history["Close"].rolling(200).mean()
    return history[["Date", "Close", "SMA50", "SMA200"]]


def _filter_history_by_period(history: pd.DataFrame, period: str) -> pd.DataFrame:
    """Filtra el historico exportado al periodo seleccionado."""
    if history.empty:
        return history

    period_days = {
        "6mo": 183,
        "1y": 365,
        "2y": 730,
        "5y": 1825,
    }
    days = period_days.get(period)
    if not days:
        return history

    max_date = history["Date"].max()
    cutoff = max_date - pd.Timedelta(days=days)
    filtered = history.loc[history["Date"] >= cutoff].copy()
    return filtered if not filtered.empty else history


@st.cache_data(ttl=3600)
def load_price_history(ticker: str, period: str) -> tuple[pd.DataFrame, str]:
    """Resuelve el historico del grafico sin usar yfinance en cloud."""
    exported_history = load_exported_price_history(ticker)
    if not exported_history.empty:
        return _filter_history_by_period(exported_history, period), "exported"

    if is_cloud_mode():
        return pd.DataFrame(), "cloud_unavailable"

    try:
        import yfinance as yf
    except Exception:
        return pd.DataFrame(), "local_unavailable"

    history = yf.Ticker(ticker).history(period=period)
    if history is None or history.empty:
        return pd.DataFrame(), "local_unavailable"

    history = history.reset_index()
    history["Date"] = pd.to_datetime(history["Date"]).dt.tz_localize(None)
    history["Close"] = pd.to_numeric(history["Close"], errors="coerce")
    history = history.dropna(subset=["Close"])
    if history.empty:
        return history, "local_unavailable"

    history["SMA50"] = history["Close"].rolling(50).mean()
    history["SMA200"] = history["Close"].rolling(200).mean()
    return history[["Date", "Close", "SMA50", "SMA200"]], "yfinance_local"


def build_signal_markers(price_history: pd.DataFrame, signals: list[str]) -> pd.DataFrame:
    """Crea marcadores para mostrar senales sobre el ultimo precio."""
    if price_history.empty or not signals:
        return pd.DataFrame(columns=["Date", "Price", "Signal"])

    last_row = price_history.iloc[-1]
    last_date = last_row["Date"]
    last_close = float(last_row["Close"])
    markers = []

    for index, signal in enumerate(signals[:4]):
        markers.append(
            {
                "Date": last_date,
                "Price": last_close * (1 + 0.015 * index),
                "Signal": signal,
            }
        )

    return pd.DataFrame(markers)


def build_price_chart(price_history: pd.DataFrame, selected_row: pd.Series) -> alt.Chart:
    """Construye el grafico de precio, medias y senales."""
    chart_data = price_history.melt(
        id_vars=["Date"],
        value_vars=["Close", "SMA50", "SMA200"],
        var_name="Serie",
        value_name="Precio",
    ).dropna(subset=["Precio"])

    line_chart = (
        alt.Chart(chart_data)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("Date:T", title="Fecha"),
            y=alt.Y("Precio:Q", title="Precio"),
            color=alt.Color(
                "Serie:N",
                scale=alt.Scale(
                    domain=["Close", "SMA50", "SMA200"],
                    range=["#0f172a", "#2563eb", "#f59e0b"],
                ),
                title="Serie",
            ),
            tooltip=[
                alt.Tooltip("Date:T", title="Fecha"),
                alt.Tooltip("Serie:N", title="Serie"),
                alt.Tooltip("Precio:Q", title="Precio", format=".2f"),
            ],
        )
        .properties(height=460)
    )

    chart: alt.Chart = line_chart
    support_value = pd.to_numeric(selected_row.get("Soporte"), errors="coerce")
    if pd.notna(support_value):
        support_df = pd.DataFrame({"Support": [float(support_value)]})
        support_line = (
            alt.Chart(support_df)
            .mark_rule(color="#dc2626", strokeDash=[6, 4])
            .encode(y="Support:Q")
        )
        chart = chart + support_line

    signal_markers = build_signal_markers(price_history, parse_pipe_list(selected_row.get("Senales")))
    if not signal_markers.empty:
        point_layer = (
            alt.Chart(signal_markers)
            .mark_circle(color="#059669", size=90)
            .encode(
                x="Date:T",
                y="Price:Q",
                tooltip=[
                    alt.Tooltip("Signal:N", title="Senal"),
                    alt.Tooltip("Price:Q", title="Nivel", format=".2f"),
                ],
            )
        )
        text_layer = (
            alt.Chart(signal_markers)
            .mark_text(align="left", dx=8, dy=-8, color="#059669")
            .encode(x="Date:T", y="Price:Q", text="Signal:N")
        )
        chart = chart + point_layer + text_layer

    return chart.interactive()


def format_value(value: object, decimals: int = 2, suffix: str = "") -> str:
    """Renderiza valores evitando NaN, None y strings vacios."""
    if value is None:
        return "N/A"
    try:
        if pd.isna(value):
            return "N/A"
    except Exception:
        pass

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}"

    text = str(value).strip()
    return text or "N/A"


def slugify_filename(value: str) -> str:
    """Replica el slug basico usado al exportar fichas."""
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


def get_company_report_path(result_file: Path | None, ticker: str) -> Path | None:
    """Devuelve la ficha Markdown asociada si existe."""
    if result_file is None:
        return None

    timestamp = extract_result_timestamp(result_file)
    if not timestamp:
        return None

    report_dir = RESULTS_DIR / f"fichas_{timestamp}"
    if not report_dir.exists():
        return None

    ticker_slug = slugify_filename(ticker)
    matches = sorted(report_dir.glob(f"*_{ticker_slug}.md"))
    return matches[0] if matches else None


def get_summary_report_path(result_file: Path | None) -> Path | None:
    """Devuelve el resumen consolidado de fichas para el lote seleccionado."""
    if result_file is None:
        return None

    timestamp = extract_result_timestamp(result_file)
    if not timestamp:
        return None

    summary_path = RESULTS_DIR / f"fichas_{timestamp}" / "fichas_resumen.md"
    return summary_path if summary_path.exists() else None


def show_local_scan_controls() -> None:
    """Renderiza controles de ejecucion solo para uso local."""
    st.sidebar.divider()
    st.sidebar.subheader("Escaneo local")
    quick_label = f"Escaneo rapido ({', '.join(cfg.QUICK_MARKETS)})"
    quick_scan = st.sidebar.checkbox(quick_label, value=True)
    selected_markets = st.sidebar.multiselect(
        "Mercados a ejecutar",
        options=sorted(cfg.MARKETS.keys()),
        default=list(cfg.ACTIVE_MARKETS),
        disabled=quick_scan,
    )

    if st.sidebar.button("Ejecutar screener", use_container_width=True):
        with st.spinner("Ejecutando screener local..."):
            completed = run_scan(quick_scan=quick_scan, markets=selected_markets)
        st.session_state["last_scan"] = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        st.cache_data.clear()
        st.rerun()

    scan_result = st.session_state.get("last_scan")
    if not scan_result:
        return

    if scan_result["returncode"] == 0:
        st.sidebar.success("Escaneo completado")
    else:
        st.sidebar.error("El escaneo termino con error")

    with st.sidebar.expander("Salida del ultimo escaneo", expanded=False):
        if scan_result["stdout"]:
            st.code(scan_result["stdout"], language="text")
        if scan_result["stderr"]:
            st.code(scan_result["stderr"], language="text")


def show_sidebar_status(dataframe: pd.DataFrame, source_mode: str, last_scan_label: str) -> None:
    """Muestra estado general del dataset cargado."""
    st.sidebar.subheader("Estado")
    source_label = "SQLite local" if source_mode == "sqlite" else "CSV del repo"
    st.sidebar.write(f"Fuente de datos: {source_label}")
    st.sidebar.write(f"Ultimo escaneo: {last_scan_label}")
    st.sidebar.write(f"Oportunidades detectadas: {len(dataframe)}")


def apply_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aplica filtros desde la barra lateral."""
    filtered = dataframe.copy()

    st.sidebar.subheader("Filtros")
    market_options = sorted(value for value in filtered["Mercado"].dropna().unique() if str(value).strip())
    classification_options = sorted(
        value for value in filtered["Clasificacion"].dropna().unique() if str(value).strip()
    )

    selected_markets = st.sidebar.multiselect("Mercado", market_options, default=market_options)
    selected_classifications = st.sidebar.multiselect(
        "Clasificacion final",
        classification_options,
        default=classification_options,
    )

    valid_scores = filtered["Score_Total"].dropna()
    if valid_scores.empty:
        score_min = 0
        score_max = 100
    else:
        score_min = int(valid_scores.min())
        score_max = max(int(valid_scores.max()), score_min + 1)
    selected_score_min = st.sidebar.slider(
        "Score minimo",
        min_value=score_min,
        max_value=score_max,
        value=score_min,
        step=1,
    )

    if selected_markets:
        filtered = filtered[filtered["Mercado"].isin(selected_markets)]
    if selected_classifications:
        filtered = filtered[filtered["Clasificacion"].isin(selected_classifications)]

    filtered = filtered[filtered["Score_Total"].fillna(-1) >= selected_score_min]
    return filtered.sort_values("Score_Total", ascending=False, na_position="last")


def show_top_metrics(filtered: pd.DataFrame) -> None:
    """Muestra un resumen rapido del dataset ya filtrado."""
    score_mean = filtered["Score_Total"].dropna().mean() if not filtered.empty else pd.NA
    market_count = filtered["Mercado"].nunique(dropna=True) if "Mercado" in filtered.columns else 0
    classification_count = filtered["Clasificacion"].nunique(dropna=True) if "Clasificacion" in filtered.columns else 0
    latest_config = "N/A"

    if "Config_Version" in filtered.columns:
        valid_versions = [
            str(item).strip()
            for item in filtered["Config_Version"].dropna().unique()
            if str(item).strip()
        ]
        if valid_versions:
            latest_config = valid_versions[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Filas visibles", len(filtered))
    col2.metric("Score medio", f"{score_mean:.1f}" if pd.notna(score_mean) else "N/A")
    col3.metric("Mercados", int(market_count))
    col4.metric("Config version", latest_config)
    st.caption(f"Clasificaciones visibles: {classification_count}")


def get_last_scan_label(result_file: Path | None, dataframe: pd.DataFrame, timezone_name: str) -> str:
    """Resuelve la fecha/hora del ultimo escaneo para la UI."""
    if result_file is not None:
        return format_result_timestamp(extract_result_timestamp(result_file), timezone_name)

    if "Evaluation_Timestamp" in dataframe.columns and not dataframe["Evaluation_Timestamp"].dropna().empty:
        return format_iso_timestamp(dataframe["Evaluation_Timestamp"].dropna().iloc[0], timezone_name)

    return "N/A"


def render_selection_table(filtered: pd.DataFrame) -> pd.Series:
    """Renderiza la tabla principal y permite abrir detalle con click."""
    table_columns = [
        "Ticker",
        "Nombre",
        "Mercado",
        "Sector",
        "Precio",
        "Score_Total",
        "Clasificacion",
        "Recovery_Status",
        "Technical_Status",
        "Entry_Zone",
    ]
    visible_columns = [column for column in table_columns if column in filtered.columns]

    st.subheader("Oportunidades")
    st.caption("Haz click en una fila para abrir la ficha detallada. Si no hay seleccion, se muestra la primera.")

    selected_rows: list[int] = []
    try:
        event = st.dataframe(
            filtered[visible_columns],
            use_container_width=True,
            hide_index=True,
            height=420,
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_rows = list(event.selection.rows)
    except TypeError:
        st.dataframe(
            filtered[visible_columns],
            use_container_width=True,
            hide_index=True,
            height=420,
        )

    if selected_rows:
        selected_index = selected_rows[0]
        if 0 <= selected_index < len(filtered):
            st.session_state["selected_ticker"] = str(filtered.iloc[selected_index]["Ticker"])

    ticker_options = filtered["Ticker"].astype(str).tolist()
    default_ticker = st.session_state.get("selected_ticker", ticker_options[0])
    if default_ticker not in ticker_options:
        default_ticker = ticker_options[0]

    selected_ticker = st.selectbox(
        "Empresa seleccionada",
        options=ticker_options,
        index=ticker_options.index(default_ticker),
    )
    st.session_state["selected_ticker"] = selected_ticker
    return filtered.loc[filtered["Ticker"].astype(str) == selected_ticker].iloc[0]


def render_detail_panel(selected_row: pd.Series, timezone_name: str) -> None:
    """Muestra el detalle extendido del ticker seleccionado."""
    st.subheader("Detalle")
    st.write(f"Clasificacion: {selected_row.get('Clasificacion', 'N/A')}")
    st.write(f"Mercado: {selected_row.get('Mercado', 'N/A')}")
    st.write(f"Sector: {selected_row.get('Sector', 'N/A')}")
    st.write(f"Pais: {selected_row.get('Pais', 'N/A')}")
    st.write(f"Precio: {format_value(selected_row.get('Precio'))} {selected_row.get('Moneda', 'N/A')}")
    st.write(f"Score total: {format_value(selected_row.get('Score_Total'), decimals=1)}")
    st.write(f"Recovery status: {selected_row.get('Recovery_Status', 'N/A')}")
    st.write(f"Technical status: {selected_row.get('Technical_Status', 'N/A')}")
    st.write(f"PER: {format_value(selected_row.get('PER'))}")
    st.write(f"P/B: {format_value(selected_row.get('P/B'))}")
    st.write(f"Dist. SMA200: {format_value(selected_row.get('Dist_SMA200_%'), suffix='%')}")
    st.write(f"RSI 14: {format_value(selected_row.get('RSI_14'))}")
    st.write(f"Soporte: {format_value(selected_row.get('Soporte'))}")
    st.write(
        f"Ultima evaluacion: {format_iso_timestamp(selected_row.get('Evaluation_Timestamp'), timezone_name)}"
    )

    with st.expander("Plan operativo", expanded=True):
        st.write(f"Entrada: {selected_row.get('Entry_Zone', 'N/A') or 'N/A'}")
        st.write(f"Salida: {selected_row.get('Exit_Zone', 'N/A') or 'N/A'}")

        horizon = format_value(selected_row.get("Estimated_Horizon_Months"), decimals=0)
        if horizon != "N/A":
            horizon = f"{horizon} meses"
        st.write(f"Horizonte: {horizon}")

        invalidation = parse_pipe_list(selected_row.get("Invalidation_Conditions"))
        st.markdown("**Invalidacion**")
        if invalidation:
            for item in invalidation:
                st.write(f"- {item}")
        else:
            st.write("Sin condiciones registradas.")

        hard_rules = parse_pipe_list(selected_row.get("hard_rules_applied"))
        st.markdown("**Hard rules**")
        if hard_rules:
            for item in hard_rules:
                st.write(f"- {item}")
        else:
            st.write("No se aplicaron hard rules.")

    with st.expander("Senales y tesis", expanded=True):
        technical_signals = parse_pipe_list(selected_row.get("Senales"))
        recovery_signals = parse_pipe_list(selected_row.get("Recovery_Signals"))

        st.markdown("**Senales tecnicas / compuestas**")
        if technical_signals:
            for signal in technical_signals:
                st.write(f"- {signal}")
        else:
            st.write("Sin senales registradas.")

        st.markdown("**Senales de recuperacion**")
        if recovery_signals:
            for signal in recovery_signals:
                st.write(f"- {signal}")
        else:
            st.write("Sin senales de recuperacion registradas.")

        st.markdown("**Tesis resumida**")
        st.write(selected_row.get("Short_Explanation") or "Sin tesis resumida.")

        summary = str(selected_row.get("Summary_Explanation") or "").strip()
        if summary:
            st.markdown("**Resumen ampliado**")
            st.write(summary)

    with st.expander("Versionado", expanded=False):
        st.write(f"Rules version: {selected_row.get('Rules_Version', 'N/A')}")
        st.write(f"Model version: {selected_row.get('Model_Version', 'N/A')}")
        st.write(f"Config version: {selected_row.get('Config_Version', 'N/A')}")


def main() -> None:
    require_authentication()
    timezone_name = get_dashboard_timezone()

    st.title("Stock Opportunity Screener Dashboard")
    st.caption(
        "GitHub Actions ejecuta el screener, commitea resultados en results/ "
        "y este dashboard consume el ultimo lote disponible."
    )

    dataframe, source_mode, latest_csv_str = load_dashboard_dataset()
    latest_result_file = Path(latest_csv_str) if latest_csv_str else None

    if dataframe.empty:
        st.info("No hay oportunidades disponibles en results/ ni en screener.db.")
        return

    if source_mode == "sqlite":
        show_local_scan_controls()
    show_logout_button()

    last_scan_label = get_last_scan_label(latest_result_file, dataframe, timezone_name)
    show_sidebar_status(dataframe, source_mode, last_scan_label)
    filtered = apply_filters(dataframe)

    source_label = "SQLite local con enriquecimiento CSV" if source_mode == "sqlite" else "CSV del repo"
    st.caption(f"Fuente activa: {source_label}")
    show_top_metrics(filtered)

    if filtered.empty:
        st.warning("No hay empresas que cumplan los filtros seleccionados.")
        return

    selected_row = render_selection_table(filtered)
    selected_ticker = str(selected_row.get("Ticker", "")).strip()

    period = st.selectbox("Periodo del grafico", ["6mo", "1y", "2y", "5y"], index=1)
    price_history, price_history_source = load_price_history(selected_ticker, period)

    detail_left, detail_right = st.columns([2, 1])
    with detail_left:
        st.subheader(f"{selected_ticker} | {selected_row.get('Nombre', '')}")
        if price_history.empty:
            if price_history_source == "cloud_unavailable":
                st.info("Grafico de precios no disponible en modo cloud.")
            else:
                st.warning("No se pudo cargar historico para el grafico.")
        else:
            if price_history_source == "exported":
                st.caption("Grafico construido con historico exportado por el screener.")
            elif price_history_source == "yfinance_local":
                st.caption("Grafico construido con yfinance en modo local.")
            st.altair_chart(build_price_chart(price_history, selected_row), use_container_width=True)

    with detail_right:
        render_detail_panel(selected_row, timezone_name)

    report_path = get_company_report_path(latest_result_file, selected_ticker)
    summary_path = get_summary_report_path(latest_result_file)

    st.markdown("---")
    st.subheader("Ficha Markdown")
    if report_path and report_path.exists():
        st.caption(f"Fuente: {report_path.name}")
        st.markdown(load_markdown_file(str(report_path)))
    else:
        st.info("No se encontro ficha Markdown asociada para este ticker.")

    with st.expander("Fichas resumen del lote", expanded=False):
        if summary_path and summary_path.exists():
            st.caption(f"Fuente: {summary_path.name}")
            st.markdown(load_markdown_file(str(summary_path)))
        else:
            st.info("No se encontro fichas_resumen.md para el lote actual.")


if __name__ == "__main__":
    main()
