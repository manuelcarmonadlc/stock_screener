# Metodología de Gregorio Hernández Jiménez — Operaciones de Medio Plazo

## Informe v3 — Versión consolidada para diseño de herramienta de detección

---

## 1. Resumen ejecutivo

Gregorio sigue un proceso discrecional de mean reversion sobre empresas razonables o sólidas, afectadas por un problema identificable y en principio temporal, que cotizan con una valoración deprimida respecto a su normalidad o a comparables, y donde empieza a aparecer alguna evidencia de estabilización o recuperación. El análisis técnico no define la tesis, pero sí ayuda a decidir el timing de entrada y salida.

Este informe distingue dos niveles:

- **Nivel metodológico**: lo que creemos que describe fielmente el enfoque de Gregorio, extraído directamente del material analizado.
- **Nivel de implementación**: heurísticas y parámetros necesarios para construir un screener operativo, derivados de los casos observados pero que no forman parte explícita del método declarado de Gregorio.

Esta separación es importante porque el material analizado (~15 operaciones documentadas con sus seguimientos, más varias candidatas descartadas o en lista de espera) permite extraer la lógica del método con alta confianza, pero no permite derivar reglas estadísticas cerradas. Estamos viendo operaciones seleccionadas y comentadas públicamente, no un track record completo con las fallidas.

---

# PARTE I — NIVEL METODOLÓGICO

## Lo que Gregorio hace (con alta confianza)

---

## 2. Universo de empresas: razonables y entendibles

Gregorio no opera con cualquier empresa. Filtra por calidad y comprensibilidad.

### 2.1 Jerarquía de calidad explícita

Clasifica las empresas en niveles y destina cada nivel a una estrategia diferente. Lo dice abiertamente en múltiples posts:

- **Primera división** → largo plazo. Procter & Gamble, Adidas, Nike, BASF, Ferrari, CIE.
- **Segunda división / justo por debajo** → medio plazo preferente. Clorox, Puma, Hugo Boss, Lyondellbasell, Gestamp, Mondi, Porsche (acciones preferentes), Unicaja.
- **Tercera división / demasiado cíclicas o pequeñas** → medio plazo con cautela extra. Lingotes Especiales, Inmocemento.
- **Calidad insuficiente o negocio poco conocido** → descarta o exige condiciones extremas. Telecom Italia, Alexandria RE.

Las empresas de "segunda división" deben comprarse a múltiplos más bajos que las de "primera", porque el múltiplo de salida probable será menor. Esto lo dice explícitamente al hablar de Puma respecto a Adidas y Nike.

En muchos casos la empresa también sería apta para largo plazo (Nike, Porsche, Gestamp), pero Gregorio la trata como medio plazo para optimizar la rotación de capital, o bien por algún matiz (como las acciones preferentes de Porsche, que no le gustan para mantener indefinidamente).

### 2.2 Patrón de empresa comparable superior

Un mecanismo recurrente para generar candidatas es compararlas con empresas de mayor calidad del mismo sector:

| Candidata medio plazo | Referente superior (largo plazo) | Sector |
|----------------------|--------------------------------|--------|
| Clorox | Procter & Gamble | Consumo hogar |
| Puma | Adidas / Nike | Material deportivo |
| Hugo Boss | Burberry | Moda/lujo |
| Lyondellbasell | BASF | Química |
| Lingotes | CIE / Gestamp | Componentes automóvil |
| Porsche | Ferrari | Automóvil premium |
| Unicaja | BBVA / Santander | Banca |

### 2.3 Penalización por opacidad

Cuando el negocio es más especializado o difícil de monitorizar para un particular, Gregorio sube significativamente su nivel de prudencia. En Alexandria RE lo explicita: "con una empresa así debemos ser más prudentes, y eso se traduce en invertir menos dinero y en esperar a que la oportunidad parezca muy clara". No es solo que no entienda el negocio — es que la incertidumbre sobre si el problema es temporal o estructural se vuelve demasiado alta.

---

## 3. Naturaleza del problema: temporal y comprensible

Este es probablemente el filtro más importante y el más difícil de automatizar.

### 3.1 El problema debe parecer temporal, no estructural

Le atraen caídas por:

- Márgenes deprimidos por inflación o costes (Clorox, Mondi).
- Litigios largos pero acotables, con negocio intacto (Bayer).
- Reestructuraciones y transiciones de producto (Nike, Porsche).
- Debilidad cíclica del sector (Gestamp, Lingotes, Mondi).
- Distorsiones operativas puntuales: cambio de sistema informático (Clorox), transición de gama de modelos (Porsche).
- Pánico de mercado: caída exagerada tras resultados (Kyndryl).

### 3.2 Cuantificable y con horizonte de resolución

Gregorio siempre intenta acotar cuándo empezará la recuperación. No se conforma con "ya subirá en algún momento". Busca un horizonte: "Porsche espera que en 2026 empiece a mejorar", "en 2027 Puma probablemente se acercará al BPA de 2,36€".

### 3.3 El gran riesgo: confundir deterioro estructural con problema temporal

El caso de Alexandria RE es muy ilustrativo. Un usuario del Club aporta un análisis detallado sobre los cambios regulatorios en EEUU que afectan al sector life-science, y ese análisis cuestiona si el problema es realmente temporal. Gregorio lo acepta y no abre la operación. Esto muestra que el riesgo de value trap está presente en el método y que Gregorio lo gestiona con prudencia, pero también con las limitaciones propias de un análisis discrecional.

---

## 4. Valoración deprimida respecto a normalidad

No busca empresas simplemente baratas. Busca desviaciones fuertes respecto a la situación normalizada del negocio. La diferencia es sutil pero importante: un PER de 8 en una empresa que siempre ha cotizado a PER 8 no le interesaría; un PER de 8 en una empresa que normalmente cotiza a PER 15, sí.

### 4.1 Métricas que usa (no una sola, sino un abanico)

- **PER sobre beneficios normalizados** o pre-crisis. Es la métrica más frecuente. En Lingotes mira el BPA previo al deterioro; en Mondi usa el PER de 2022; en Bayer usa el BPA ordinario ajustado.
- **Descuento sobre valor contable**. Especialmente en bancos (Unicaja a 0,5-0,7x VC) e inmobiliarias (Inmocemento a 0,65x VC).
- **Comparación con pares**. Telecom Italia cotiza barata, pero también lo están sus competidores mejores, así que no hay ventaja diferencial.
- **Rentabilidad por dividendo**. Como señal auxiliar de infravaloración, no como objetivo de la operación. Mondi al 7%, Gestamp al 5,8%, Unicaja al 8-10%.
- **Ajuste por calidad relativa**. Las empresas de "segunda división" deben comprarse a PER más bajo que las de primera, porque el múltiplo de salida será menor.

### 4.2 Rangos observados en los casos documentados

| Empresa | BPA de referencia | PER al precio de compra |
|---------|------------------|------------------------|
| Bayer | 5,00-5,05 € (ordinario) | 5-7x |
| Gestamp | BPA 2023 | 5,2x |
| Unicaja | BPA 2024 | ~9x (+ cotizaba a 0,5x VC) |
| Porsche | BPA 2023 | <8x |
| Nike | BPA 2024 = 3,73$ | 17,5x (empresa de crecimiento) |
| Clorox | BPA normalizado ~6$ | 17x (consumo defensivo) |
| Mondi | BPA 2022 = 1,96 GBP | 4,4x |
| Lingotes | BPA pre-crisis ~1€ | 5x |
| Inmocemento | BPA 2024 | 10x (+ descuento 35% sobre VC) |

El patrón muestra PER normalizados típicamente en 4x-10x para cíclicas, y hasta 15-18x para empresas de crecimiento o consumo defensivo. Pero estos rangos son observaciones, no reglas declaradas.

### 4.3 Deuda: controlada aunque esté elevada

El ratio deuda neta / EBITDA es su indicador principal de riesgo financiero. Lo que busca no es un número fijo sino que la deuda sea soportable dentro del bache:

- Cuando el EBITDA del año en curso es negativo o atípico, calcula con el último EBITDA positivo o con el previo a los problemas.
- La tendencia de la deuda importa tanto como el nivel: si se está reduciendo activamente, es señal positiva (Bayer). Si crece en un momento bajo del ciclo, es señal negativa (Lyondellbasell).
- Lyondellbasell es el caso más claro de freno por deuda: barata y técnicamente interesante, pero no entra porque "si la recuperación no es rápida podrían seguir cayendo los resultados, subiendo la deuda, y que bajase el dividendo".

---

## 5. Evidencia de recuperación incipiente

Esta dimensión merece aislarse porque Gregorio no entra en el punto de máximo deterioro sin ninguna señal de estabilización. No necesita una recuperación plena, pero sí al menos un dato que sugiera que lo peor ha pasado o empieza a pasar:

- **Bayer**: BPA ordinario ya subiendo (+7% en Q3 2025), deuda neta bajando 6,5%.
- **Clorox**: "los beneficios ya se han recuperado, prácticamente", márgenes restaurados.
- **Lingotes**: empresas del sector reportaron mejor de lo esperado en Q3, aunque Lingotes no presenta resultados trimestrales.
- **Mondi**: "en los últimos meses empieza a mejorar el margen de beneficios".
- **Porsche**: expectativa de mejora en 2026, costes extraordinarios acotados en el tiempo.
- **Nike**: reorganización "bien encaminada", recuperando canales de venta tradicionales.

En otros casos donde esta señal no existe o no es clara (Alexandria RE), Gregorio se abstiene o pone la empresa en seguimiento.

---

## 6. Análisis técnico como filtro de timing

El fundamental es el filtro primario y la tesis principal. El técnico sirve para no entrar demasiado pronto y para mejorar la asimetría. Gregorio nunca entra solo por técnico y nunca entra solo por fundamental. Necesita ambos alineados.

### 6.1 Caja de herramientas técnica

No hay una receta rígida ni un checklist fijo. Hay un conjunto recurrente de herramientas que aplica con flexibilidad según el caso:

- **MACD** (mensual y semanal): sobreventa extrema, giro al alza, divergencia alcista. Es el indicador que más repite.
- **MACDH / histograma** (semanal): divergencia alcista.
- **Media de 200** (mensual y diaria): soporte de largo plazo, zona de compra.
- **RSI** (semanal): divergencia alcista (menos frecuente que MACD).
- **Estocástico** (diario): timing fino de entrada.
- **A/D — Acumulación/Distribución** (diario): divergencia alcista como señal de compra institucional.
- **Figuras de velas**: Suelo de Torres, Envolvente alcista/bajista, Estrella del Atardecer, Doble Suelo.
- **Directrices y líneas de tendencia** (mensual): ruptura de directriz bajista como señal de cambio.
- **Soportes de precio**: mínimos previos, canales laterales.

### 6.2 Lo que busca en el técnico

La idea general es confluencia de señales que sugieran que el suelo se está formando o ya se formó. Típicamente combina varias de estas piezas:

- MACD mensual muy por debajo de 0 y empezando a girar al alza.
- Divergencia alcista en algún indicador (MACD, MACDH, RSI, A/D) en gráfico semanal o diario.
- Cotización en o cerca de un soporte importante.
- Formación de suelo visible: movimiento lateral prolongado, doble suelo, suelo de torres.
- Proximidad de ruptura de directriz bajista de largo plazo.

No necesita todas. Generalmente confluyen varias, pero la combinación varía según el caso.

### 6.3 Proceso top-down para el análisis

1. **Mensual**: visión de largo plazo, posición del MACD, divergencias, medias de 200, soportes de largo plazo.
2. **Semanal**: confirmación de suelo, divergencias, canales y directrices.
3. **Diario**: timing fino de entrada, medias de 40 y 200, Estocástico, A/D, figuras de velas de confirmación.

### 6.4 Señales de salida

La venta se decide por combinación de factores, no por un único disparador:

- Llegada a zona de objetivo (resistencia técnica predefinida o valoración de recuperación).
- Resistencia técnica fuerte que no consigue romper (Bayer en la media mensual de 200).
- Señales de techo: Envolvente Bajista, Estrella del Atardecer, MACD girando a la baja desde arriba.
- Situación general del mercado: si anticipa caída general, vende las posiciones más débiles para tener liquidez.
- Subida demasiado brusca sin consolidación.
- Tiempo consumido: si una resistencia puede atascar el valor muchos meses, prefiere vender y reciclar capital.

**Punto crítico**: no espera a que se resuelva el problema fundamental. En Bayer: "compramos cuando se produjo un extremo de pánico por los juicios y hemos vendido con una buena rentabilidad sin necesidad de que ese tema se resuelva". La tesis de medio plazo es la recuperación parcial de precio, no la normalización total del negocio.

---

## 7. Gestión de la operación

### 7.1 Modos de entrada

Gregorio no siempre entra igual. Del material se distinguen tres patrones según el nivel de convicción y la claridad de la señal:

**Entrada directa con posición completa.** Cuando fundamentales y técnico coinciden de forma muy clara y el precio está en un soporte extremo. Así lo hace en Clorox ("invierto ahora todo el dinero previsto, porque está en la media mensual de 200"). Es la excepción, no la norma.

**Entrada escalada.** Es el modo más frecuente. Entra con la mitad del dinero previsto y reserva la otra mitad para: comprar si cae significativamente más, o no comprar si sube (preservando esa mitad para otra operación), o comprar la segunda mitad si el tiempo transcurrido confirma la tesis. Regla explícita: "tan pronto no meto nunca la otra mitad".

**Entrada afinada por confirmación en diario.** Espera una señal concreta en el gráfico diario antes de ejecutar. El ejemplo más claro es Kyndryl: tras la caída fuerte, espera a que un día cierre por encima del máximo de la sesión de pánico. Solo cuando se produce ese cierre, compra.

### 7.2 No perseguir precios escapados

Gregorio insiste varias veces en no comprar si el precio ya se ha movido significativamente desde el punto ideal. En Lingotes, tras la subida brusca del 25%: "yo ahora sólo compraría si vuelve hacia la zona de los 5-5,20 euros". En Clorox, cuando ya lleva +14%: "yo a este precio no compraría la otra mitad, porque el beneficio ya se va estrechando". En Amadeus: "para medio plazo esperaría a ver si cae más".

### 7.3 Horizonte, objetivo y salida

- **Horizonte objetivo**: 6 meses a 2 años. El momento de venta se busca según cotización y situación, no por calendario.
- **Objetivo de venta**: siempre un rango, nunca un precio exacto. El rango superior suele coincidir con una resistencia técnica importante o una valoración de recuperación razonable. Ratios de multiplicación observados: típicamente 1,3x-2,0x sobre precio de compra, con outliers como Unicaja.
- **Pocas operaciones, bien seleccionadas**: "hago pocas operaciones al año, sólo cuando veo oportunidades que me parecen especialmente claras. Por eso espero rentabilidades más altas."
- **Tiempo como variable activa**: en medio plazo importa "el tiempo en el que se consiguen las rentabilidades". Si una posición se estanca en una resistencia, prefiere vender y reciclar capital.
- **Rotación activa**: cuando vende una operación, busca activamente la siguiente. Vendió Bayer para comprar Lingotes.

### 7.4 Stops

Norma general: no usa stops en medio plazo. Confía en la valoración fundamental como protección. Excepciones: empresas con más riesgo (Grifols: sugirió stop) y posiciones con buena ganancia acumulada donde quiere proteger beneficios (Bayer: stop en 42-43€ tras la subida).

### 7.5 Opciones y derivados

Herramienta complementaria, no principal:

- Venta de Put para entrar: reduce el precio efectivo de compra (Bayer).
- Venta de Call cubierta: incrementa rentabilidad cuando tiene las acciones (CIE, Enagás). Riesgo cero si tiene las acciones.
- CFDs: para separar fiscalmente posiciones de medio y largo plazo de la misma empresa.
- Regla absoluta: nunca vender Call descubierta.

### 7.6 Compartimentos separados

Largo plazo y medio plazo son operativas distintas con dinero distinto. Una operación de medio plazo puede pasar a largo plazo, pero nunca al revés.

---

## 8. Factores de descarte

Razones documentadas para no entrar o posponer:

1. **Valoración insuficientemente barata.** SAP a PER 36. Amadeus "para medio plazo esperaría a ver si cae más".
2. **Negocio demasiado opaco o incertidumbre estructural alta.** Alexandria RE.
3. **Deuda o ciclo con riesgo de empeorar.** Lyondellbasell.
4. **Ausencia de suelo técnico claro.** Alexandria RE: "de momento no hay suelo claro".
5. **Precio ya escapado.** Lingotes tras subida del 25%, Clorox a +14%.
6. **Mejor alternativa disponible.** Vendió Bayer para rotar a Lingotes.

---

# PARTE II — NIVEL DE IMPLEMENTACIÓN

## Heurísticas para construir la herramienta

**Todo lo que sigue son parámetros iniciales de calibración derivados de los casos observados, no reglas literales del método de Gregorio. Deben ajustarse con la experiencia de uso.**

---

## 9. Arquitectura del screener: 5 capas

La herramienta no debe buscar "acciones muy caídas y baratas", sino casos de recuperación plausible donde confluyan negocio suficiente, problema temporal, infravaloración frente a normalidad, primeras señales de mejora y timing técnico razonable.

### Capa 1 — Filtrado cuantitativo

Objetivo: reducir el universo a un número manejable de candidatas que cumplan las condiciones numéricas mínimas.

Parámetros iniciales de calibración (sujetos a ajuste):

| Parámetro | Rango orientativo | Base de inferencia |
|-----------|-------------------|-------------------|
| Caída desde máximos | >30% (zona más fértil: >50%) | Nike -70%, Bayer -75%, Porsche -65%, Mondi -55% |
| PER normalizado | <12x cíclicas, <20x crecimiento | Zona observada: 4x-10x cíclicas, 15-18x crecimiento |
| PER actual vs. media histórica de la empresa | Descuento significativo | Concepto de mean reversion; no hay % fijo en el material |
| Precio / Valor contable | <1,0x cuando aplica | Inmocemento 0,65x, Unicaja 0,5-0,7x |
| Deuda neta / EBITDA normalizado | Preferible <3x | Bayer ~3x aceptable, Lyondellbasell 3,6x = freno |
| Tendencia de deuda neta | Estable o bajando | Alerta si crece trimestre a trimestre |
| Rentabilidad por dividendo | Elevada vs. histórico (si paga) | Señal auxiliar, no requisito |
| Capitalización | Sin umbral fijo, pero mayor liquidez = menor fricción | Gregorio opera con empresas de todos los tamaños |

Lo que estas cifras NO son: reglas fijas de Gregorio ni umbrales validados estadísticamente. Son puntos de partida razonables extraídos de los 15 casos documentados.

### Capa 2 — Clasificación causal

Objetivo: distinguir entre problema temporal y deterioro estructural. Esta es la capa donde la IA generativa tiene más valor añadido.

Inputs sugeridos para el modelo:

- Earnings calls y transcripciones de resultados recientes.
- Guidance de la empresa y consensus de analistas.
- Contexto sectorial: ¿las demás empresas del sector también sufren, o es un problema específico?
- Naturaleza del problema: ¿cíclico, litigio, reestructuración, transición operativa, regulatorio?
- Historial: ¿la empresa ha salido antes de baches similares?

Output esperado: clasificación (temporal / probablemente temporal / incierto / potencialmente estructural) con justificación.

Señales de alerta de deterioro estructural (heurísticas, no reglas duras):

- Beneficios cayendo durante muchos años consecutivos sin señales de estabilización.
- Deuda creciendo trimestre a trimestre mientras los ingresos caen.
- Pérdida permanente de ventaja competitiva o cambio regulatorio adverso no reversible.
- Competidores de mayor calidad igual de baratos o más baratos (caso Telecom Italia).

### Capa 3 — Validación de recuperación

Objetivo: confirmar que hay al menos alguna señal de que lo peor ha pasado o empieza a pasar.

Señales a buscar (cualquiera de ellas sirve):

- Márgenes que dejan de caer o empiezan a mejorar en el último trimestre.
- Deuda que empieza a bajar.
- Guidance estabilizado o ligeramente positivo.
- Mejora operativa incipiente: nuevos productos, recortes de costes en marcha, pedidos mejorando.
- Empresas del mismo sector reportando mejor de lo esperado.
- Recompras de acciones o comportamiento accionarial que sugiere confianza interna.

Si no hay ninguna señal de estabilización → watchlist, no operación.

### Capa 4 — Validación técnica

Objetivo: verificar que la ventana de entrada sigue abierta y que hay señales de suelo o activación.

Señales a evaluar (scoring, no checklist binario):

- MACD mensual por debajo de 0 y girando al alza o con divergencia alcista.
- Cotización en o cerca de soporte mayor (media de 200, mínimos previos, valor contable).
- Divergencia alcista en al menos un indicador (MACD, MACDH, RSI, A/D) en semanal o diario.
- Figura de suelo visible: doble suelo, suelo de torres, canal lateral, ruptura de directriz bajista.
- Patrón Kyndryl: tras caída brusca en un día, esperar cierre por encima del máximo de la sesión de pánico.

Filtros de descarte:

- Si el precio ya ha subido considerablemente desde el soporte reciente, la ventana puede estar cerrándose. No hay un porcentaje canónico, pero el material sugiere que Gregorio pierde interés cuando el recorrido remanente ya no compensa.
- Si no hay ninguna señal técnica de suelo, el screener debería mover la candidata a watchlist aunque pase las capas 1-3.

### Capa 5 — Plan operativo

Objetivo: clasificar la oportunidad y sugerir modo de actuación.

| Clasificación | Condiciones | Acción sugerida |
|--------------|------------|----------------|
| **Entrada directa** | Capas 1-4 superadas con señales fuertes, soporte extremo | Posición completa |
| **Entrada escalada** | Capas 1-4 superadas con señales buenas pero margen de caída adicional | Media posición, reservar otra media |
| **Pendiente de confirmación** | Capas 1-3 superadas, capa 4 parcial | Watchlist activa, alerta si confirma |
| **En seguimiento** | Capa 1 superada, capas 2-3 parciales | Watchlist pasiva, revisar trimestralmente |
| **Descarte** | Capa 1 no superada, o clasificación "estructural" en capa 2 | No operar |

Elementos del plan operativo:

- **Zona de compra**: precio o rango donde la operación tiene sentido.
- **Zona de salida**: rango de resistencias o valoración de recuperación. Típicamente 1,3x-2,0x sobre precio de compra.
- **Horizonte estimado**: 6 meses a 2 años.
- **Señales de invalidación**: qué tendría que pasar para cerrar la operación con pérdidas o reconsiderar la tesis.

---

## 10. Universo geográfico y sectorial

### Lo que Gregorio cubre

- **Geográficamente**: Europa (España, Alemania, Italia, UK) y EEUU.
- **Sectores recurrentes**: consumo (Clorox, Nike, Puma, Hugo Boss), industria/automóvil (Gestamp, Lingotes, Porsche), químico/farma (Bayer, Lyondellbasell), financiero (Unicaja), materiales (Mondi, Inmocemento).
- **Lo que evita**: tecnológicas puras, empresas de "nueva economía", SPACs, empresas sin beneficio histórico positivo.

### Oportunidades de ampliación para el screener

- **Mercados fuera de su radar**: empresas nórdicas, japonesas, coreanas, australianas, canadienses con el mismo perfil de mean reversion.
- **Mid-caps poco cubiertas**: 1.000-10.000M€ fuera de índices principales. Menor cobertura de analistas = mayor probabilidad de ineficiencia.
- **Velocidad de detección**: un sistema automatizado detecta señales antes que un análisis manual con retraso de publicación.
- **Screening sistemático de divergencias técnicas**: barrido automático de MACD mensual sobrevendido + girando al alza, cruzado con valoración deprimida.

---

## 11. Resultados observados en las operaciones documentadas

Para contexto, no como promesa de rentabilidad:

| Operación | Compra | Venta | Rentabilidad | Duración |
|-----------|--------|-------|-------------|----------|
| Bayer | 26,74 € | 42,20 € | +56% | 19 meses |
| Unicaja | 0,91 € | 2,39 € | +163% (+183% con dividendos) | ~12 meses |
| Gestamp | 2,54 € | 3,15 € | +24% (+26% con dividendo) | 10 meses |
| CIE (OPA) | 22 € | 24 € + primas | +10,5% (anualizado ~50%) | 2,5 meses |
| Naturgy (OPA) | 25,20 € | Venta + dividendo + Put | +9,5% (anualizado ~28,5%) | 4 meses |

Operaciones abiertas al momento de redacción del material: Nike, Clorox, Mondi, Lingotes, Inmocemento, Porsche, Kyndryl, Enagás.

**Advertencia**: estas son las operaciones documentadas públicamente. No sabemos si hay operaciones fallidas no publicadas, ni si la muestra es representativa del rendimiento real del método.

---

## 12. Síntesis final

La herramienta no debe buscar acciones muy caídas y baratas. Debe buscar casos de recuperación plausible donde confluyan:

1. **Negocio suficiente**: empresa razonable, entendible, con calidad aceptable.
2. **Problema temporal**: caída causada por algo identificable, comprensible y con horizonte de resolución.
3. **Infravaloración frente a normalidad**: valoración deprimida respecto a la situación normalizada del negocio, no simple PER bajo.
4. **Primeras señales de mejora**: alguna evidencia de que el deterioro se estabiliza o empieza a revertir.
5. **Timing técnico razonable**: señales de suelo o activación que sugieran que el mercado empieza a dejar atrás el peor miedo.

Esa es, con alta confianza, la esencia del método de Gregorio aplicada a medio plazo.
