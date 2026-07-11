"""Orquestador del Mini Monitor de Recursos: núcleo concurrente.

- Hilo A: refresca métricas de CPU/RAM en tiempo real cada segundo.
- Hilo B: detecta picos de tráfico de red comparando deltas sucesivos.
- Captura bajo demanda: usa os.fork() + os.pipe() para ejecutar en un
  proceso hijo los comandos "pesados" (ps, df, who) sin bloquear al padre,
  que persiste el resultado combinado en SQLite.

El proceso principal es el único que maneja señales (SIGINT) y el único
que, en la Semana 5, controla la TUI. Nota importante de SO: os.fork()
en un proceso multihilo solo clona el hilo que lo invoca (el principal);
los hilos A y B no existen en el hijo, por lo que este nunca debe tocar
el lock ni el estado compartido — solo ejecuta comandos y escribe al pipe.
"""

import json
import os
import signal
import sys
import threading

from src.core import cmd_runner, proc_parser
from src.database import db_manager

INTERVALO_METRICAS = 1.0
UMBRAL_PICO_RED_BYTES = 5 * 1024 * 1024  # 5 MB entre lecturas consecutivas

evento_salida = threading.Event()


class EstadoMonitor:
    """Estado compartido entre hilos, protegido por un lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.cpu: dict = {}
        self.memoria: dict = {}
        self.alerta_red = False
        self.trafico_anterior: int | None = None

    def actualizar_metricas(self, cpu: dict, memoria: dict) -> None:
        with self._lock:
            self.cpu = cpu
            self.memoria = memoria

    def snapshot_metricas(self) -> tuple[dict, dict]:
        with self._lock:
            return dict(self.cpu), dict(self.memoria)

    def marcar_alerta_red(self, activa: bool) -> None:
        with self._lock:
            self.alerta_red = activa

    def hay_alerta_red(self) -> bool:
        with self._lock:
            return self.alerta_red


def hilo_metricas(estado: EstadoMonitor) -> None:
    """Hilo A: refresca CPU/RAM en tiempo real."""
    while not evento_salida.is_set():
        try:
            cpu = proc_parser.obtener_info_cpu(intervalo=0.1)
            memoria = proc_parser.obtener_info_meminfo()
            estado.actualizar_metricas(cpu, memoria)
        except RuntimeError as error:
            print(f"[Hilo A] Error leyendo métricas: {error}", file=sys.stderr)
        evento_salida.wait(INTERVALO_METRICAS)


def hilo_red(estado: EstadoMonitor) -> None:
    """Hilo B: detecta picos de tráfico de red comparando deltas sucesivos."""
    while not evento_salida.is_set():
        try:
            trafico = cmd_runner.obtener_trafico_total()
            total_actual = trafico["red_trafico_in"] + trafico["red_trafico_out"]

            if estado.trafico_anterior is not None:
                delta = total_actual - estado.trafico_anterior
                estado.marcar_alerta_red(delta > UMBRAL_PICO_RED_BYTES)

            estado.trafico_anterior = total_actual
        except RuntimeError as error:
            print(f"[Hilo B] Error leyendo tráfico de red: {error}", file=sys.stderr)
        evento_salida.wait(INTERVALO_METRICAS)


def _proceso_hijo_captura(fd_escritura: int) -> None:
    """Cuerpo del proceso hijo: ejecuta los comandos pesados y envía el resultado por el pipe.

    Se atrapa `Exception` de forma amplia a propósito: el hijo es un
    callejón sin salida tras el fork, y NUNCA debe dejar una excepción sin
    manejar — si escapara, el intérprete intentaría desenredar la pila de
    llamadas del proceso hijo (que es una copia de la del padre, incluida
    potencialmente la TUI de curses), con resultados impredecibles sobre
    una terminal que en realidad controla el padre. Se informa el error al
    padre por el pipe y se termina siempre con `os._exit()` (nunca con un
    `return` normal), para no arriesgarse a que el hijo continúe
    ejecutando por accidente código pensado solo para el padre.
    """
    codigo_salida = 0
    with os.fdopen(fd_escritura, "w") as pipe_escritura:
        try:
            datos = {
                "disco": cmd_runner.obtener_disco_principal(),
                "procesos": cmd_runner.obtener_procesos(),
                "usuarios": cmd_runner.obtener_usuarios(),
                "trafico": cmd_runner.obtener_trafico_total(),
            }
            pipe_escritura.write(json.dumps(datos))
        except Exception as error:
            pipe_escritura.write(json.dumps({"error": str(error)}))
            codigo_salida = 1
    os._exit(codigo_salida)


def _persistir_captura(estado: EstadoMonitor, datos: dict, etiquetas: list[str] | None) -> int:
    """Combina los datos pesados (disco/procesos/usuarios/trafico) con las
    métricas de CPU/RAM ya calculadas por el Hilo A, y guarda la captura."""
    cpu, memoria = estado.snapshot_metricas()
    disco = datos["disco"]
    trafico = datos["trafico"]

    return db_manager.crear_captura(
        cpu_uso=cpu.get("uso_porcentaje", 0.0),
        ram_total=memoria.get("ram_total_kb", 0),
        ram_usada=memoria.get("ram_usada_kb", 0),
        disco_total=disco.get("total_kb", 0),
        disco_usada=disco.get("usado_kb", 0),
        red_trafico_in=trafico.get("red_trafico_in", 0),
        red_trafico_out=trafico.get("red_trafico_out", 0),
        procesos=datos["procesos"],
        usuarios=datos["usuarios"],
        etiquetas=etiquetas,
    )


def realizar_captura(estado: EstadoMonitor, etiquetas: list[str] | None = None) -> tuple[int, str | None]:
    """Crea una captura completa del estado del sistema (los 6 módulos) y la
    persiste en la BD. Devuelve `(id_captura, advertencia)`.

    El proceso hijo (os.fork()) ejecuta los comandos pesados (df, ps, who) y
    devuelve el resultado al padre mediante os.pipe(); el padre combina ese
    resultado con las métricas de CPU/RAM ya calculadas por el Hilo A y
    guarda la captura completa (CPU, RAM, Disco, Red, Procesos y Usuarios)
    en SQLite.

    Si `os.fork()` falla (ej. se alcanzó el límite de procesos del usuario,
    `RLIMIT_NPROC`, o el sistema se quedó sin PIDs disponibles) se captura
    el `OSError` y se degrada a un modo de respaldo síncrono: los mismos
    comandos se ejecutan directamente en el proceso principal en vez de
    delegarlos a un hijo. `advertencia` es `None` en el caso normal, o un
    mensaje describiendo la degradación para que la TUI lo muestre.
    """
    try:
        fd_lectura, fd_escritura = os.pipe()
        pid_hijo = os.fork()
    except OSError as error:
        advertencia = f"os.fork() falló ({error}); captura realizada de forma síncrona."
        datos = {
            "disco": cmd_runner.obtener_disco_principal(),
            "procesos": cmd_runner.obtener_procesos(),
            "usuarios": cmd_runner.obtener_usuarios(),
            "trafico": cmd_runner.obtener_trafico_total(),
        }
        return _persistir_captura(estado, datos, etiquetas), advertencia

    if pid_hijo == 0:
        os.close(fd_lectura)
        _proceso_hijo_captura(fd_escritura)
        return -1, None  # inalcanzable: el hijo termina en os._exit()

    os.close(fd_escritura)
    with os.fdopen(fd_lectura, "r") as pipe_lectura:
        contenido = pipe_lectura.read()
    os.waitpid(pid_hijo, 0)

    datos_hijo = json.loads(contenido)
    if "error" in datos_hijo:
        raise RuntimeError(f"El proceso hijo de captura falló: {datos_hijo['error']}")

    return _persistir_captura(estado, datos_hijo, etiquetas), None


def _manejar_sigint(signum, frame) -> None:
    # No imprime nada aquí: la terminal está controlada por curses mientras
    # la TUI está activa: escribir directamente la corrompería. Solo se
    # señaliza la salida; el mensaje final se imprime tras cerrar la TUI.
    evento_salida.set()


def main() -> None:
    db_manager.init_db()
    signal.signal(signal.SIGINT, _manejar_sigint)

    estado = EstadoMonitor()
    hilos = [
        threading.Thread(target=hilo_metricas, args=(estado,), daemon=True),
        threading.Thread(target=hilo_red, args=(estado,), daemon=True),
    ]
    for hilo in hilos:
        hilo.start()

    from src.ui.tui import iniciar_tui  # import diferido: evita import circular con src.main

    try:
        iniciar_tui(estado)
    finally:
        evento_salida.set()
        for hilo in hilos:
            hilo.join(timeout=2)

    print("Mini Monitor de Recursos finalizado.")


if __name__ == "__main__":
    main()
