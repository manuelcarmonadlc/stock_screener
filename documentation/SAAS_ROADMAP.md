# SaaS Roadmap

## Migracion a SaaS - Cuando llegue el momento

Lo importante ahora es que la logica de negocio quede solida:
- pipeline de 5 capas
- reglas duras
- scoring
- clasificacion final

Ese bloque es el activo principal y se reutiliza casi integro en una arquitectura SaaS.

## 1. Backend

Reemplazar `screener.py` por FastAPI + Celery workers.

- Cada capa del pipeline se convierte en endpoint o task.
- `screener.py` se reutiliza como libreria importable.
- Las tareas de escaneo dejan de depender de ejecucion CLI manual.

## 2. Base de datos

Migrar SQLite a PostgreSQL.

- `database.py` ya abstrae las operaciones principales.
- El cambio natural es sustituir `sqlite3` por `psycopg2` o SQLAlchemy.
- En la fase LLM, `pgvector` permitiria soporte para embeddings en la capa causal.

## 3. Frontend

Reemplazar Streamlit por React + Next.js.

- La spec v3 ya define vistas y endpoints esperables.
- Streamlit puede quedarse como panel interno o entorno de analisis.
- El frontend publico tendria mejor control de UX, auth y escalabilidad.

## 4. Auth

Reemplazar password simple por OAuth/JWT.

- Roles previstos: Viewer, Analyst, Admin.
- La spec v3 ya contempla esta necesidad en la seccion 16.
- Streamlit secrets son suficientes para esta fase, no para SaaS multiusuario.

## 5. Infraestructura

Evolucionar desde ejecucion simple a contenedores y orquestacion.

- Docker Compose como primer paso.
- Despues, Kubernetes si el volumen o el numero de servicios lo exige.
- Servicios probables: API, workers, scheduler, frontend, base de datos.

## 6. Monetizacion

Posibles tiers cuando el producto madure:

- Free: dashboard read-only con datos retrasados.
- Pro: alertas, fichas completas, mas frecuencia y mejor seguimiento.
- Enterprise: API access, universos personalizados, integraciones.

## Decision actual

La capa causal con LLM sigue aplazada.

- Motivo: coste por llamada y necesidad de calibracion.
- La heuristica actual cubre una parte grande del valor del pipeline.
- Tiene sentido retomarla cuando las capas cuantitativa, recovery, tecnica y operativa esten mas validadas.
