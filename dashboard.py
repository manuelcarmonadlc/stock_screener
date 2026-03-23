from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import yfinance as yf

import config as cfg


PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / cfg.OUTPUT["results_dir"]
SCREENER_PATH = PROJECT_ROOT / "screener.py"

st.set_page_config(
    page_title="Stock Opportunity Screener",
    page_icon=":bar_chart:",
    layout="wide",
)


def run_scan(quick_scan: bool, markets: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta el screener desde la interfaz."""
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


@st.cache_data(ttl=60)
def list_result_files() -> list[Path]:
    """Lista los ficheros de resultados disponibles."""
    if not RESULTS_DIR.exists():
        return []

    files: list[Path] = []
    for pattern in ("oportunidades_*.csv", "oportunidades_*.xlsx", "analisis_completo_*.csv"):
        files.extend(RESULTS_DIR.glob(pattern))
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def get_default_result_index(files: list[Path]) -> int:
    """Prioriza por defecto el ultimo fichero de oportunidades."""
    for index, path in enumerate(files):
        if path.name.startswith("oportunidades_"):
            return index
    return 0


def _coalesce_column(df: pd.DataFrame, target: str, candidates: list[str], default: object) -> None:
    """Crea una columna normalizada a partir de varias alternativas."""
    for column_name in candidates:
        if column_name in df.columns:
            df[target] = df[column_name]
            return
    if target not in df.columns:
        df[target] = default


@st.cache_data(ttl=60)
def load_results_file(path_str: str) -> pd.DataFrame:
    """Carga un CSV o Excel de resultados y normaliza el esquema."""
    path = Path(path_str)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    elif path.suffix.lower() == ".xlsx":
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Formato no soportado: {path.suffix}")

    df = df.copy()
    _coalesce_column(df, "Score_Total", ["Score_Total", "Score"], pd.NA)
    _coalesce_column(
        df,
        "Clasificacion",
        ["Clasificacion", "Final_Classification", "Capa5_Final_Classification"],
        "N/A",
    )
    _coalesce_column(df, "Senales", ["Senales", "Señales", "SeÃ±ales"], "")
    _coalesce_column(df, "Pais", ["Pais", "País", "PaÃ­s"], "N/A")
    _coalesce_column(df, "Moneda", ["Moneda"], "N/A")
    _coalesce_column(df, "Recovery_Status", ["Recovery_Status", "Capa3_Recovery_Status"], "N/A")
    _coalesce_column(df, "Recovery_Signals", ["Recovery_Signals", "Capa3_Recovery_Signals"], "")
    _coalesce_column(df, "Technical_Status", ["Technical_Status", "Capa4_Status"], "N/A")
    _coalesce_column(df, "Entry_Zone", ["Entry_Zone", "Capa5_Entry_Zone"], "")
    _coalesce_column(df, "Exit_Zone", ["Exit_Zone", "Capa5_Exit_Zone"], "")
    _coalesce_column(
        df,
        "Estimated_Horizon_Months",
        ["Estimated_Horizon_Months", "Capa5_Estimated_Horizon_Months"],
        pd.NA,
    )
    _coalesce_column(df, "Short_Explanation", ["Short_Explanation", "Capa5_Short_Explanation"], "")
    _coalesce_column(df, "Summary_Explanation", ["Summary_Explanation", "Capa5_Summary_Explanation"], "")
    _coalesce_column(df, "Invalidation_Conditions", ["Invalidation_Conditions", "Capa5_Invalidation_Conditions"], "")

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
        "Technical_Status": "N/A",
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
        if column_name not in df.columns:
            df[column_name] = default_value

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
    ]
    for column_name in numeric_columns:
        if column_name in df.columns:
            df[column_name] = pd.to_numeric(df[column_name], errors="coerce")

    bool_columns = [
        "MACD_Cruce",
        "MACD_Convergiendo",
        "SMA50_Girando",
        "Recorte_Reciente",
        "MACD_Semanal_Giro",
        "Estocastico_Giro",
        "Base_Pattern_Detected",
        "Trendline_Break",
    ]
    for column_name in bool_columns:
        if column_name in df.columns:
            df[column_name] = df[column_name].astype("boolean")

    return df


@st.cache_data(ttl=1800)
def load_price_history(ticker: str, period: str) -> pd.DataFrame:
    """Descarga historico de precios para el grafico."""
    history = yf.Ticker(ticker).history(period=period)
    if history is None or history.empty:
        return pd.DataFrame()

    history = history.reset_index()
    history["Date"] = pd.to_datetime(history["Date"]).dt.tz_localize(None)
    history["Close"] = pd.to_numeric(history["Close"], errors="coerce")
    history = history.dropna(subset=["Close"])
    if history.empty:
        return history

    history["SMA50"] = history["Close"].rolling(50).mean()
    history["SMA200"] = history["Close"].rolling(200).mean()
    return history[["Date", "Close", "SMA50", "SMA200"]]


def parse_pipe_list(value: object) -> list[str]:
    """Normaliza listas guardadas en el CSV/XLSX."""
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []

    text = str(value).strip()
    if not text or text == "-":
        return []
    return [item.strip() for item in text.split("|") if item.strip()]


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
    """Renderiza valores para la UI evitando NaN y None."""
    if value is None:
        return "N/A"
    if isinstance(value, float) and pd.isna(value):
        return "N/A"
    if pd.isna(value):
        return "N/A"

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


def extract_result_timestamp(path: Path) -> str:
    """Extrae el timestamp del nombre del fichero de resultados."""
    for prefix in ("oportunidades_", "analisis_completo_"):
        if path.stem.startswith(prefix):
            return path.stem[len(prefix):]
    return ""


def format_result_file_label(path: Path) -> str:
    """Genera una etiqueta legible para el selector de resultados."""
    timestamp = extract_result_timestamp(path)
    if len(timestamp) >= 13:
        pretty_timestamp = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} {timestamp[9:11]}:{timestamp[11:13]}"
    else:
        pretty_timestamp = timestamp or "sin fecha"

    if path.name.startswith("oportunidades_"):
        dataset_label = "Oportunidades"
    elif path.name.startswith("analisis_completo_"):
        dataset_label = "Analisis completo"
    else:
        dataset_label = path.stem

    return f"{dataset_label} | {pretty_timestamp} | {path.suffix.lower().lstrip('.')}"


def get_company_report_path(result_file: Path, ticker: str) -> Path | None:
    """Devuelve la ficha Markdown asociada si existe."""
    timestamp = extract_result_timestamp(result_file)
    if not timestamp:
        return None

    report_dir = RESULTS_DIR / f"fichas_{timestamp}"
    if not report_dir.exists():
        return None

    ticker_slug = slugify_filename(ticker)
    matches = sorted(report_dir.glob(f"*_{ticker_slug}.md"))
    return matches[0] if matches else None


def get_summary_report_path(result_file: Path) -> Path | None:
    """Devuelve el resumen consolidado de fichas para el lote seleccionado."""
    timestamp = extract_result_timestamp(result_file)
    if not timestamp:
        return None

    summary_path = RESULTS_DIR / f"fichas_{timestamp}" / "fichas_resumen.md"
    return summary_path if summary_path.exists() else None


@st.cache_data(ttl=60)
def load_markdown_file(path_str: str) -> str:
    """Carga una ficha Markdown si existe."""
    path = Path(path_str)
    return path.read_text(encoding="utf-8")


def show_scan_controls() -> None:
    """Renderiza los controles de ejecucion."""
    st.sidebar.subheader("Escanear")
    quick_label = f"Escaneo rapido ({', '.join(cfg.QUICK_MARKETS)})"
    quick_scan = st.sidebar.checkbox(quick_label, value=True)
    selected_markets = st.sidebar.multiselect(
        "Mercados",
        options=sorted(cfg.MARKETS.keys()),
        default=list(cfg.ACTIVE_MARKETS),
        disabled=quick_scan,
    )

    if st.sidebar.button("Escanear", use_container_width=True):
        with st.spinner("Ejecutando screener..."):
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


def show_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aplica filtros interactivos a la tabla."""
    filtered = dataframe.copy()

    st.sidebar.subheader("Filtros")
    market_options = sorted(value for value in filtered["Mercado"].dropna().unique() if str(value).strip())
    sector_options = sorted(value for value in filtered["Sector"].dropna().unique() if str(value).strip())
    classification_options = sorted(
        value for value in filtered["Clasificacion"].dropna().unique() if str(value).strip()
    )

    selected_markets = st.sidebar.multiselect("Mercado", market_options, default=market_options)
    selected_sectors = st.sidebar.multiselect("Sector", sector_options, default=sector_options)
    selected_classifications = st.sidebar.multiselect(
        "Clasificacion",
        classification_options,
        default=classification_options,
    )

    if not filtered["Score_Total"].dropna().empty:
        score_min = float(filtered["Score_Total"].min())
        score_max = float(filtered["Score_Total"].max())
    else:
        score_min = 0.0
        score_max = 100.0
    selected_score = st.sidebar.slider(
        "Score",
        min_value=float(score_min),
        max_value=float(score_max),
        value=(float(score_min), float(score_max)),
        step=1.0,
    )

    text_filter = st.sidebar.text_input("Ticker o nombre")

    if selected_markets:
        filtered = filtered[filtered["Mercado"].isin(selected_markets)]
    if selected_sectors:
        filtered = filtered[filtered["Sector"].isin(selected_sectors)]
    if selected_classifications:
        filtered = filtered[filtered["Clasificacion"].isin(selected_classifications)]

    filtered = filtered[
        filtered["Score_Total"].fillna(score_min).between(selected_score[0], selected_score[1])
    ]

    if text_filter:
        mask = (
            filtered["Ticker"].astype(str).str.contains(text_filter, case=False, na=False)
            | filtered["Nombre"].astype(str).str.contains(text_filter, case=False, na=False)
        )
        filtered = filtered[mask]

    return filtered.sort_values("Score_Total", ascending=False, na_position="last")


def show_summary(filtered: pd.DataFrame) -> None:
    """Muestra indicadores resumidos del dataset filtrado."""
    total_rows = int(len(filtered))
    mean_score = filtered["Score_Total"].dropna().mean() if "Score_Total" in filtered.columns else pd.NA
    market_count = filtered["Mercado"].nunique(dropna=True) if "Mercado" in filtered.columns else 0
    classification_count = (
        filtered["Clasificacion"].nunique(dropna=True) if "Clasificacion" in filtered.columns else 0
    )

    latest_config = "N/A"
    if "Config_Version" in filtered.columns:
        valid_versions = [str(value) for value in filtered["Config_Version"].dropna().unique() if str(value).strip()]
        if valid_versions:
            latest_config = valid_versions[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Filas", total_rows)
    col2.metric("Score medio", f"{mean_score:.1f}" if pd.notna(mean_score) else "N/A")
    col3.metric("Mercados", int(market_count))
    col4.metric("Config version", latest_config if latest_config else "N/A")

    st.caption(f"Clasificaciones presentes: {classification_count}")


def render_detail_panel(selected_row: pd.Series) -> None:
    """Muestra detalle extendido del ticker seleccionado."""
    st.subheader("Detalle")
    st.write(f"Clasificacion: {selected_row.get('Clasificacion', 'N/A')}")
    st.write(f"Mercado: {selected_row.get('Mercado', 'N/A')}")
    st.write(f"Sector: {selected_row.get('Sector', 'N/A')}")
    st.write(f"Pais: {selected_row.get('Pais', 'N/A')}")
    st.write(
        f"Precio: {format_value(selected_row.get('Precio'))} {selected_row.get('Moneda', 'N/A')}"
    )
    st.write(f"Score total: {format_value(selected_row.get('Score_Total'), decimals=1)}")
    st.write(f"Recovery status: {selected_row.get('Recovery_Status', 'N/A')}")
    st.write(f"Technical status: {selected_row.get('Technical_Status', 'N/A')}")
    st.write(f"PER: {format_value(selected_row.get('PER'))}")
    st.write(f"P/B: {format_value(selected_row.get('P/B'))}")
    st.write(f"Dist. SMA200: {format_value(selected_row.get('Dist_SMA200_%'), suffix='%')}")
    st.write(f"RSI 14: {format_value(selected_row.get('RSI_14'))}")
    st.write(f"Soporte: {format_value(selected_row.get('Soporte'))}")

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
        signals = parse_pipe_list(selected_row.get("Senales"))
        recovery_signals = parse_pipe_list(selected_row.get("Recovery_Signals"))

        st.markdown("**Senales tecnicas / compuestas**")
        if signals:
            for signal in signals:
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

        summary = selected_row.get("Summary_Explanation") or ""
        if str(summary).strip():
            st.markdown("**Resumen ampliado**")
            st.write(summary)

    with st.expander("Versionado", expanded=False):
        st.write(f"Rules version: {selected_row.get('Rules_Version', 'N/A')}")
        st.write(f"Model version: {selected_row.get('Model_Version', 'N/A')}")
        st.write(f"Config version: {selected_row.get('Config_Version', 'N/A')}")
        st.write(f"Evaluation timestamp: {selected_row.get('Evaluation_Timestamp', 'N/A')}")


def main() -> None:
    st.title("Stock Opportunity Screener Dashboard")
    st.caption(
        "Explora resultados, filtra oportunidades, revisa el plan operativo y consulta la ficha Markdown."
    )

    show_scan_controls()

    result_files = list_result_files()
    if not result_files:
        st.info("No hay ficheros en results/. Ejecuta el screener desde la barra lateral.")
        return

    opportunity_files = [path for path in result_files if path.name.startswith("oportunidades_")]
    analysis_files = [path for path in result_files if path.name.startswith("analisis_completo_")]

    dataset_view = st.radio(
        "Vista de dataset",
        options=["Operativo", "Analisis completo"],
        horizontal=True,
        index=0,
    )

    if dataset_view == "Operativo":
        selectable_files = opportunity_files or result_files
        if not opportunity_files:
            st.info("No hay ficheros de oportunidades. Mostrando el dataset disponible mas reciente.")
    else:
        selectable_files = analysis_files or result_files
        if not analysis_files:
            st.info("No hay ficheros de analisis completo. Mostrando el dataset disponible mas reciente.")

    selected_file = st.selectbox(
        "Fuente de datos",
        options=selectable_files,
        format_func=format_result_file_label,
        index=0,
    )

    dataframe = load_results_file(str(selected_file))
    filtered = show_filters(dataframe)

    st.caption(
        f"Archivo: {selected_file.name} | Registros: {len(dataframe)} | "
        f"Actualizado: {pd.Timestamp(selected_file.stat().st_mtime, unit='s')}"
    )
    if selected_file.name.startswith("analisis_completo_"):
        st.info("Estas viendo el analisis completo. La tabla es mas exhaustiva, pero algunas columnas visuales se derivan del dataset normalizado.")
    else:
        st.success("Estas viendo el dataset operativo de oportunidades, optimizado para revisiones manuales.")

    show_summary(filtered)

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
        "Senales",
    ]
    visible_columns = [column for column in table_columns if column in filtered.columns]
    st.dataframe(
        filtered[visible_columns],
        use_container_width=True,
        hide_index=True,
        height=420,
    )

    if filtered.empty:
        st.warning("No hay empresas que cumplan los filtros seleccionados.")
        return

    selection_options = [
        f"{row.Ticker} - {row.Nombre}" for row in filtered.itertuples(index=False)
    ]
    selected_label = st.selectbox("Empresa seleccionada", selection_options)
    selected_ticker = selected_label.split(" - ", 1)[0]
    selected_row = filtered.loc[filtered["Ticker"] == selected_ticker].iloc[0]

    period = st.selectbox("Periodo del grafico", ["6mo", "1y", "2y", "5y"], index=1)
    price_history = load_price_history(selected_ticker, period)

    detail_left, detail_right = st.columns([2, 1])
    with detail_left:
        st.subheader(f"{selected_row['Ticker']} | {selected_row.get('Nombre', '')}")
        if price_history.empty:
            st.warning("No se pudo descargar historico para el grafico.")
        else:
            st.altair_chart(build_price_chart(price_history, selected_row), use_container_width=True)

    with detail_right:
        render_detail_panel(selected_row)

    report_path = get_company_report_path(selected_file, selected_ticker)
    summary_path = get_summary_report_path(selected_file)
    st.markdown("---")
    st.subheader("Ficha Markdown")
    if report_path and report_path.exists():
        st.caption(f"Fuente: {report_path.name}")
        st.markdown(load_markdown_file(str(report_path)))
    else:
        st.info("No se encontro ficha Markdown asociada para este ticker o este fichero de resultados.")

    with st.expander("Fichas resumen del lote", expanded=False):
        if summary_path and summary_path.exists():
            st.caption(f"Fuente: {summary_path.name}")
            st.markdown(load_markdown_file(str(summary_path)))
        else:
            st.info("No se encontro fichas_resumen.md para el lote seleccionado.")


if __name__ == "__main__":
    main()
