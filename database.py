"""
Persistencia SQLite para el historial de evaluaciones del screener.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).resolve().parent / "screener.db"
WATCHLIST_STATES = {
    "activa",
    "pendiente",
    "pausada",
    "descartada",
    "operada",
}
CLASSIFICATION_ORDER = {
    "descarte": 0,
    "seguimiento": 1,
    "pendiente_confirmacion": 2,
    "entrada_escalada": 3,
    "entrada_directa": 4,
}
RECOVERY_ORDER = {
    "ausente": 0,
    "parcial": 1,
    "confirmada": 2,
    "pendiente": 3,
}
STATE_PRIORITY_DEFAULTS = {
    "activa": "media",
    "pendiente": "media",
    "pausada": "baja",
    "descartada": "baja",
    "operada": "media",
}
CLASSIFICATION_TO_WATCHLIST = {
    "entrada_directa": ("activa", "alta"),
    "entrada_escalada": ("activa", "media"),
    "pendiente_confirmacion": ("pendiente", "media"),
    "seguimiento": ("activa", "baja"),
    "descarte": ("descartada", "baja"),
}


def _get_connection() -> sqlite3.Connection:
    """Abre una conexion SQLite con row_factory tipo diccionario."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _now_iso() -> str:
    """Devuelve timestamp ISO con zona horaria."""
    return datetime.now().astimezone().isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    """Convierte texto ISO a datetime de forma defensiva."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _to_python_scalar(value: Any) -> Any:
    """Convierte valores numpy/pandas a escalares compatibles con SQLite."""
    if value is None:
        return None

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return item_method()
        except Exception:
            pass

    return value


def _json_dumps(payload: Any) -> str:
    """Serializa listas/dicts a JSON robusto para persistencia."""
    return json.dumps(payload, ensure_ascii=False, default=str)


def _deserialize_json_field(value: str | None) -> Any:
    """Deserializa un campo JSON si contiene datos."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Convierte una fila SQLite a dict con campos JSON ya decodificados."""
    if row is None:
        return None

    item = dict(row)
    if "hard_rules_json" in item:
        item["hard_rules_json"] = _deserialize_json_field(item.get("hard_rules_json"))
    if "signals_json" in item:
        item["signals_json"] = _deserialize_json_field(item.get("signals_json"))
    return item


def _build_alert_payload(
    ticker: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    triggered_at: str,
    is_read: bool = False,
) -> dict:
    """Construye una alerta homogénea."""
    return {
        "ticker": ticker,
        "alert_type": alert_type,
        "severity": severity,
        "title": title,
        "message": message,
        "triggered_at": triggered_at,
        "is_read": bool(is_read),
    }


def _validate_watchlist_state(state: str) -> str:
    """Valida un estado de watchlist permitido."""
    normalized = (state or "").strip().lower()
    if normalized not in WATCHLIST_STATES:
        allowed = ", ".join(sorted(WATCHLIST_STATES))
        raise ValueError(f"Estado de watchlist no valido: {state}. Usa: {allowed}")
    return normalized


def _record_transition(
    connection: sqlite3.Connection,
    ticker: str,
    previous_state: str | None,
    new_state: str,
    previous_classification: str | None,
    new_classification: str | None,
    priority: str,
    reason: str,
    manual_override: bool,
    changed_at: str,
) -> None:
    """Registra un cambio de estado o clasificacion en el historial de watchlist."""
    connection.execute(
        """
        INSERT INTO watchlist_transitions (
            ticker,
            previous_state,
            new_state,
            previous_classification,
            new_classification,
            priority,
            reason,
            changed_at,
            manual_override
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            previous_state,
            new_state,
            previous_classification,
            new_classification,
            priority,
            reason,
            changed_at,
            int(manual_override),
        ),
    )


def _upsert_watchlist_state(
    connection: sqlite3.Connection,
    ticker: str,
    state: str,
    priority: str,
    reason: str,
    last_changed_at: str,
    manual_override: bool,
) -> None:
    """Inserta o actualiza el estado actual de la watchlist."""
    connection.execute(
        """
        INSERT INTO watchlist_states (
            ticker,
            state,
            priority,
            reason,
            last_changed_at,
            manual_override
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            state = excluded.state,
            priority = excluded.priority,
            reason = excluded.reason,
            last_changed_at = excluded.last_changed_at,
            manual_override = excluded.manual_override
        """,
        (
            ticker,
            state,
            priority,
            reason,
            last_changed_at,
            int(manual_override),
        ),
    )


def _derive_watchlist_target(
    previous_classification: str | None,
    current_classification: str | None,
) -> tuple[str, str, str]:
    """Calcula el estado y prioridad deseados para la watchlist."""
    normalized_classification = (current_classification or "descarte").strip()

    if previous_classification == "seguimiento" and normalized_classification == "entrada_directa":
        return (
            "activa",
            "alta",
            "Transicion automatica: seguimiento -> entrada_directa",
        )

    if previous_classification == "entrada_directa" and normalized_classification == "descarte":
        return (
            "descartada",
            "baja",
            "Transicion automatica: entrada_directa -> descarte",
        )

    state, priority = CLASSIFICATION_TO_WATCHLIST.get(
        normalized_classification,
        ("descartada", "baja"),
    )
    return state, priority, f"Evaluacion actual: {normalized_classification}"


def init_db() -> None:
    """Crea la base de datos y la tabla principal si no existen."""
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                evaluation_date TEXT NOT NULL,
                final_classification TEXT,
                total_score REAL,
                fundamental_score REAL,
                valuation_score REAL,
                recovery_score REAL,
                technical_score REAL,
                entry_zone_min REAL,
                entry_zone_max REAL,
                exit_zone_min REAL,
                exit_zone_max REAL,
                hard_rules_json TEXT,
                signals_json TEXT,
                rules_version TEXT,
                config_version TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_evaluations_ticker_date
            ON evaluations (ticker, evaluation_date DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist_states (
                ticker TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                priority TEXT,
                reason TEXT,
                last_changed_at TEXT NOT NULL,
                manual_override INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                previous_state TEXT,
                new_state TEXT NOT NULL,
                previous_classification TEXT,
                new_classification TEXT,
                priority TEXT,
                reason TEXT,
                changed_at TEXT NOT NULL,
                manual_override INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_watchlist_transitions_ticker_date
            ON watchlist_transitions (ticker, changed_at DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                triggered_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_alerts_ticker_type_date
            ON alerts (ticker, alert_type, triggered_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_alerts_read_date
            ON alerts (is_read, triggered_at DESC)
            """
        )
        connection.commit()


def save_evaluation(result: dict) -> None:
    """Guarda una evaluacion individual en SQLite."""
    composite = result.get("composite", {})
    layer_1 = result.get("layer_1_quantitative", {})
    layer_3 = result.get("layer_3_recovery", {})
    layer_4 = result.get("layer_4_technical", {})
    layer_5 = result.get("layer_5_operational_plan", {})

    signals_payload = {
        "quantitative_flags": layer_1.get("flags", []),
        "recovery_signals": layer_3.get("signals", []),
        "technical_signals": layer_4.get("signals", []),
        "recovery_status": layer_3.get("recovery_status"),
        "technical_status": layer_4.get("status"),
        "price": _to_python_scalar(result.get("price")),
        "support_level": _to_python_scalar(layer_4.get("metrics", {}).get("support_level")),
        "quarterly_debt_change_pct": _to_python_scalar(
            layer_1.get("fundamental", {}).get("metrics", {}).get("quarterly_debt_change_pct")
        ),
    }

    record = (
        result.get("ticker"),
        result.get("ticker"),
        result.get("evaluation_timestamp"),
        composite.get("final_classification"),
        _to_python_scalar(composite.get("total_score")),
        _to_python_scalar(composite.get("fundamental_score")),
        _to_python_scalar(composite.get("valuation_score")),
        _to_python_scalar(composite.get("recovery_score")),
        _to_python_scalar(composite.get("technical_score")),
        _to_python_scalar(layer_5.get("entry_zone_min")),
        _to_python_scalar(layer_5.get("entry_zone_max")),
        _to_python_scalar(layer_5.get("exit_zone_min")),
        _to_python_scalar(layer_5.get("exit_zone_max")),
        _json_dumps(composite.get("hard_rules_applied", [])),
        _json_dumps(signals_payload),
        result.get("rules_version"),
        result.get("config_version"),
    )

    with _get_connection() as connection:
        connection.execute(
            """
            INSERT INTO evaluations (
                company_id,
                ticker,
                evaluation_date,
                final_classification,
                total_score,
                fundamental_score,
                valuation_score,
                recovery_score,
                technical_score,
                entry_zone_min,
                entry_zone_max,
                exit_zone_min,
                exit_zone_max,
                hard_rules_json,
                signals_json,
                rules_version,
                config_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record,
        )
        connection.commit()


def get_history(ticker: str) -> list[dict]:
    """Devuelve el historial completo de evaluaciones de un ticker."""
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM evaluations
            WHERE ticker = ?
            ORDER BY evaluation_date DESC
            """,
            (ticker,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_previous_evaluation(ticker: str) -> dict | None:
    """Devuelve la ultima evaluacion registrada de un ticker."""
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM evaluations
            WHERE ticker = ?
            ORDER BY evaluation_date DESC
            LIMIT 1
            """,
            (ticker,),
        ).fetchone()
    return _row_to_dict(row)


def get_watchlist_state(ticker: str) -> dict | None:
    """Devuelve el estado actual de watchlist para un ticker."""
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM watchlist_states
            WHERE ticker = ?
            """,
            (ticker,),
        ).fetchone()
    return _row_to_dict(row)


def sync_watchlist_state(
    result: dict,
    previous_evaluation: dict | None = None,
) -> dict | None:
    """Sincroniza el estado de watchlist a partir de la nueva evaluacion."""
    ticker = result.get("ticker")
    composite = result.get("composite", {})
    current_classification = composite.get("final_classification")
    if not ticker or not current_classification:
        return None

    current_state = get_watchlist_state(ticker)
    if current_state and current_state.get("manual_override"):
        return None

    previous_classification = None
    if previous_evaluation:
        previous_classification = previous_evaluation.get("final_classification")

    target_state, target_priority, target_reason = _derive_watchlist_target(
        previous_classification,
        current_classification,
    )
    changed_at = result.get("evaluation_timestamp") or _now_iso()

    previous_state = current_state.get("state") if current_state else None
    previous_priority = current_state.get("priority") if current_state else None
    previous_reason = current_state.get("reason") if current_state else None

    state_changed = (
        current_state is None
        or previous_state != target_state
        or previous_priority != target_priority
        or previous_reason != target_reason
        or previous_classification != current_classification
    )
    if not state_changed:
        return None

    with _get_connection() as connection:
        _upsert_watchlist_state(
            connection,
            ticker=ticker,
            state=target_state,
            priority=target_priority,
            reason=target_reason,
            last_changed_at=changed_at,
            manual_override=False,
        )
        _record_transition(
            connection,
            ticker=ticker,
            previous_state=previous_state,
            new_state=target_state,
            previous_classification=previous_classification,
            new_classification=current_classification,
            priority=target_priority,
            reason=target_reason,
            manual_override=False,
            changed_at=changed_at,
        )
        connection.commit()

    return {
        "ticker": ticker,
        "state": target_state,
        "priority": target_priority,
        "reason": target_reason,
        "manual_override": False,
        "last_changed_at": changed_at,
        "previous_state": previous_state,
        "previous_classification": previous_classification,
        "new_classification": current_classification,
    }


def set_watchlist_override(ticker: str, state: str, reason: str) -> dict:
    """Aplica un override manual persistente sobre la watchlist."""
    normalized_ticker = (ticker or "").strip().upper()
    if not normalized_ticker:
        raise ValueError("Ticker vacio para override de watchlist")

    normalized_state = _validate_watchlist_state(state)
    changed_at = _now_iso()
    priority = STATE_PRIORITY_DEFAULTS.get(normalized_state, "media")
    final_reason = (reason or "").strip() or "Override manual"

    current_state = get_watchlist_state(normalized_ticker)
    previous_state = current_state.get("state") if current_state else None
    previous_evaluation = get_previous_evaluation(normalized_ticker)
    previous_classification = None
    if previous_evaluation:
        previous_classification = previous_evaluation.get("final_classification")

    with _get_connection() as connection:
        _upsert_watchlist_state(
            connection,
            ticker=normalized_ticker,
            state=normalized_state,
            priority=priority,
            reason=final_reason,
            last_changed_at=changed_at,
            manual_override=True,
        )
        _record_transition(
            connection,
            ticker=normalized_ticker,
            previous_state=previous_state,
            new_state=normalized_state,
            previous_classification=previous_classification,
            new_classification=previous_classification,
            priority=priority,
            reason=final_reason,
            manual_override=True,
            changed_at=changed_at,
        )
        connection.commit()

    return {
        "ticker": normalized_ticker,
        "state": normalized_state,
        "priority": priority,
        "reason": final_reason,
        "manual_override": True,
        "last_changed_at": changed_at,
        "previous_state": previous_state,
        "previous_classification": previous_classification,
        "new_classification": previous_classification,
    }


def get_watchlist() -> list[dict]:
    """Devuelve la watchlist actual con la ultima evaluacion disponible."""
    with _get_connection() as connection:
        rows = connection.execute(
            """
            WITH latest_evaluations AS (
                SELECT e.*
                FROM evaluations e
                INNER JOIN (
                    SELECT ticker, MAX(evaluation_date) AS latest_date
                    FROM evaluations
                    GROUP BY ticker
                ) latest
                    ON latest.ticker = e.ticker
                   AND latest.latest_date = e.evaluation_date
            )
            SELECT
                w.ticker,
                w.state,
                w.priority,
                w.reason,
                w.last_changed_at,
                w.manual_override,
                le.final_classification,
                le.total_score,
                le.evaluation_date
            FROM watchlist_states w
            LEFT JOIN latest_evaluations le
                ON le.ticker = w.ticker
            ORDER BY
                CASE w.state
                    WHEN 'activa' THEN 1
                    WHEN 'pendiente' THEN 2
                    WHEN 'pausada' THEN 3
                    WHEN 'operada' THEN 4
                    WHEN 'descartada' THEN 5
                    ELSE 6
                END,
                CASE w.priority
                    WHEN 'alta' THEN 1
                    WHEN 'media' THEN 2
                    WHEN 'baja' THEN 3
                    ELSE 4
                END,
                w.ticker
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _has_recent_duplicate_alert(
    connection: sqlite3.Connection,
    ticker: str,
    alert_type: str,
    triggered_at: str,
    window_hours: int = 48,
) -> bool:
    """Evita duplicados del mismo tipo de alerta en la ventana de anti-spam."""
    current_dt = _parse_iso(triggered_at)
    if current_dt is None:
        current_dt = datetime.now().astimezone()

    rows = connection.execute(
        """
        SELECT triggered_at
        FROM alerts
        WHERE ticker = ? AND alert_type = ?
        ORDER BY triggered_at DESC
        """,
        (ticker, alert_type),
    ).fetchall()

    for row in rows:
        alert_dt = _parse_iso(row["triggered_at"])
        if alert_dt is None:
            continue
        delta_hours = abs((current_dt - alert_dt).total_seconds()) / 3600
        if delta_hours <= window_hours:
            return True
        if alert_dt < current_dt:
            break

    return False


def save_alert(alert: dict) -> dict | None:
    """Guarda una alerta si no existe duplicada en la ventana de anti-spam."""
    payload = _build_alert_payload(
        ticker=(alert.get("ticker") or "").strip().upper(),
        alert_type=alert.get("alert_type", "generic"),
        severity=alert.get("severity", "media"),
        title=alert.get("title", ""),
        message=alert.get("message", ""),
        triggered_at=alert.get("triggered_at") or _now_iso(),
        is_read=bool(alert.get("is_read", False)),
    )
    if not payload["ticker"] or not payload["title"] or not payload["message"]:
        return None

    with _get_connection() as connection:
        if _has_recent_duplicate_alert(
            connection,
            payload["ticker"],
            payload["alert_type"],
            payload["triggered_at"],
        ):
            return None

        cursor = connection.execute(
            """
            INSERT INTO alerts (
                ticker,
                alert_type,
                severity,
                title,
                message,
                triggered_at,
                is_read
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["ticker"],
                payload["alert_type"],
                payload["severity"],
                payload["title"],
                payload["message"],
                payload["triggered_at"],
                int(payload["is_read"]),
            ),
        )
        connection.commit()

    payload["id"] = cursor.lastrowid
    return payload


def get_alerts(unread_only: bool = False, limit: int | None = None) -> list[dict]:
    """Devuelve alertas persistidas, opcionalmente solo no leidas."""
    query = """
        SELECT *
        FROM alerts
    """
    params: list[Any] = []
    if unread_only:
        query += " WHERE is_read = 0"
    query += " ORDER BY triggered_at DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with _get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_alerts_as_read(alert_ids: list[int]) -> None:
    """Marca alertas como leidas."""
    valid_ids = [int(alert_id) for alert_id in alert_ids if alert_id is not None]
    if not valid_ids:
        return

    placeholders = ", ".join("?" for _ in valid_ids)
    with _get_connection() as connection:
        connection.execute(
            f"UPDATE alerts SET is_read = 1 WHERE id IN ({placeholders})",
            tuple(valid_ids),
        )
        connection.commit()


def _extract_evaluation_context(
    result: dict | None,
    signals_json: dict | None = None,
) -> dict:
    """Normaliza datos de evaluacion para comparar cambios y generar alertas."""
    if not result:
        return {
            "classification": None,
            "total_score": None,
            "recovery_status": None,
            "recovery_score": None,
            "technical_status": None,
            "technical_signals": [],
            "recovery_signals": [],
            "price": None,
            "support_level": None,
            "quarterly_debt_change_pct": None,
        }

    if "composite" in result:
        layer_3 = result.get("layer_3_recovery", {})
        layer_4 = result.get("layer_4_technical", {})
        fundamental_metrics = result.get("fundamental", {}).get("metrics", {})
        technical_metrics = layer_4.get("metrics", {})
        return {
            "classification": result.get("composite", {}).get("final_classification"),
            "total_score": _to_python_scalar(result.get("composite", {}).get("total_score")),
            "recovery_status": layer_3.get("recovery_status"),
            "recovery_score": _to_python_scalar(layer_3.get("recovery_score")),
            "technical_status": layer_4.get("status"),
            "technical_signals": list(layer_4.get("signals", [])),
            "recovery_signals": list(layer_3.get("signals", [])),
            "price": _to_python_scalar(result.get("price")),
            "support_level": _to_python_scalar(technical_metrics.get("support_level")),
            "quarterly_debt_change_pct": _to_python_scalar(
                fundamental_metrics.get("quarterly_debt_change_pct")
            ),
        }

    signal_payload = signals_json or result.get("signals_json") or {}
    return {
        "classification": result.get("final_classification"),
        "total_score": _to_python_scalar(result.get("total_score")),
        "recovery_status": signal_payload.get("recovery_status"),
        "recovery_score": _to_python_scalar(result.get("recovery_score")),
        "technical_status": signal_payload.get("technical_status"),
        "technical_signals": list(signal_payload.get("technical_signals", [])),
        "recovery_signals": list(signal_payload.get("recovery_signals", [])),
        "price": _to_python_scalar(signal_payload.get("price")),
        "support_level": _to_python_scalar(signal_payload.get("support_level")),
        "quarterly_debt_change_pct": _to_python_scalar(
            signal_payload.get("quarterly_debt_change_pct")
        ),
    }


def generate_alerts_for_evaluation(
    result: dict,
    previous_evaluation: dict | None = None,
) -> list[dict]:
    """Genera alertas relevantes comparando la evaluacion actual con la anterior."""
    ticker = (result.get("ticker") or "").strip().upper()
    if not ticker:
        return []

    triggered_at = result.get("evaluation_timestamp") or _now_iso()
    current = _extract_evaluation_context(result)
    previous = _extract_evaluation_context(previous_evaluation)

    alerts: list[dict] = []
    current_classification = current.get("classification")
    previous_classification = previous.get("classification")
    current_rank = CLASSIFICATION_ORDER.get(current_classification, 0)
    previous_rank = CLASSIFICATION_ORDER.get(previous_classification, 0)

    if previous_evaluation is None and (current.get("total_score") or 0) > 60:
        alerts.append(
            _build_alert_payload(
                ticker,
                "new_opportunity",
                "media",
                f"Nueva oportunidad detectada en {ticker}",
                (
                    f"{ticker} aparece por primera vez con score "
                    f"{current.get('total_score', 0):.1f} y clasificación {current_classification}."
                ),
                triggered_at,
            )
        )

    if previous_classification and current_rank > previous_rank:
        alerts.append(
            _build_alert_payload(
                ticker,
                "classification_upgrade",
                "alta" if current_classification == "entrada_directa" else "media",
                f"Mejora de clasificación en {ticker}",
                (
                    f"{ticker} mejora de {previous_classification} a {current_classification} "
                    f"con score {current.get('total_score', 0):.1f}."
                ),
                triggered_at,
            )
        )
    elif previous_classification and current_rank < previous_rank:
        alerts.append(
            _build_alert_payload(
                ticker,
                "classification_downgrade",
                "alta" if current_classification == "descarte" else "media",
                f"Deterioro de clasificación en {ticker}",
                (
                    f"{ticker} cae de {previous_classification} a {current_classification} "
                    f"con score {current.get('total_score', 0):.1f}."
                ),
                triggered_at,
            )
        )

    current_signals = set(current.get("technical_signals") or [])
    previous_signals = set(previous.get("technical_signals") or [])
    new_technical_signals = sorted(current_signals - previous_signals)
    if previous_evaluation is not None and new_technical_signals:
        signal_preview = ", ".join(new_technical_signals[:3])
        alerts.append(
            _build_alert_payload(
                ticker,
                "technical_confirmation",
                "media",
                f"Confirmación técnica en {ticker}",
                f"Se activan nuevas señales técnicas: {signal_preview}.",
                triggered_at,
            )
        )

    current_support = current.get("support_level")
    current_price = current.get("price")
    previous_support = previous.get("support_level")
    previous_price = previous.get("price")
    active_support = current_support if current_support is not None else previous_support
    support_was_respected = (
        previous_support is not None and previous_price is not None and previous_price >= previous_support
    )
    if (
        previous_evaluation is not None and
        active_support is not None and
        current_price is not None and
        current_price < active_support and
        support_was_respected
    ):
        alerts.append(
            _build_alert_payload(
                ticker,
                "support_lost",
                "alta",
                f"Soporte perdido en {ticker}",
                f"El precio actual {current_price:.2f} cae por debajo del soporte {active_support:.2f}.",
                triggered_at,
            )
        )

    current_recovery_rank = RECOVERY_ORDER.get(current.get("recovery_status"), 0)
    previous_recovery_rank = RECOVERY_ORDER.get(previous.get("recovery_status"), 0)
    current_recovery_score = current.get("recovery_score") or 0
    previous_recovery_score = previous.get("recovery_score") or 0
    if (
        previous_evaluation is not None and (
            current_recovery_rank > previous_recovery_rank or
            current_recovery_score >= previous_recovery_score + 3
        )
    ):
        alerts.append(
            _build_alert_payload(
                ticker,
                "recovery_improved",
                "media",
                f"Recuperación mejorando en {ticker}",
                (
                    f"La recuperación pasa de {previous.get('recovery_status')} a "
                    f"{current.get('recovery_status')} con score {current_recovery_score:.1f}."
                ),
                triggered_at,
            )
        )

    current_debt_change = current.get("quarterly_debt_change_pct")
    previous_debt_change = previous.get("quarterly_debt_change_pct")
    if previous_evaluation is not None and current_debt_change is not None and current_debt_change > 10:
        if previous_debt_change is not None and previous_debt_change <= 10:
            alerts.append(
                _build_alert_payload(
                    ticker,
                    "debt_warning",
                    "alta",
                    f"Alerta de deuda en {ticker}",
                    (
                        f"La deuda trimestral sube {current_debt_change:.1f}% y supera "
                        "el umbral del 10%."
                    ),
                    triggered_at,
                )
            )

    persisted_alerts: list[dict] = []
    for alert in alerts:
        saved = save_alert(alert)
        if saved:
            persisted_alerts.append(saved)

    return persisted_alerts
