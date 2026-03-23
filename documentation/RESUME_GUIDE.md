# RESUME_GUIDE

Guia pensada para una persona o una IA que abre este proyecto por primera vez
y necesita retomar el trabajo sin perder tiempo.

## 3.1 Como arrancar

Desde la raiz del proyecto:

```powershell
cd C:\Users\mcarmona.delacuesta\Repo_de_trabajo_local\script_stock_opportunity_screener
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe .\screener.py --quick
```

Si quieres abrir el dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\dashboard.py
```

Comandos utiles de inspeccion rapida:

```powershell
.\.venv\Scripts\python.exe .\screener.py --watchlist
.\.venv\Scripts\python.exe .\screener.py --alerts
```

## 3.2 Que leer primero

Orden recomendado:
1. `AGENTS.md`
2. `GUIA_CODEX.md`
3. `documentation/PROJECT_STATUS.md`
4. `documentation/DESIGN_DECISIONS.md`
5. `documentation/analisis_metodologia_gregorio_v3_consenso.md`
6. `config.py`
7. `database.py`
8. `screener.py`
9. `dashboard.py`

Si el objetivo es puramente funcional:
- empieza por `config.py`, `database.py` y `screener.py`

Si el objetivo es de producto/metodologia:
- empieza por el documento metodologico y luego por `PROJECT_STATUS.md`

## 3.3 Mapa mental rapido del sistema

Flujo actual:

1. `screener.py` descarga datos de yfinance y cachea respuestas JSON.
2. Ejecuta 5 capas:
   - capa 1 cuantitativa
   - capa 2 causal placeholder
   - capa 3 recuperacion
   - capa 4 tecnica
   - capa 5 plan operativo
3. Calcula score compuesto.
4. Aplica hard rules.
5. Exporta CSV/XLSX y fichas Markdown.
6. Guarda historial en `screener.db`.
7. Sincroniza watchlist.
8. Genera alertas si detecta cambios relevantes.
9. `dashboard.py` lee `results/` para revision visual.

## 3.4 Donde tocar segun el tipo de cambio

### Si quieres cambiar mercados o umbrales

Toca:
- `config.py`

Luego ejecuta:

```powershell
.\.venv\Scripts\python.exe .\screener.py --quick
```

Nota:
- el proyecto versiona cambios de configuracion con `.config_hash`

### Si quieres cambiar logica de scoring, capas o export

Toca:
- `screener.py`

Puntos de entrada utiles:
- `analyze_quantitative`
- `analyze_causal`
- `analyze_recovery`
- `analyze_technical`
- `generate_operational_plan`
- `compute_composite_score`
- `apply_hard_rules`
- `_export_results`

### Si quieres cambiar persistencia, watchlist o alertas

Toca:
- `database.py`

Puntos de entrada utiles:
- `save_evaluation`
- `get_previous_evaluation`
- `sync_watchlist_state`
- `generate_alerts_for_evaluation`
- `get_alerts`

### Si quieres cambiar la interfaz

Toca:
- `dashboard.py`

Recuerda:
- hoy el dashboard lee ficheros en `results/`
- no consume SQLite directamente

## 3.5 Comandos base de trabajo

### Sanity check principal

```powershell
.\.venv\Scripts\python.exe .\screener.py --quick
```

### Escaneo por mercados

```powershell
.\.venv\Scripts\python.exe .\screener.py --markets EUROSTOXX SP500
```

### Limpiar cache

```powershell
.\.venv\Scripts\python.exe .\screener.py --clear-cache
```

### Watchlist y overrides

```powershell
.\.venv\Scripts\python.exe .\screener.py --watchlist
.\.venv\Scripts\python.exe .\screener.py --override SCG.AX pausada "Esperando confirmacion"
```

### Alertas

```powershell
.\.venv\Scripts\python.exe .\screener.py --alerts
```

## 3.6 Checklist de validacion tras cada cambio

Minimo aceptable:
1. `python screener.py --quick`
2. revisar que no haya fallidas inesperadas
3. revisar que se generan CSV/XLSX si has tocado export
4. revisar `--watchlist` o `--alerts` si has tocado SQLite
5. abrir `dashboard.py` si has tocado schema visible

Si cambias columnas exportadas:
- revisar tambien `dashboard.py`, porque normaliza columnas manualmente

Si cambias la estructura de `signals_json` o persistencia:
- revisar `database.py`
- revisar compatibilidad con historicos ya guardados

## 3.7 Cosas que NO debes asumir

- No asumas que el README refleja el estado actual exacto; esta por detras.
- No asumas que la capa 2 ya analiza causalidad real; hoy es stub.
- No asumas que el dashboard muestra todo lo persistido; hoy no muestra
  watchlist/alertas SQLite.
- No asumas que todos los tickers tienen datos completos en yfinance.
- No asumas que `--quick` cubre varios mercados; hoy solo usa `ASX`.

## 3.8 Riesgos practicos al retomar

- Hay mojibake en varios mensajes heredados; no confundas eso con fallo funcional.
- `screener.py` es grande; conviene leerlo por bloques y no de arriba abajo sin plan.
- Algunas metricas historicas dependen de fallbacks; si un ticker se ve raro,
  primero comprueba si faltan datos fuente.
- La base `screener.db` es local. Si la borras, pierdes historial, watchlist y alertas.
- `results/` y `screener.db` son artefactos locales; no son la fuente de verdad del codigo.

## 3.9 Prioridades recomendadas cuando se reanude el desarrollo

Orden sugerido:
1. Consolidar documentacion y README.
2. Limpiar deuda tecnica visible (`screener.py` monolitico, encoding).
3. Implementar capa 2 causal real.
4. Conectar dashboard a SQLite para watchlist y alertas.
5. Introducir backtesting para calibrar umbrales.

## 3.10 Si eres una IA retomando el proyecto

Haz esto antes de tocar codigo:
1. leer `AGENTS.md`
2. leer `GUIA_CODEX.md`
3. leer `documentation/PROJECT_STATUS.md`
4. ejecutar o pedir `python screener.py --quick`
5. revisar `git status`

Despues:
- toca el minimo numero de archivos posible
- no cambies umbrales en `config.py` sin justificarlo
- si cambias export, revisa tambien `dashboard.py`
- si cambias persistencia, revisa compatibilidad hacia atras
