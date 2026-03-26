# DESIGN_DECISIONS

## 2.1 Enfoque general

### Por que un script Python y no una aplicacion web completa

Se eligio empezar con un script local porque el problema principal no era
la interfaz, sino el pipeline de analisis batch:
- descargar datos de cientos de tickers
- calcular metricas fundamental/valoracion/tecnico
- iterar rapidamente sobre reglas y umbrales
- exportar resultados comparables

La web completa se dejo para despues. El dashboard Streamlit se introdujo
como companion app ligera, no como nucleo del producto.

### Por que yfinance como fuente de datos

Se eligio `yfinance` por razones pragmaticas:
- gratis
- sin API key
- cubre bastantes mercados internacionales
- suficiente para un MVP orientado a exploracion y calibracion

Se acepta a cambio:
- huecos de datos
- inestabilidad puntual
- coberturas distintas segun ticker/mercado

### Por que SQLite y no PostgreSQL

Se eligio SQLite porque el uso real hoy es local y monousuario:
- no requiere servidor
- no requiere setup adicional
- permite versionar mentalmente el estado del proyecto sin complejidad
- es suficiente para historiales, watchlist y alertas en un MVP

La base de datos no busca escalar horizontalmente; busca persistencia
simple y comparacion historica.

## 2.2 Filosofia de dividendos

Decision clave:
- no descartar automaticamente empresas que han recortado o suspendido dividendo

Razon:
- en el enfoque de Gregorio, un recorte reciente puede ser parte del
  evento de panico que genera la oportunidad
- lo importante es si la empresa ERA razonable antes del bache, no si
  hoy mantiene un dividendo intacto

Consecuencias de implementacion:
- el historial de dividendos importa mas que el dividendo actual
- el dividendo actual puede dar bonus si existe
- un dividendo actual bajo o cero no penaliza por si mismo
- el recorte reciente se trata como flag informativa, no como descarte duro

## 2.3 Pipeline de 5 capas

El diseno nace de la especificacion v3 basada en la metodologia de Gregorio,
pero la implementacion actual la aterriza a datos disponibles yfinance.

### Capa 1 - Filtrado cuantitativo

Es la capa mas objetiva. Reune fundamental + valoracion.

Importante:
- conceptualmente es una sola capa
- numericamente pesa el 75 por ciento del score actual
- ese 75 por ciento se reparte en:
  - 35 por ciento fundamental
  - 40 por ciento valoracion

Esto se hizo asi porque:
- la hipotesis principal es de mean reversion fundamental/valoracion
- el tecnico ayuda al timing, pero no debe dominar el modelo

### Capa 2 - Clasificacion causal

Se dejo conectada en la arquitectura pero no implementada de verdad.
Hoy actua como placeholder con salida fija `pendiente`.

Se mantuvo aun siendo stub porque:
- el modelo de negocio la necesita
- las hard rules futuras dependen de ella
- permite reservar el punto exacto donde entrara la parte causal avanzada

### Capa 3 - Senales de recuperacion

Se implemento con datos code-based porque era la mejor forma de extraer
valor adicional sin coste de API:
- margenes estabilizando
- EPS dejando de caer
- deuda reduciendose
- dividendo mantenido
- senales internas/analistas disponibles en yfinance

La idea fue cubrir con datos objetivos una parte grande del juicio
discrecional sobre si "lo peor ha pasado".

### Capa 4 - Validacion tecnica

Se eligio una capa tecnica relativamente rica, pero siempre subordinada a
la tesis principal:
- RSI
- MACD diario
- divergencias RSI
- soportes
- volumen
- estocastico
- MACD semanal
- MA40 semanal
- doble suelo
- proxy de ruptura de directriz

Peso numerico actual:
- 25 por ciento del score

### Capa 5 - Plan operativo

Se creo para transformar analisis en accion:
- clasificacion operativa
- zonas de entrada/salida
- invalidacion
- horizonte
- tesis corta

Sin esta capa, el screener devolvia puntuaciones; con ella devuelve una
propuesta operativa interpretable.

## 2.4 Reglas duras (hard rules)

Principio central:
- las hard rules anulan el score numerico

Razon:
- una combinacion de score alto puede ocultar riesgos que invalidan la
  operacion desde la logica del metodo

Reglas hoy activas:
- si capa 1 falla -> `descarte`
- si el problema fuera potencialmente estructural -> como maximo `seguimiento`
- si no hay senales de recuperacion -> como maximo `pendiente_confirmacion`
- si no hay suelo tecnico -> como maximo `seguimiento`

La regla de deuda creciente + guidance negativo esta preparada
conceptualmente, pero sigue pendiente de disponer de datos causales fiables.

## 2.5 Clasificacion categorica vs score numerico

Decision:
- mantener el score 0-100 como referencia interna
- usar la clasificacion categorica como salida principal

Razon:
- el usuario necesita saber "que hacer", no solo "cuanto puntua"
- dos empresas con score parecido pueden no estar en el mismo punto
  operativo si las hard rules cambian el contexto

Orden actual de clasificaciones:
- `entrada_directa`
- `entrada_escalada`
- `pendiente_confirmacion`
- `seguimiento`
- `descarte`

El score ayuda a ordenar. La clasificacion manda.

## 2.6 Ajustes por sector

Se introdujeron overrides porque comparar todos los sectores con los mismos
umbrales genera falsos descartes o falsos positivos.

### Bancos / Financial Services

- D/E alto es normal por naturaleza del negocio
- P/B se vuelve mas importante
- Net debt / EBITDA deja de ser util y se ignora

### Utilities

- deuda mas alta aceptable
- PER algo mas alto aceptable

### Real Estate / REITs

- PER menos representativo
- mayor importancia relativa de yield/valor contable

### Energia

- PER bajo es normal en ciclo bajo
- no conviene interpretarlo automaticamente como gran oportunidad

## 2.7 Persistencia y seguimiento

Se eligio persistir no solo evaluaciones, sino tambien su evolucion.

Bloques implementados:
- historial de evaluaciones
- watchlist con estado actual
- historial de transiciones
- alertas automaticas
- versionado de reglas/configuracion

Razon:
- la estrategia tiene mucho valor en la transicion, no solo en la foto
- importa detectar empresas que pasan de seguimiento a entrada
- importa registrar cuando se degradan
- importa comparar ejecuciones entre fechas

SQLite cumple bien este papel sin introducir complejidad operacional.

## 2.8 Decision de no usar LLM (por ahora)

La clasificacion causal avanzada con LLM se aplazo deliberadamente.

Motivos:
- coste economico por llamada API
- dificultad de calibrar prompts y consistencia de salida
- riesgo de meter ruido narrativo demasiado pronto
- primero convenia estabilizar el pipeline cuantitativo/tecnico

Hipotesis actual:
- con capas 1, 3 y 4 bien calibradas se captura una parte importante
  del valor practico del screener
- la capa causal se retomara cuando el resto del pipeline este mas maduro
  y se quiera reducir falsos positivos cualitativos

## 2.9 Dashboard como capa secundaria

El dashboard se planteo como herramienta de revision, no como backend
principal.

Decisiones implicitas:
- lee ficheros de `results/`
- prioriza trazabilidad y visualizacion rapida
- no gobierna la logica del motor
- no es la fuente de verdad de watchlist/alertas; esa fuente es SQLite

Esto permite evolucionar el motor sin rehacer toda la interfaz en cada paso.
