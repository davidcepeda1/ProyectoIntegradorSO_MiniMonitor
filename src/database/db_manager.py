"""Gestión de la base de datos SQLite del Mini Monitor de Recursos."""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

REINTENTOS_ESCRITURA = 3
ESPERA_BASE_SEG = 0.1

DB_PATH = Path(__file__).resolve().parent.parent.parent / "monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS capturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    cpu_uso REAL,
    ram_total INTEGER,
    ram_usada INTEGER,
    disco_total INTEGER,
    disco_usada INTEGER,
    red_trafico_in INTEGER,
    red_trafico_out INTEGER,
    procesos_json TEXT NOT NULL DEFAULT '[]',
    usuarios_json TEXT NOT NULL DEFAULT '[]',
    etiquetas TEXT NOT NULL
);
"""

# Columnas agregadas despues de la version inicial del esquema. Se aplican
# con ALTER TABLE para que una base de datos ya existente (creada antes de
# que se guardaran Procesos/Usuarios) se actualice sola sin perder datos.
COLUMNAS_MIGRACION = {
    "procesos_json": "TEXT NOT NULL DEFAULT '[]'",
    "usuarios_json": "TEXT NOT NULL DEFAULT '[]'",
}


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    # timeout: cuanto tiempo espera SQLite a nivel interno por un lock antes
    # de lanzar "database is locked". 5s es generoso para este proyecto
    # (escrituras cortas, un solo archivo local) sin congelar la UI.
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _con_reintento(operacion):
    """Ejecuta `operacion` (una función sin argumentos) reintentando con
    backoff progresivo si SQLite reporta "database is locked".

    `sqlite3.connect(timeout=5.0)` ya reintenta internamente durante ese
    lapso, pero si el lock sigue activo justo al expirar ese margen, esta
    capa adicional evita que una escritura concurrente (ej. el hilo
    principal guardando una captura justo cuando otra operación toca el
    archivo) tumbe la aplicación con una excepción no controlada.
    """
    ultimo_error = None
    for intento in range(REINTENTOS_ESCRITURA):
        try:
            return operacion()
        except sqlite3.OperationalError as error:
            if "locked" not in str(error).lower():
                raise
            ultimo_error = error
            time.sleep(ESPERA_BASE_SEG * (2 ** intento))
    raise RuntimeError(
        f"No se pudo escribir en la base de datos tras {REINTENTOS_ESCRITURA} intentos "
        f"(base de datos bloqueada): {ultimo_error}"
    )


def init_db(db_path: Path = DB_PATH) -> None:
    def operacion():
        with get_connection(db_path) as conn:
            conn.execute(SCHEMA)
            for columna, definicion in COLUMNAS_MIGRACION.items():
                try:
                    conn.execute(f"ALTER TABLE capturas ADD COLUMN {columna} {definicion}")
                except sqlite3.OperationalError as error:
                    if "duplicate column" not in str(error).lower():
                        raise  # solo se ignora el caso esperado: la columna ya existe

    _con_reintento(operacion)


def _etiquetas_a_texto(etiquetas: list[str] | None) -> str:
    if not etiquetas:
        return "GENERAL"
    return ", ".join(etiquetas)


def crear_captura(
    cpu_uso: float,
    ram_total: int,
    ram_usada: int,
    disco_total: int,
    disco_usada: int,
    red_trafico_in: int,
    red_trafico_out: int,
    procesos: list[dict] | None = None,
    usuarios: list[dict] | None = None,
    etiquetas: list[str] | None = None,
    db_path: Path = DB_PATH,
) -> int:
    fecha_hora = datetime.now().isoformat(timespec="seconds")
    etiquetas_texto = _etiquetas_a_texto(etiquetas)
    procesos_texto = json.dumps(procesos or [])
    usuarios_texto = json.dumps(usuarios or [])

    def operacion():
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO capturas (
                    fecha_hora, cpu_uso, ram_total, ram_usada,
                    disco_total, disco_usada, red_trafico_in, red_trafico_out,
                    procesos_json, usuarios_json, etiquetas
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fecha_hora,
                    cpu_uso,
                    ram_total,
                    ram_usada,
                    disco_total,
                    disco_usada,
                    red_trafico_in,
                    red_trafico_out,
                    procesos_texto,
                    usuarios_texto,
                    etiquetas_texto,
                ),
            )
            return cursor.lastrowid

    return _con_reintento(operacion)


def listar_capturas(etiqueta: str | None = None, db_path: Path = DB_PATH) -> list[dict]:
    """Consulta capturas almacenadas, opcionalmente filtradas por etiqueta (LIKE)."""
    consulta = "SELECT * FROM capturas"
    parametros: tuple = ()

    if etiqueta:
        consulta += " WHERE etiquetas LIKE ?"
        parametros = (f"%{etiqueta}%",)

    consulta += " ORDER BY fecha_hora DESC"

    with get_connection(db_path) as conn:
        filas = conn.execute(consulta, parametros).fetchall()
        return [dict(fila) for fila in filas]


def actualizar_etiquetas(captura_id: int, etiquetas: list[str], db_path: Path = DB_PATH) -> bool:
    """Modifica exclusivamente las etiquetas de una captura existente."""
    etiquetas_texto = _etiquetas_a_texto(etiquetas)

    def operacion():
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "UPDATE capturas SET etiquetas = ? WHERE id = ?",
                (etiquetas_texto, captura_id),
            )
            return cursor.rowcount > 0

    return _con_reintento(operacion)


def eliminar_captura(captura_id: int, db_path: Path = DB_PATH) -> bool:
    """Elimina una captura por su id."""
    def operacion():
        with get_connection(db_path) as conn:
            cursor = conn.execute("DELETE FROM capturas WHERE id = ?", (captura_id,))
            return cursor.rowcount > 0

    return _con_reintento(operacion)


if __name__ == "__main__":
    init_db()
    print(f"Base de datos inicializada en: {DB_PATH}")
