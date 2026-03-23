# STREAMLIT_CLOUD_DEPLOY

## Repo y entrypoint

- Repo: `manuelcarmonadlc/stock_screener`
- Branch: `main`
- Main file path: `dashboard.py`

## Checklist previo

- `requirements.txt` en la raiz del repo
- `dashboard.py` en la raiz del repo
- `.streamlit/config.toml` en la raiz del repo
- datos de ejemplo ya incluidos en `results/`

## Despliegue en Streamlit Community Cloud

1. Ir a `https://share.streamlit.io/`
2. Pulsar `Create app`
3. Seleccionar el repo `manuelcarmonadlc/stock_screener`
4. Elegir la rama `main`
5. Indicar `dashboard.py` como entrypoint
6. En `Advanced settings`, seleccionar la version de Python
7. Desplegar la app

## Configuracion recomendada

- Python recomendado: `3.13` si aparece disponible en el selector
- Si no aparece, usar la version soportada mas alta compatible y revisar logs

## Notas operativas

- Community Cloud copia el repo y ejecuta la app desde la raiz del repositorio.
- La configuracion personalizada de Streamlit debe estar en `.streamlit/config.toml` en la raiz.
- La app deberia arrancar mostrando el dashboard incluso sin nuevos escaneos, porque el repo incluye un lote reciente dentro de `results/`.
- El boton de escaneo del dashboard ejecuta `screener.py`; esto puede tardar y depende de yfinance.

## Si algo falla al desplegar

Revisar en este orden:
1. logs de Streamlit Cloud
2. version de Python seleccionada en `Advanced settings`
3. instalacion de dependencias desde `requirements.txt`
4. permisos del repositorio en Streamlit Cloud
5. rutas relativas desde la raiz del repo
