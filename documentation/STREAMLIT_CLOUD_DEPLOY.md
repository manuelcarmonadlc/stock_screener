# STREAMLIT_CLOUD_DEPLOY

## Repo y entrypoint

- Repo: `manuelcarmonadlc/stock_screener`
- Branch: `main`
- Main file path: `dashboard.py`

## Checklist previo

- `requirements.txt` en la raiz del repo
- `requirements_streamlit.txt` disponible si quieres aislar dependencias de cloud
- `dashboard.py` en la raiz del repo
- `.streamlit/config.toml` en la raiz del repo
- `.streamlit/secrets.toml.example` como referencia
- password real configurada en Streamlit Cloud secrets
- datos de ejemplo ya incluidos en `results/`
- workflows en `.github/workflows/` para refrescar resultados automaticamente

## Despliegue en Streamlit Community Cloud

1. Ir a `https://share.streamlit.io/`
2. Pulsar `Create app`
3. Seleccionar el repo `manuelcarmonadlc/stock_screener`
4. Elegir la rama `main`
5. Indicar `dashboard.py` como entrypoint
6. En `Advanced settings`, configurar secrets:

```toml
[auth]
password = "TU_PASSWORD_REAL"

[general]
timezone = "Europe/Madrid"
```

7. Seleccionar la version de Python
8. Desplegar la app

## Configuracion recomendada

- Python recomendado: `3.13` si aparece disponible en el selector
- Si no aparece, usar la version soportada mas alta compatible y revisar logs

## Notas operativas

- Community Cloud copia el repo y ejecuta la app desde la raiz del repositorio.
- La configuracion personalizada de Streamlit debe estar en `.streamlit/config.toml` en la raiz.
- La app lee el ultimo `results/oportunidades_*.csv` disponible en el repo.
- Si existe `screener.db`, el dashboard usa SQLite como fallback local y enriquece con el ultimo CSV.
- En Streamlit Cloud no aparece boton de escaneo: la actualizacion la hace GitHub Actions.
- Las fichas Markdown se leen desde `results/fichas_YYYYMMDD_HHMM/`.

## Si algo falla al desplegar

Revisar en este orden:
1. logs de Streamlit Cloud
2. version de Python seleccionada en `Advanced settings`
3. instalacion de dependencias desde `requirements.txt` o `requirements_streamlit.txt`
4. permisos del repositorio en Streamlit Cloud
5. secrets configurados correctamente
6. rutas relativas desde la raiz del repo
