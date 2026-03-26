# PROJECT_STATUS

## 1.1 Resumen ejecutivo

Este proyecto es un stock screener local en Python orientado a detectar
empresas razonables o solidas que atraviesan un bache temporal, cotizan
deprimidas frente a su normalidad y empiezan a mostrar alguna senal de
recuperacion. La inspiracion metodologica viene del enfoque de medio plazo
de Gregorio Hernandez Jimenez, pero la implementacion traduce esa idea a un
pipeline automatizado de 5 capas, reglas duras, exportacion tabular,
persistencia local y dashboard de revision.

Estado actual:
- El motor principal esta funcional y puede ejecutarse en modo rapido,
  mercados especificos o escaneo completo.
- La arquitectura de 5 capas esta implementada y operativa.
- La persistencia SQLite para evaluaciones, watchlist y alertas esta activa.
- El dashboard Streamlit existe y es util para revisar resultados, aunque
  no explota todavia toda la informacion persistida en SQLite.
- La clasificacion causal avanzada con LLM no esta implementada; la capa 2
  sigue en estado placeholder.

## 1.2 Estructura actual de archivos

- `AGENTS.md` - Instrucciones operativas para agentes que trabajan en el repo.
- `GUIA_CODEX.md` - Handoff corto de sesiones previas y notas del usuario.
- `README.md` - Documentacion de usuario; parcialmente desalineada respecto al estado actual.
- `config.py` - Configuracion centralizada: mercados, umbrales, overrides sectoriales, pesos y versionado.
- `screener.py` - Motor principal: fetch, cache, pipeline de 5 capas, hard rules, export, Markdown, CLI.
- `database.py` - Persistencia SQLite: evaluaciones, watchlist, transiciones y alertas.
- `dashboard.py` - Dashboard Streamlit para revisar resultados, graficos, fichas y filtros.
- `requirements.txt` - Dependencias minimas del proyecto.
- `.config_hash` - Estado de versionado de configuracion para detectar cambios en umbrales.
- `.gitignore` - Ignora artefactos locales como `cache/`, `results/` y `screener.db`.
- `screener.db` - Base de datos SQLite local con historial de evaluaciones, watchlist y alertas.
- `documentation/analisis_metodologia_gregorio_v3_consenso.md` - Documento base de negocio/metodologia.
- `documentation/PROJECT_STATUS.md` - Estado actual del proyecto.
- `documentation/DESIGN_DECISIONS.md` - Registro de decisiones de diseno.
- `documentation/RESUME_GUIDE.md` - Guia para retomar el proyecto.
- `documentation/pip_freeze.txt` - Congelacion real de dependencias del `.venv`.

## 1.3 Funcionalidad implementada

### Capa 1 - Filtrado cuantitativo

La capa 1 agrupa fundamental + valoracion. Usa principalmente:
- `yfinance.info`
- historicos de precio (`history`)
- estados anuales (`financials`)
- estados trimestrales (`quarterly_financials`)
- balance trimestral (`quarterly_balance_sheet`)
- historicos auxiliares serializados en cache

Metricas y reglas implementadas:
- Anos con dividendo en los ultimos 10 ejercicios.
- Dividend yield actual y bonus si sigue pagando dividendo.
- Pico historico de dividend yield estimado a 5 anos.
- Deteccion de recorte reciente de dividendo.
- Payout ratio.
- Debt to equity con overrides por sector.
- Net debt y net debt / EBITDA.
- Cambio trimestral de deuda.
- Variacion de margenes vs media de los ultimos 4 trimestres.
- ROE con suelo flexible y soft floor.
- Capitalizacion minima.
- Volumen medio diario minimo.
- PER actual.
- PER medio historico con fallbacks.
- Descuento del PER actual frente al historico.
- Price to Book.
- EV / EBITDA.
- Caida desde maximo 52 semanas.
- Caida desde maximo multianual del historico disponible.
- Distancia frente a SMA200.
- Premium de yield actual frente al yield historico estimado.

Salidas de la capa 1:
- `passed`
- `status` (`pass` / `fail`)
- `score`
- `flags`
- sub-bloques `fundamental` y `valuation`

### Capa 2 - Clasificacion causal

Estado actual:
- No esta implementada de verdad.
- Devuelve un stub fijo:
  - `causal_classification = "pendiente"`
  - `causal_confidence = 0`
  - `problem_type = "desconocido"`
  - `justification = "Pendiente de implementar"`

Impacto actual:
- Existe para respetar la arquitectura de 5 capas.
- Esta conectada a hard rules futuras, pero hoy no aporta senal real.

### Capa 3 - Senales de recuperacion

Usa solo datos accesibles desde yfinance, sin LLM. Detecta:
- `margin_stabilization`
- `eps_stabilization`
- `debt_reduction`
- `dividend_maintained`
- `insider_buying` si hay dato comparable
- `analyst_upgrade`

Salidas:
- `recovery_status` (`confirmada`, `parcial`, `ausente`)
- `recovery_score`
- `signals` con `type`, `strength`, `evidence` y puntos

### Capa 4 - Validacion tecnica

Indicadores y senales implementados:
- RSI 14.
- Deteccion de divergencias alcistas RSI/precio.
- MACD diario: cruce alcista y convergencia.
- SMA50 y SMA200.
- Volumen relativo vs media.
- Deteccion de soporte cercano.
- MACD semanal.
- Estocastico diario (14, 3, 3).
- MA40 semanal.
- Deteccion basica de doble suelo.
- Proxy de ruptura de directriz bajista.

Estados tecnicos:
- `fuerte`
- `razonable`
- `incompleto`
- `sin_suelo`

### Capa 5 - Plan operativo

Genera:
- Clasificacion final base:
  - `entrada_directa`
  - `entrada_escalada`
  - `pendiente_confirmacion`
  - `seguimiento`
  - `descarte`
- Zona de entrada (`entry_zone_min`, `entry_zone_max`, `entry_zone`).
- Zona de salida (`exit_zone_min`, `exit_zone_max`, `exit_zone`).
- Condiciones de invalidacion.
- Horizonte estimado por tramos de drawdown.
- `short_explanation`
- `summary_explanation`

Tambien genera fichas Markdown:
- una ficha `.md` por empresa del top N
- `fichas_resumen.md` consolidado por lote

### Score compuesto y hard rules

El score numerico sigue siendo 0-100, pero manda la clasificacion
categorial ajustada por hard rules.

Hard rules activas:
- Si capa 1 falla -> `descarte`
- Si problema potencialmente estructural -> como maximo `seguimiento`
- Si no hay recuperacion -> como maximo `pendiente_confirmacion`
- Si no hay suelo tecnico -> como maximo `seguimiento`
- Regla de deuda + guidance negativo preparada conceptualmente, pero hoy
  no se activa porque no hay guidance estructurado en la capa causal

### Persistencia

SQLite en `screener.db` con:
- Tabla `evaluations`
- Tabla `watchlist_states`
- Tabla `watchlist_transitions`
- Tabla `alerts`

Capacidades actuales:
- Historial de evaluaciones por ticker.
- Watchlist persistente con estados:
  - `activa`
  - `pendiente`
  - `pausada`
  - `descartada`
  - `operada`
- Overrides manuales de watchlist.
- Deteccion de transiciones relevantes de watchlist.
- Alertas automaticas con anti-spam de 48 horas.
- Versionado de evaluaciones:
  - `rules_version`
  - `model_version`
  - `config_version`
  - `evaluation_timestamp`

Tipos de alerta implementados:
- `classification_upgrade`
- `classification_downgrade`
- `technical_confirmation`
- `support_lost`
- `recovery_improved`
- `debt_warning`
- `new_opportunity`

### Exportacion

Artefactos generados en `results/`:
- `oportunidades_YYYYMMDD_HHMM.xlsx`
- `oportunidades_YYYYMMDD_HHMM.csv`
- `analisis_completo_YYYYMMDD_HHMM.csv`
- `alerts_YYYYMMDD_HHMM.csv`
- `fichas_YYYYMMDD_HHMM/`

### CLI

Comandos actuales:

```powershell
python screener.py
python screener.py --markets EUROSTOXX SP500
python screener.py --quick
python screener.py --clear-cache
python screener.py --watchlist
python screener.py --override SCG.AX pausada "Esperando confirmacion"
python screener.py --alerts
```

Comportamiento observado recientemente:
- `--quick` usa `QUICK_MARKETS = ["ASX"]`
- Modo rapido validado sobre `ASX`
- Alertas no leidas se muestran con `--alerts` y se marcan como leidas

### Dashboard Streamlit

Estado actual:
- Funcional para revisar resultados ya exportados.
- Permite lanzar el screener desde la interfaz.
- Permite elegir dataset `Operativo` o `Analisis completo`.
- Muestra graficos de precio, detalles de clasificacion, hard rules,
  versionado, tesis y fichas Markdown.

Limitacion importante:
- El dashboard trabaja sobre ficheros en `results/`, no sobre SQLite.
- No muestra todavia watchlist ni alertas persistidas de `database.py`.

## 1.4 Funcionalidad pendiente

Pendientes principales:
- Fase 3: clasificacion causal real con LLM o heuristica avanzada.
- Enriquecer la capa 2 con noticias, guidance, transcripts o datos sectoriales.
- Dashboard conectado a SQLite para watchlist, transiciones y alertas.
- Alertas push por email/Telegram.
- Backtesting de la estrategia.
- Integracion con fuentes oficiales o de pago para mejorar calidad de datos.
- Modularizacion de `screener.py` en submodulos mas pequenos.
- Limpieza de mojibake/encoding heredado en mensajes y documentos.

Sobre `PLAN_EVOLUCION_v2.md`:
- No se ha localizado ese archivo en el repo actual.
- Para documentar pendientes se ha tomado como referencia el codigo real,
  `README.md`, `GUIA_CODEX.md` y el documento metodologico de `documentation/`.

## 1.5 Limitaciones conocidas

- Dependencia fuerte de yfinance: puede devolver huecos, `HTTP 500`,
  datos incompletos o inconsistencias por mercado.
- Algunos calculos historicos dependen de cobertura real de Yahoo y por
  tanto caen a fallbacks.
- `screener.py` es grande y concentra demasiada logica.
- Existen restos legacy y deuda tecnica menor; conviene consolidar
  helpers duplicados y limpiar mensajes heredados.
- El dashboard no es una capa operativa completa; es un visor sobre
  `results/`, no un front-end de la base SQLite.
- No hay suite automatica de tests unitarios/integracion.
- La capa causal no discrimina todavia problemas temporales vs estructurales.
- Watchlist y alertas son locales a `screener.db`; no hay sincronizacion
  remota ni multiusuario.
- El anti-spam de alertas esta basado en ventana temporal local de 48h.
- En entornos restringidos puede aparecer el error interno de SQLite de
  yfinance mencionado en `GUIA_CODEX.md`.

## 1.6 Dependencias y versiones

Version de Python observada en `.venv`:
- Python 3.13.5

Paquetes clave instalados:
- `yfinance==1.2.0`
- `pandas==2.3.3`
- `numpy==2.4.3`
- `ta==0.11.0`
- `rich==14.3.3`
- `requests==2.32.5`
- `openpyxl==3.1.5`
- `lxml==6.0.2`
- `streamlit==1.55.0`
- `altair==6.0.0`

Dependencias minimas declaradas en `requirements.txt`:
- `yfinance>=0.2.36`
- `pandas>=2.0.0`
- `numpy>=1.24.0`
- `ta>=0.11.0`
- `rich>=13.0.0`
- `requests>=2.31.0`
- `openpyxl>=3.1.0`
- `lxml>=5.0.0`
- `streamlit>=1.40.0`

Freeze completo del entorno:
- Ver `documentation/pip_freeze.txt`
