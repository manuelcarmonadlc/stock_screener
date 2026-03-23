# 🎯 Stock Opportunity Screener v1.0

**Detector de valor temporal deprimido** — Localiza empresas sólidas (tipo buy&hold con dividendos) que están temporalmente infravaloradas, con confirmación de análisis técnico.

Inspirado en la estrategia de medio plazo de Gregorio Hernández Jiménez.

---

## Instalación

```bash
# 1. Crear entorno virtual (recomendado)
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
# .venv\Scripts\activate        # Windows

# 2. Instalar dependencias
pip install -r requirements.txt
```

## Uso

```bash
# Escaneo completo (todos los mercados activos)
python screener.py

# Solo mercados específicos
python screener.py --markets EUROSTOXX SP500

# Prueba rápida (mercados definidos en QUICK_MARKETS, por defecto ASX)
python screener.py --quick

# Limpiar caché y re-escanear
python screener.py --clear-cache
```

## Qué hace

El screener aplica **tres capas de filtrado** a cada empresa:

### Capa 1 — Calidad Fundamental (35%)
- **Historial** de dividendos (años pagando en los últimos 10, no consecutivos)
- Dividendo actual: bonus si aún paga, pero **no penaliza si es cero** (puede ser temporal)
- Detección de recorte reciente de dividendo (señal de oportunidad, no de descarte)
- Deuda/Equity controlada (ajustado por sector) — crítica para sobrevivir al bache
- ROE con suelo flexible (ROE deprimido es aceptable si no es negativo)
- Capitalización mínima (evitar chicharros)

### Capa 2 — Infravaloración Temporal (40%)
- PER por debajo de umbral (ajustado por sector)
- Caída significativa desde máximo 52 semanas (15-60%)
- Price/Book razonable
- Precio por debajo de SMA200

### Capa 3 — Timing Técnico (25%)
- RSI en zona de sobreventa o recuperación
- MACD: cruce alcista o convergencia
- SMA50 girando al alza
- Volumen creciente (confirmación compradora)
- Cercanía a niveles de soporte

### Resultado
Cada empresa recibe un **score 0-100** ponderado:
- 🟢 **≥75**: Oportunidad fuerte
- 🟡 **≥60**: Oportunidad moderada
- 🔵 **≥55**: Vigilar
- ⚪ **<55**: No cumple criterios

## Configuración

Edita `config.py` para ajustar:

- **Universo de mercados**: Añade/quita tickers en `MARKETS`
- **Umbrales fundamentales**: Dividendo mínimo, deuda máxima, etc.
- **Umbrales de valoración**: PER máximo, caída mínima/máxima, etc.
- **Parámetros técnicos**: Periodos RSI/MACD, umbrales de sobreventa, etc.
- **Ajustes por sector**: Overrides para bancos, utilities, REITs, etc.
- **Ponderaciones**: Peso de cada capa en el score final

## Output

Genera automáticamente en la carpeta `results/`:
- `oportunidades_YYYYMMDD_HHMM.xlsx` — Top oportunidades con detalle
- `oportunidades_YYYYMMDD_HHMM.csv` — Mismo en CSV
- `analisis_completo_YYYYMMDD_HHMM.csv` — Todas las empresas analizadas

## Mercados incluidos

| Mercado    | Tickers | Cobertura |
|------------|---------|-----------|
| EUROSTOXX  | ~90     | DAX, CAC40, AEX, FTSE MIB, BEL20, PSI, OMX, SMI, FTSE100 |
| SP500      | ~80     | Dividend Aristocrats + Value + Tech value |
| ASX        | ~30     | ASX principales |
| ASIA       | ~50     | Nikkei, Hang Seng, KOSPI, SGX |

## Tiempos estimados

- `--quick` (QUICK_MARKETS): ~2-4 minutos
- Un mercado: ~5-10 minutos
- Todos los mercados: ~20-40 minutos

## Limitaciones

- Los datos vienen de Yahoo Finance (gratuito). Puede haber huecos o datos incompletos, especialmente en mercados asiáticos.
- El análisis técnico es orientativo. Siempre confirmar visualmente el gráfico antes de operar.
- Los ajustes por sector son aproximados. Revisar manualmente empresas de sectores atípicos.
- El PER histórico y el dividend yield histórico de 5 años dependen de la cobertura de yfinance. En algunos tickers faltarán datos y el screener caerá a métodos de fallback.

## Roadmap v2

- [x] PER medio real de 5 años
- [x] Dividend yield medio de 5 años
- [x] Detección de divergencias RSI/precio
- [ ] Alertas automáticas por email/Telegram
- [x] Dashboard web interactivo
- [ ] Integración con API de CNMV/SEC para datos oficiales
- [ ] Backtesting de la estrategia con datos históricos

---

**Disclaimer**: Esta herramienta es solo para fines educativos e informativos. No constituye asesoramiento financiero. Toda decisión de inversión es responsabilidad del usuario.
