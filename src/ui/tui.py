"""Interfaz interactiva de terminal (TUI) del Mini Monitor de Recursos.

Usa `curses` (librería estándar, sin dependencias externas) para un panel
estilo htop con CPU, RAM, Disco y Red, más un menú inferior para las
operaciones CRUD sobre el historial de capturas.

El hilo principal es el único que controla la pantalla (curses no es
thread-safe); los Hilos A/B, definidos en src/main.py, solo actualizan el
estado compartido en segundo plano y nunca tocan la terminal.
"""

import curses

from src.core import cmd_runner
from src.database import db_manager
from src.main import EstadoMonitor, evento_salida, realizar_captura

REFRESCO_MS = 1000

COLOR_OK = 1
COLOR_ALERTA = 2
COLOR_TITULO = 3


def _configurar_colores() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_OK, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_ALERTA, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_TITULO, curses.COLOR_CYAN, -1)


def _dibujar_panel(stdscr, estado: EstadoMonitor) -> None:
    stdscr.erase()
    alto, ancho = stdscr.getmaxyx()
    cpu, memoria = estado.snapshot_metricas()

    stdscr.addstr(0, 0, " MINI MONITOR DE RECURSOS ".center(ancho, "="),
                  curses.color_pair(COLOR_TITULO) | curses.A_BOLD)

    uso_cpu = cpu.get("uso_porcentaje", 0.0)
    color_cpu = COLOR_ALERTA if uso_cpu > 80 else COLOR_OK
    stdscr.addstr(2, 2, "CPU", curses.A_BOLD)
    stdscr.addstr(3, 4, f"Nucleos: {cpu.get('nucleos', '?')}    "
                        f"Frecuencia: {cpu.get('frecuencia_mhz', '?')} MHz")
    stdscr.addstr(4, 4, f"Uso: {uso_cpu}%", curses.color_pair(color_cpu))
    stdscr.addstr(5, 4, f"Carga (1/5/15 min): {cpu.get('carga_1min', '?')} / "
                        f"{cpu.get('carga_5min', '?')} / {cpu.get('carga_15min', '?')}")

    ram_total = memoria.get("ram_total_kb", 0)
    ram_usada = memoria.get("ram_usada_kb", 0)
    porcentaje_ram = (ram_usada / ram_total * 100) if ram_total else 0.0
    color_ram = COLOR_ALERTA if porcentaje_ram > 85 else COLOR_OK
    stdscr.addstr(7, 2, "MEMORIA", curses.A_BOLD)
    stdscr.addstr(8, 4, f"Total: {ram_total} KB   Usada: {ram_usada} KB "
                        f"({porcentaje_ram:.1f}%)", curses.color_pair(color_ram))
    stdscr.addstr(9, 4, f"Libre: {memoria.get('ram_libre_kb', '?')} KB   "
                        f"Swap usada: {memoria.get('swap_usada_kb', '?')} KB")

    stdscr.addstr(11, 2, "DISCO (/)", curses.A_BOLD)
    try:
        disco = cmd_runner.obtener_disco_principal()
        stdscr.addstr(12, 4, f"Total: {disco['total_kb']} KB   "
                             f"Usado: {disco['usado_kb']} KB ({disco['porcentaje']})")
    except RuntimeError as error:
        stdscr.addstr(12, 4, f"Error: {error}"[:ancho - 6])

    alerta_red = estado.hay_alerta_red()
    color_red = COLOR_ALERTA if alerta_red else COLOR_OK
    estado_red = "PICO DETECTADO" if alerta_red else "estable"
    stdscr.addstr(14, 2, "RED", curses.A_BOLD)
    stdscr.addstr(15, 4, f"Estado: {estado_red}", curses.color_pair(color_red))

    menu = "[C] Crear  [V] Historial  [E] Editar etiquetas  [D] Eliminar  [Q] Salir"
    stdscr.addstr(alto - 1, 0, menu.center(ancho, " ")[:ancho - 1], curses.A_REVERSE)

    stdscr.noutrefresh()
    curses.doupdate()


def _leer_texto(stdscr, prompt: str) -> str:
    alto, ancho = stdscr.getmaxyx()
    stdscr.addstr(alto - 2, 0, " " * (ancho - 1))
    stdscr.addstr(alto - 2, 0, prompt)
    stdscr.refresh()

    # stdscr queda en modo no-bloqueante con timeout de REFRESCO_MS por el
    # bucle principal; sin desactivarlo aqui, getstr() hereda ese timeout y
    # corta la entrada si el usuario tarda mas de un segundo en escribir.
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    curses.echo()
    curses.curs_set(1)
    try:
        texto = stdscr.getstr(alto - 2, len(prompt) + 1, 60).decode("utf-8", errors="ignore").strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(REFRESCO_MS)
    return texto


def _mostrar_mensaje(stdscr, mensaje: str) -> None:
    alto, ancho = stdscr.getmaxyx()
    stdscr.addstr(alto - 2, 0, " " * (ancho - 1))
    stdscr.addstr(alto - 2, 0, mensaje[:ancho - 1])
    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.timeout(1500)
    stdscr.getch()
    stdscr.nodelay(True)
    stdscr.timeout(REFRESCO_MS)


def _parsear_etiquetas(texto: str) -> list[str] | None:
    etiquetas = [etiqueta.strip() for etiqueta in texto.split(",") if etiqueta.strip()]
    return etiquetas or None


def _crear_captura(stdscr, estado: EstadoMonitor) -> None:
    texto = _leer_texto(stdscr, "Etiquetas separadas por coma (Enter = GENERAL): ")
    try:
        captura_id = realizar_captura(estado, etiquetas=_parsear_etiquetas(texto))
        _mostrar_mensaje(stdscr, f"Captura #{captura_id} guardada correctamente.")
    except RuntimeError as error:
        _mostrar_mensaje(stdscr, f"Error al capturar: {error}")


def _dibujar_tabla_historial(stdscr, capturas: list[dict]) -> None:
    stdscr.erase()
    alto, ancho = stdscr.getmaxyx()
    stdscr.addstr(0, 0, " HISTORIAL DE CAPTURAS ".center(ancho, "="), curses.A_BOLD)

    if not capturas:
        stdscr.addstr(2, 2, "No hay capturas registradas.")
    else:
        encabezado = f"{'ID':<5}{'Fecha':<21}{'CPU%':<8}{'RAM(KB)':<12}{'Etiquetas':<30}"
        stdscr.addstr(2, 2, encabezado[:ancho - 3], curses.A_UNDERLINE)
        for fila, captura in enumerate(capturas[:alto - 6], start=3):
            linea = (f"{captura['id']:<5}{captura['fecha_hora']:<21}"
                     f"{captura['cpu_uso']:<8}{captura['ram_usada']:<12}{captura['etiquetas']:<30}")
            stdscr.addstr(fila, 2, linea[:ancho - 3])

    stdscr.refresh()


def _mostrar_detalle_captura(stdscr, captura: dict) -> None:
    stdscr.erase()
    alto, ancho = stdscr.getmaxyx()
    stdscr.addstr(0, 0, f" DETALLE DE CAPTURA #{captura['id']} (cualquier tecla para volver) "
                  .center(ancho, "="), curses.A_BOLD)

    campos = [
        ("Fecha/Hora", captura["fecha_hora"]),
        ("CPU uso", f"{captura['cpu_uso']}%"),
        ("RAM total", f"{captura['ram_total']} KB"),
        ("RAM usada", f"{captura['ram_usada']} KB"),
        ("Disco total", f"{captura['disco_total']} KB"),
        ("Disco usada", f"{captura['disco_usada']} KB"),
        ("Red entrada", f"{captura['red_trafico_in']} bytes"),
        ("Red salida", f"{captura['red_trafico_out']} bytes"),
        ("Etiquetas", captura["etiquetas"]),
    ]
    for fila, (etiqueta, valor) in enumerate(campos, start=2):
        stdscr.addstr(fila, 2, f"{etiqueta:<14}: {valor}"[:ancho - 3])

    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.getch()
    stdscr.nodelay(True)
    stdscr.timeout(REFRESCO_MS)


def _ver_historial(stdscr) -> None:
    etiqueta = _leer_texto(stdscr, "Filtrar por etiqueta (Enter = ver todo): ")
    filtro = etiqueta or None

    while True:
        capturas = db_manager.listar_capturas(filtro)
        _dibujar_tabla_historial(stdscr, capturas)

        if not capturas:
            stdscr.nodelay(False)
            stdscr.timeout(-1)
            stdscr.getch()
            stdscr.nodelay(True)
            stdscr.timeout(REFRESCO_MS)
            return

        id_texto = _leer_texto(stdscr, "ID para ver detalle (Enter para volver): ")
        if not id_texto:
            return
        if not id_texto.isdigit():
            _mostrar_mensaje(stdscr, "ID invalido.")
            continue

        captura = next((c for c in capturas if c["id"] == int(id_texto)), None)
        if captura is None:
            _mostrar_mensaje(stdscr, "No se encontro esa captura en la lista actual.")
            continue

        _mostrar_detalle_captura(stdscr, captura)


def _editar_etiquetas(stdscr) -> None:
    id_texto = _leer_texto(stdscr, "ID de la captura a editar: ")
    if not id_texto.isdigit():
        _mostrar_mensaje(stdscr, "ID invalido.")
        return

    etiquetas_texto = _leer_texto(stdscr, "Nuevas etiquetas separadas por coma: ")
    exito = db_manager.actualizar_etiquetas(int(id_texto), _parsear_etiquetas(etiquetas_texto))
    _mostrar_mensaje(stdscr, "Etiquetas actualizadas." if exito else "No se encontro esa captura.")


def _eliminar_registro(stdscr) -> None:
    id_texto = _leer_texto(stdscr, "ID de la captura a eliminar: ")
    if not id_texto.isdigit():
        _mostrar_mensaje(stdscr, "ID invalido.")
        return

    exito = db_manager.eliminar_captura(int(id_texto))
    _mostrar_mensaje(stdscr, "Captura eliminada." if exito else "No se encontro esa captura.")


def _bucle_principal(stdscr, estado: EstadoMonitor) -> None:
    curses.curs_set(0)
    _configurar_colores()
    stdscr.nodelay(True)
    stdscr.timeout(REFRESCO_MS)

    while not evento_salida.is_set():
        _dibujar_panel(stdscr, estado)
        tecla = stdscr.getch()

        if tecla in (ord("q"), ord("Q")):
            evento_salida.set()
        elif tecla in (ord("c"), ord("C")):
            _crear_captura(stdscr, estado)
        elif tecla in (ord("v"), ord("V")):
            _ver_historial(stdscr)
        elif tecla in (ord("e"), ord("E")):
            _editar_etiquetas(stdscr)
        elif tecla in (ord("d"), ord("D")):
            _eliminar_registro(stdscr)


def iniciar_tui(estado: EstadoMonitor) -> None:
    """Punto de entrada de la TUI. curses.wrapper garantiza una salida limpia
    de la terminal incluso si ocurre una excepción no controlada."""
    curses.wrapper(_bucle_principal, estado)
