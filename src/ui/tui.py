"""Interfaz interactiva de terminal (TUI) del Mini Monitor de Recursos.

Usa `curses` (librería estándar, sin dependencias externas) para un panel
estilo btop/htop: secciones en cajas con borde, barras de uso para CPU,
RAM, Swap y Disco, listas de Procesos/Usuarios con scroll real (flechas,
RePág/AvPág) y barra de desplazamiento vertical, más un menú inferior para
las operaciones CRUD sobre el historial de capturas.

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


def _escribir(stdscr, fila: int, columna: int, ancho: int, texto: str, atributo=0) -> None:
    # Se permite escribir hasta la ultima columna (ancho - 1): curses solo
    # prohibe escribir en la celda inferior-derecha exacta de la ventana,
    # y esa excepcion puntual se descarta con el try/except.
    try:
        stdscr.addstr(fila, columna, texto[:max(ancho - columna, 0)], atributo)
    except curses.error:
        pass


def _dibujar_caja(stdscr, fila0: int, ancho: int, alto_contenido: int, titulo: str) -> tuple[int, int]:
    """Dibuja una caja con borde y título (estilo btop). Devuelve (fila_contenido, columna_contenido)."""
    alto_caja = alto_contenido + 2
    _escribir(stdscr, fila0, 0, ancho, "┌" + "─" * max(ancho - 2, 0) + "┐")
    for i in range(1, alto_caja - 1):
        _escribir(stdscr, fila0 + i, 0, ancho, "│")
        _escribir(stdscr, fila0 + i, ancho - 1, ancho, "│")
    _escribir(stdscr, fila0 + alto_caja - 1, 0, ancho, "└" + "─" * max(ancho - 2, 0) + "┘")
    _escribir(stdscr, fila0, 2, ancho, f"┤ {titulo} ├", curses.A_BOLD | curses.color_pair(COLOR_TITULO))
    return fila0 + 1, 2


def _dibujar_barra(stdscr, fila: int, columna: int, ancho_barra: int, porcentaje: float,
                    color: int, ancho_total: int) -> None:
    porcentaje = max(0.0, min(porcentaje, 100.0))
    llenos = int(round(ancho_barra * porcentaje / 100))
    barra = "█" * llenos + "░" * (ancho_barra - llenos)
    _escribir(stdscr, fila, columna, ancho_total, barra, curses.color_pair(color))
    _escribir(stdscr, fila, columna + ancho_barra + 1, ancho_total, f"{porcentaje:5.1f}%")


def _dibujar_panel(stdscr, estado: EstadoMonitor) -> None:
    stdscr.erase()
    alto, ancho = stdscr.getmaxyx()
    cpu, memoria = estado.snapshot_metricas()

    stdscr.addstr(0, 0, " MINI MONITOR DE RECURSOS ".center(ancho, "="),
                  curses.color_pair(COLOR_TITULO) | curses.A_BOLD)

    ancho_barra = max(min(ancho - 24, 40), 10)
    fila = 1

    # --- CPU ---
    f, c = _dibujar_caja(stdscr, fila, ancho, 3, "cpu")
    uso_cpu = cpu.get("uso_porcentaje", 0.0)
    color_cpu = COLOR_ALERTA if uso_cpu > 80 else COLOR_OK
    _escribir(stdscr, f, c, ancho, f"Nucleos: {cpu.get('nucleos', '?')}   "
              f"Frecuencia: {cpu.get('frecuencia_mhz', '?')} MHz")
    _dibujar_barra(stdscr, f + 1, c, ancho_barra, uso_cpu, color_cpu, ancho)
    _escribir(stdscr, f + 2, c, ancho, f"Carga (1/5/15 min): {cpu.get('carga_1min', '?')} / "
              f"{cpu.get('carga_5min', '?')} / {cpu.get('carga_15min', '?')}")
    fila = f + 3 + 1

    # --- MEMORIA ---
    ram_total = memoria.get("ram_total_kb", 0)
    ram_usada = memoria.get("ram_usada_kb", 0)
    porcentaje_ram = (ram_usada / ram_total * 100) if ram_total else 0.0
    color_ram = COLOR_ALERTA if porcentaje_ram > 85 else COLOR_OK
    swap_total = memoria.get("swap_total_kb", 0)
    swap_usada = memoria.get("swap_usada_kb", 0)
    porcentaje_swap = (swap_usada / swap_total * 100) if swap_total else 0.0

    f, c = _dibujar_caja(stdscr, fila, ancho, 4, "mem")
    _dibujar_barra(stdscr, f, c, ancho_barra, porcentaje_ram, color_ram, ancho)
    _escribir(stdscr, f, c + ancho_barra + 10, ancho, "RAM")
    _escribir(stdscr, f + 1, c, ancho, f"Total: {ram_total} KB   Usada: {ram_usada} KB   "
              f"Libre: {memoria.get('ram_libre_kb', '?')} KB")
    _dibujar_barra(stdscr, f + 2, c, ancho_barra, porcentaje_swap, COLOR_OK, ancho)
    _escribir(stdscr, f + 2, c + ancho_barra + 10, ancho, "SWAP")
    _escribir(stdscr, f + 3, c, ancho, f"Total: {swap_total} KB   Usada: {swap_usada} KB   "
              f"Libre: {memoria.get('swap_libre_kb', '?')} KB")
    fila = f + 4 + 1

    # --- DISCO ---
    f, c = _dibujar_caja(stdscr, fila, ancho, 2, "disco (/)")
    try:
        disco = cmd_runner.obtener_disco_principal()
        porcentaje_disco = float(disco["porcentaje"].strip("%") or 0)
        color_disco = COLOR_ALERTA if porcentaje_disco > 90 else COLOR_OK
        _dibujar_barra(stdscr, f, c, ancho_barra, porcentaje_disco, color_disco, ancho)
        _escribir(stdscr, f + 1, c, ancho, f"Total: {disco['total_kb']} KB   "
                  f"Usado: {disco['usado_kb']} KB   Libre: {disco['libre_kb']} KB")
    except (RuntimeError, ValueError) as error:
        _escribir(stdscr, f, c, ancho, f"Error: {error}")
    fila = f + 2 + 1

    # --- RED ---
    alerta_red = estado.hay_alerta_red()
    color_red = COLOR_ALERTA if alerta_red else COLOR_OK
    estado_red = "PICO DETECTADO" if alerta_red else "estable"
    try:
        interfaces = cmd_runner.obtener_red()
        error_red = None
    except RuntimeError as error:
        interfaces = []
        error_red = str(error)

    espacio_disponible = max(alto - fila - 3, 2)
    alto_red = min(1 + max(len(interfaces), 1), espacio_disponible)
    f, c = _dibujar_caja(stdscr, fila, ancho, alto_red, "red")
    _escribir(stdscr, f, c, ancho, f"Estado: {estado_red}", curses.color_pair(color_red))
    if error_red:
        _escribir(stdscr, f + 1, c, ancho, f"Error: {error_red}")
    else:
        for i, interfaz in enumerate(interfaces[:alto_red - 1]):
            linea = (f"{interfaz['interfaz']:<10} {interfaz['ip']:<18} "
                     f"RX: {interfaz['rx_bytes']:>12}  TX: {interfaz['tx_bytes']:>12}")
            _escribir(stdscr, f + 1 + i, c, ancho, linea)

    menu = "[C]Crear [V]Historial [E]Editar [D]Eliminar [P]Procesos [U]Usuarios [Q]Salir"
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


def _esperar_tecla(stdscr) -> None:
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.getch()
    stdscr.nodelay(True)
    stdscr.timeout(REFRESCO_MS)


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
    _esperar_tecla(stdscr)


def _ver_historial(stdscr) -> None:
    etiqueta = _leer_texto(stdscr, "Filtrar por etiqueta (Enter = ver todo): ")
    filtro = etiqueta or None

    while True:
        capturas = db_manager.listar_capturas(filtro)
        _dibujar_tabla_historial(stdscr, capturas)

        if not capturas:
            _esperar_tecla(stdscr)
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


def _vista_lista_desplazable(stdscr, titulo: str, encabezado: str, obtener_filas) -> None:
    """Vista de lista con scroll real (flechas, RePag/AvPag, Inicio/Fin) y una
    barra de desplazamiento vertical estilo btop en el borde derecho.

    `obtener_filas()` se llama cada vez que el usuario navega y debe devolver
    una lista de strings ya formateados (una línea por fila de datos).
    """
    offset = 0
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.keypad(True)
    try:
        while True:
            filas_texto = obtener_filas()
            alto, ancho = stdscr.getmaxyx()
            alto_util = max(alto - 5, 1)
            total = len(filas_texto)
            offset = max(0, min(offset, max(total - alto_util, 0)))

            stdscr.erase()
            stdscr.addstr(0, 0, f" {titulo} ".center(ancho, "="), curses.A_BOLD)
            _escribir(stdscr, 2, 2, ancho, encabezado, curses.A_UNDERLINE)

            columna_barra = ancho - 2
            mostrar_barra = total > alto_util > 0
            ancho_texto = (columna_barra - 1) if mostrar_barra else ancho

            for i, linea in enumerate(filas_texto[offset:offset + alto_util]):
                _escribir(stdscr, 3 + i, 2, ancho_texto, linea)

            if mostrar_barra:
                proporcion = alto_util / total
                largo_indicador = max(1, int(alto_util * proporcion))
                maximo_offset = max(total - alto_util, 1)
                inicio_indicador = int(offset / maximo_offset * (alto_util - largo_indicador))
                for i in range(alto_util):
                    caracter = "█" if inicio_indicador <= i < inicio_indicador + largo_indicador else "│"
                    _escribir(stdscr, 3 + i, columna_barra, ancho, caracter)

            if total:
                pie = (f"Mostrando {offset + 1}-{min(offset + alto_util, total)} de {total}   "
                       f"[flechas] mover  [RePag/AvPag] pagina  [Inicio/Fin]  [Q/Enter] volver")
            else:
                pie = "Sin datos.  [Q/Enter] volver"
            _escribir(stdscr, alto - 1, 2, ancho, pie, curses.A_DIM)
            stdscr.refresh()

            tecla = stdscr.getch()
            if tecla == curses.KEY_UP:
                offset -= 1
            elif tecla == curses.KEY_DOWN:
                offset += 1
            elif tecla == curses.KEY_PPAGE:
                offset -= alto_util
            elif tecla == curses.KEY_NPAGE:
                offset += alto_util
            elif tecla == curses.KEY_HOME:
                offset = 0
            elif tecla == curses.KEY_END:
                offset = max(total - alto_util, 0)
            elif tecla in (ord("q"), ord("Q"), 27, 10, 13):
                return
    finally:
        stdscr.nodelay(True)
        stdscr.timeout(REFRESCO_MS)


def _ver_procesos(stdscr) -> None:
    def obtener_filas() -> list[str]:
        try:
            procesos = cmd_runner.obtener_procesos()
        except RuntimeError as error:
            return [f"Error al listar procesos: {error}"]
        return [f"{p['pid']:<8}{p['nombre']:<24}{p['estado']:<8}{p['usuario']:<15}" for p in procesos]

    encabezado = f"{'PID':<8}{'NOMBRE':<24}{'ESTADO':<8}{'USUARIO':<15}"
    _vista_lista_desplazable(stdscr, "PROCESOS", encabezado, obtener_filas)


def _ver_usuarios(stdscr) -> None:
    def obtener_filas() -> list[str]:
        try:
            usuarios = cmd_runner.obtener_usuarios()
        except RuntimeError as error:
            return [f"Error al listar usuarios: {error}"]
        return [f"{u['usuario']:<15}{u['terminal']:<12}{u['tiempo_conexion']:<20}" for u in usuarios]

    encabezado = f"{'USUARIO':<15}{'TERMINAL':<12}{'TIEMPO DE CONEXION':<20}"
    _vista_lista_desplazable(stdscr, "USUARIOS CONECTADOS", encabezado, obtener_filas)


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
        elif tecla in (ord("p"), ord("P")):
            _ver_procesos(stdscr)
        elif tecla in (ord("u"), ord("U")):
            _ver_usuarios(stdscr)


def iniciar_tui(estado: EstadoMonitor) -> None:
    """Punto de entrada de la TUI. curses.wrapper garantiza una salida limpia
    de la terminal incluso si ocurre una excepción no controlada."""
    curses.wrapper(_bucle_principal, estado)
