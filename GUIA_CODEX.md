# GUIA_CODEX

## Objetivo del proyecto

Stock Opportunity Screener para detectar empresas solidas temporalmente
infravaloradas, con cruce de filtros fundamentales, de valoracion y tecnicos.

Archivos principales:
- `config.py`: mercados, umbrales y configuracion
- `screener.py`: motor de analisis y export
- `dashboard.py`: dashboard Streamlit
- `requirements.txt`: dependencias

## Decisiones de producto ya tomadas

- `IBEX` queda fuera de scope.
- `IBEX` ya no esta en `config.MARKETS`.
- `--quick` ya no usa IBEX.
- `QUICK_MARKETS = ["ASX"]`.
- No hace falta volver a abrir debate sobre seguimiento del IBEX.

## Estado actual implementado

Ya estan implementados:
- calculo de PER medio real 5 anos con fallbacks de yfinance
- comparacion del dividend yield actual vs media 5 anos
- deteccion de divergencias alcistas RSI
- dashboard Streamlit separado en `dashboard.py`
- limpieza de tickers invalidos de yfinance
- reutilizacion real de cache local
- trazabilidad de errores por ticker
- export `analisis_completo_*.csv` con columnas:
  `Ticker, Nombre, Mercado, Score, Paso_Filtro, Estado, Error`

## Verificacion mas reciente

Fecha de referencia: `2026-03-22`

Verificado en entorno real:
```powershell
.\.venv\Scripts\python.exe .\screener.py --quick
```

Resultado mas reciente:
- mercado rapido: `ASX`
- `29` analizadas
- `0` fallidas
- `13` oportunidades

Notas:
- En sandbox/restricciones puede aparecer:
  `OperationalError: unable to open database file`
- En entorno real del proyecto el screener funciona.
- Yahoo puede devolver `HTTP 500 internal-error` puntualmente sin romper la ejecucion.

## Forma de trabajar preferida por el usuario

- Hacer cambios minimos y explicitos.
- Priorizar pocos ficheros por iteracion.
- No tocar secretos ni leer `.env`.
- Dar al final comandos exactos de:
  - `git status`
  - `git add ...`
  - `git commit -m ...`
  - `git push`
- Si una tarea exige ejecutar comandos o tocar entornos, confirmarlo con el usuario.

## Pendientes no bloqueantes

- Limpiar texto mojibake/encoding en mensajes y comentarios heredados.
- Mejorar la robustez frente al problema SQLite interno de `yfinance` en entornos restringidos.
- Si interesa, ampliar `dashboard.py` para mostrar tambien filas con `Estado=ERROR`.

## Si abres una sesion nueva de Codex

Orden recomendado para coger contexto:
1. Leer `AGENTS.md`
2. Leer este archivo `GUIA_CODEX.md`
3. Revisar `config.py`
4. Revisar `screener.py`
5. Ejecutar o pedir `python screener.py --quick`

## Nota sobre git

Este archivo describe decisiones y estado funcional, no garantiza el estado
exacto del staging area. Antes de continuar, comprobar:

```powershell
git status
```
