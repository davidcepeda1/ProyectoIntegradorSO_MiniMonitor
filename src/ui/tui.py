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
import json
import re

from src.core import cmd_runner
from src.database import db_manager
from src.main import EstadoMonitor, evento_salida, realizar_captura

REFRESCO_MS = 1000

COLOR_OK = 1
COLOR_ALERTA = 2
COLOR_TITULO = 3
COLOR_ADVERTENCIA = 4

BLOQUES_SPARKLINE = "▁▂▃▄▅▆▇█"
ANCHO_SPARKLINE = 10

# Umbrales de la "carita" de salud global: se evalúan sobre los mismos
# porcentajes que ya colorean las barras (CPU/RAM/Disco) más la alerta de
# red, combinados en un único semáforo de 3 niveles para dar una lectura
# de un vistazo del estado general del sistema.
CARAS_SALUD = {
    "ok": "(^‿^)",
    "alerta": "(o_o)",
    "critico": "(x_x)",
}
MENSAJES_SALUD = {
    "ok": "Todo tranquilo por aqui.",
    "alerta": "Se esta calentando esto...",
    "critico": "SOS: el sistema esta sufriendo.",
}
COLOR_POR_SALUD = {
    "ok": COLOR_OK,
    "alerta": COLOR_ADVERTENCIA,
    "critico": COLOR_ALERTA,
}

# Dimensiones mínimas para intentar dibujar cualquier pantalla con cajas.
# Por debajo de esto, en vez de arriesgarse a que curses lance
# curses.error al tratar de escribir fuera de los límites de la ventana,
# se muestra un aviso simple y se omite el dibujo normal.
MINIMO_ALTO = 6
MINIMO_ANCHO = 20


def _terminal_muy_pequena(stdscr) -> bool:
    """Si la terminal no alcanza el tamaño mínimo, muestra un aviso seguro
    y devuelve True para que el llamador omita su dibujo normal."""
    alto, ancho = stdscr.getmaxyx()
    if alto >= MINIMO_ALTO and ancho >= MINIMO_ANCHO:
        return False
    mensaje = "Terminal muy pequeña para mostrar esta pantalla. Agranda la ventana."
    try:
        stdscr.erase()
        stdscr.addstr(0, 0, mensaje[:max(ancho - 1, 0)])
        stdscr.noutrefresh()
        curses.doupdate()
    except curses.error:
        pass
    return True


def _configurar_colores() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_OK, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_ALERTA, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_TITULO, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_ADVERTENCIA, curses.COLOR_YELLOW, -1)


def _escribir(stdscr, fila: int, columna: int, ancho: int, texto: str, atributo=0) -> None:
    # Se permite escribir hasta la ultima columna (ancho - 1): curses solo
    # prohibe escribir en la celda inferior-derecha exacta de la ventana,
    # y esa excepcion puntual se descarta con el try/except.
    try:
        stdscr.addstr(fila, columna, texto[:max(ancho - columna, 0)], atributo)
    except curses.error:
        pass


def _dibujar_caja(stdscr, fila0: int, ancho: int, alto_contenido: int, titulo: str,
                   color_borde: int = 0) -> tuple[int, int]:
    """Dibuja una caja con borde y título (estilo btop). Devuelve (fila_contenido, columna_contenido).

    `color_borde` (opcional) resalta el borde completo de la caja — no solo
    los números — cuando esa sección está en alerta, para que el problema
    se note incluso de reojo sin tener que leer los porcentajes.
    """
    alto_caja = alto_contenido + 2
    atributo = curses.color_pair(color_borde) if color_borde else 0
    _escribir(stdscr, fila0, 0, ancho, "┌" + "─" * max(ancho - 2, 0) + "┐", atributo)
    for i in range(1, alto_caja - 1):
        _escribir(stdscr, fila0 + i, 0, ancho, "│", atributo)
        _escribir(stdscr, fila0 + i, ancho - 1, ancho, "│", atributo)
    _escribir(stdscr, fila0 + alto_caja - 1, 0, ancho, "└" + "─" * max(ancho - 2, 0) + "┘", atributo)
    _escribir(stdscr, fila0, 2, ancho, f"┤ {titulo} ├", curses.A_BOLD | curses.color_pair(COLOR_TITULO))
    return fila0 + 1, 2


def _dibujar_barra(stdscr, fila: int, columna: int, ancho_barra: int, porcentaje: float,
                    color: int, ancho_total: int) -> None:
    porcentaje = max(0.0, min(porcentaje, 100.0))
    llenos = int(round(ancho_barra * porcentaje / 100))
    barra = "█" * llenos + "░" * (ancho_barra - llenos)
    _escribir(stdscr, fila, columna, ancho_total, barra, curses.color_pair(color))
    _escribir(stdscr, fila, columna + ancho_barra + 1, ancho_total, f"{porcentaje:5.1f}%")


def _sparkline(valores: list[float], ancho: int = ANCHO_SPARKLINE) -> str:
    """Mini-gráfico de barras con el historial reciente (0-100%) usando
    caracteres de bloque Unicode, estilo btop."""
    recientes = valores[-ancho:]
    if not recientes:
        return "░" * ancho
    caracteres = []
    for valor in recientes:
        valor = max(0.0, min(valor, 100.0))
        indice = int(valor / 100 * (len(BLOQUES_SPARKLINE) - 1))
        caracteres.append(BLOQUES_SPARKLINE[indice])
    return "".join(caracteres).rjust(ancho, "░")


def _tendencia(valores: list[float]) -> str:
    """Flecha de tendencia comparando la última lectura con la anterior.
    Se usa un margen de 0.5 puntos para no parpadear con ruido de medición."""
    if len(valores) < 2:
        return " "
    anterior, actual = valores[-2], valores[-1]
    if actual > anterior + 0.5:
        return "↑"
    if actual < anterior - 0.5:
        return "↓"
    return "→"


def _evaluar_salud(cpu_uso: float, porcentaje_ram: float, porcentaje_disco: float, alerta_red: bool) -> str:
    """Semáforo de 3 niveles combinando los mismos umbrales que ya colorean
    las barras individuales, para una lectura de "estado general" de un vistazo."""
    if cpu_uso > 90 or porcentaje_ram > 90 or porcentaje_disco > 95 or alerta_red:
        return "critico"
    if cpu_uso > 75 or porcentaje_ram > 80 or porcentaje_disco > 85:
        return "alerta"
    return "ok"


def _dibujar_panel(stdscr, estado: EstadoMonitor) -> None:
    if _terminal_muy_pequena(stdscr):
        return

    stdscr.erase()
    alto, ancho = stdscr.getmaxyx()
    cpu, memoria = estado.snapshot_metricas()
    historial_cpu, historial_ram = estado.snapshot_historial()

    stdscr.addstr(0, 0, " MINI MONITOR DE RECURSOS ".center(ancho, "="),
                  curses.color_pair(COLOR_TITULO) | curses.A_BOLD)

    ancho_barra = max(min(ancho - 24, 40), 10)
    fila_menu = alto - 1

    # Se calculan disco y red una sola vez aqui arriba (en vez de al llegar a
    # sus respectivas cajas) porque la carita de salud global los necesita
    # de entrada, antes de dibujar ninguna caja.
    uso_cpu = cpu.get("uso_porcentaje", 0.0)
    ram_total = memoria.get("ram_total_kb", 0)
    ram_usada = memoria.get("ram_usada_kb", 0)
    porcentaje_ram = (ram_usada / ram_total * 100) if ram_total else 0.0

    try:
        disco = cmd_runner.obtener_disco_principal()
        porcentaje_disco = float(disco["porcentaje"].strip("%") or 0)
        error_disco = None
    except (RuntimeError, ValueError) as error:
        disco = None
        porcentaje_disco = 0.0
        error_disco = str(error)

    alerta_red = estado.hay_alerta_red()

    # --- Fila de estado: carita reactiva + mensaje de humor + tag fijo ---
    salud = _evaluar_salud(uso_cpu, porcentaje_ram, porcentaje_disco, alerta_red)
    color_salud = COLOR_POR_SALUD[salud]
    texto_estado = f"{CARAS_SALUD[salud]}  {MENSAJES_SALUD[salud]}"
    _escribir(stdscr, 1, 2, ancho, texto_estado, curses.color_pair(color_salud) | curses.A_BOLD)
    tag = "I <3 Linux"
    _escribir(stdscr, 1, max(ancho - len(tag) - 2, 0), ancho, tag, curses.A_DIM)

    fila = 2
    secciones_omitidas = 0

    def cabe(alto_contenido: int) -> bool:
        # +2 por los bordes superior/inferior de la caja; se deja 1 fila libre
        # antes del menu para que nunca se sobrepongan (esto es lo que fallaba
        # en terminales pequeñas: las cajas se dibujaban sin este chequeo y
        # terminaban encimadas con el menu inferior).
        return fila + alto_contenido + 2 <= fila_menu

    # --- CPU ---
    if cabe(3):
        color_cpu = COLOR_ALERTA if uso_cpu > 80 else COLOR_OK
        f, c = _dibujar_caja(stdscr, fila, ancho, 3, "cpu",
                              color_borde=COLOR_ALERTA if uso_cpu > 80 else 0)
        _escribir(stdscr, f, c, ancho, f"Nucleos: {cpu.get('nucleos', '?')}   "
                  f"Frecuencia: {cpu.get('frecuencia_mhz', '?')} MHz")
        _dibujar_barra(stdscr, f + 1, c, ancho_barra, uso_cpu, color_cpu, ancho)
        _escribir(stdscr, f + 1, c + ancho_barra + 9, ancho,
                  f"{_tendencia(historial_cpu)} {_sparkline(historial_cpu)}")
        _escribir(stdscr, f + 2, c, ancho, f"Carga (1/5/15 min): {cpu.get('carga_1min', '?')} / "
                  f"{cpu.get('carga_5min', '?')} / {cpu.get('carga_15min', '?')}")
        fila = f + 3 + 1
    else:
        secciones_omitidas += 1

    # --- MEMORIA ---
    if cabe(4):
        color_ram = COLOR_ALERTA if porcentaje_ram > 85 else COLOR_OK
        swap_total = memoria.get("swap_total_kb", 0)
        swap_usada = memoria.get("swap_usada_kb", 0)
        porcentaje_swap = (swap_usada / swap_total * 100) if swap_total else 0.0
        color_swap = COLOR_ALERTA if porcentaje_swap > 85 else COLOR_OK

        f, c = _dibujar_caja(stdscr, fila, ancho, 4, "mem",
                              color_borde=COLOR_ALERTA if (porcentaje_ram > 85 or porcentaje_swap > 85) else 0)
        _dibujar_barra(stdscr, f, c, ancho_barra, porcentaje_ram, color_ram, ancho)
        _escribir(stdscr, f, c + ancho_barra + 9, ancho,
                  f"{_tendencia(historial_ram)} {_sparkline(historial_ram)}  RAM")
        _escribir(stdscr, f + 1, c, ancho, f"Total: {ram_total} KB   Usada: {ram_usada} KB   "
                  f"Libre: {memoria.get('ram_libre_kb', '?')} KB")
        _dibujar_barra(stdscr, f + 2, c, ancho_barra, porcentaje_swap, color_swap, ancho)
        _escribir(stdscr, f + 2, c + ancho_barra + 10, ancho, "SWAP")
        _escribir(stdscr, f + 3, c, ancho, f"Total: {swap_total} KB   Usada: {swap_usada} KB   "
                  f"Libre: {memoria.get('swap_libre_kb', '?')} KB")
        fila = f + 4 + 1
    else:
        secciones_omitidas += 1

    # --- DISCO ---
    if cabe(2):
        color_disco = COLOR_ALERTA if porcentaje_disco > 90 else COLOR_OK
        f, c = _dibujar_caja(stdscr, fila, ancho, 2, "disco (/)",
                              color_borde=COLOR_ALERTA if porcentaje_disco > 90 else 0)
        if error_disco:
            _escribir(stdscr, f, c, ancho, f"Error: {error_disco}")
        else:
            _dibujar_barra(stdscr, f, c, ancho_barra, porcentaje_disco, color_disco, ancho)
            _escribir(stdscr, f + 1, c, ancho, f"Total: {disco['total_kb']} KB   "
                      f"Usado: {disco['usado_kb']} KB   Libre: {disco['libre_kb']} KB")
        fila = f + 2 + 1
    else:
        secciones_omitidas += 1

    # --- RED ---
    color_red = COLOR_ALERTA if alerta_red else COLOR_OK
    estado_red = "PICO DETECTADO" if alerta_red else "estable"
    try:
        interfaces = cmd_runner.obtener_red()
        error_red = None
    except RuntimeError as error:
        interfaces = []
        error_red = str(error)

    alto_red_deseado = 1 + max(len(interfaces), 1)
    if cabe(1):
        alto_red = min(alto_red_deseado, fila_menu - fila - 2)
        f, c = _dibujar_caja(stdscr, fila, ancho, alto_red, "red",
                              color_borde=COLOR_ALERTA if alerta_red else 0)
        _escribir(stdscr, f, c, ancho, f"Estado: {estado_red}", curses.color_pair(color_red))
        if error_red:
            _escribir(stdscr, f + 1, c, ancho, f"Error: {error_red}")
        else:
            for i, interfaz in enumerate(interfaces[:alto_red - 1]):
                linea = (f"{interfaz['interfaz']:<10} {interfaz['ip']:<18} "
                         f"RX: {interfaz['rx_bytes']:>12}  TX: {interfaz['tx_bytes']:>12}")
                _escribir(stdscr, f + 1 + i, c, ancho, linea)
    else:
        secciones_omitidas += 1

    if secciones_omitidas:
        _escribir(stdscr, fila_menu - 1, 2, ancho,
                  f"(agranda la terminal para ver {secciones_omitidas} seccion(es) mas)",
                  curses.A_DIM)

    menu = "[C]Crear [V]Historial [E]Editar [D]Eliminar [P]Procesos [U]Usuarios [Q]Salir"
    stdscr.addstr(fila_menu, 0, menu.center(ancho, " ")[:ancho - 1], curses.A_REVERSE)

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


def _leer_numero(stdscr, prompt: str, max_digitos: int = 10) -> str:
    """Como `_leer_texto`, pero filtra cada tecla al vuelo: solo los dígitos
    0-9 se insertan, cualquier otra tecla se ignora silenciosamente (no se
    imprime ni se acepta). Así el usuario no puede llegar a escribir un ID
    inválido, en vez de dejarlo escribir cualquier cosa y validar después.

    Devuelve una cadena de solo dígitos (posiblemente vacía si se cancela
    con Enter sin escribir nada, o con Esc).
    """
    alto, ancho = stdscr.getmaxyx()
    fila = alto - 2
    columna_inicio = min(len(prompt), max(ancho - 2, 0))

    def redibujar(digitos: str) -> None:
        _escribir(stdscr, fila, 0, ancho, " " * max(ancho - 1, 0))
        _escribir(stdscr, fila, 0, ancho, prompt)
        _escribir(stdscr, fila, columna_inicio, ancho, digitos)

    redibujar("")
    stdscr.refresh()

    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.keypad(True)
    curses.curs_set(1)

    digitos = ""
    try:
        while True:
            tecla = stdscr.getch()

            if tecla in (10, 13):  # Enter: confirma lo escrito hasta ahora
                break
            if tecla == 27:  # Esc: cancela, se comporta como si no se hubiera escrito nada
                digitos = ""
                break
            if tecla in (curses.KEY_BACKSPACE, 127, 8):
                digitos = digitos[:-1]
                redibujar(digitos)
                continue
            if 0 <= tecla < 256 and chr(tecla).isdigit() and len(digitos) < max_digitos:
                digitos += chr(tecla)
                redibujar(digitos)
            # cualquier otra tecla (letras, símbolos, flechas, etc.) se ignora por completo
    finally:
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(REFRESCO_MS)

    return digitos


def _confirmar(stdscr, mensaje: str) -> bool:
    """Confirmación de una sola tecla: 'S' confirma, cualquier otra tecla
    cancela. El valor por defecto ante Enter/Esc/cualquier tecla ambigua es
    NO, para que una operación destructiva (eliminar) nunca ocurra por
    accidente al presionar la tecla equivocada."""
    alto, ancho = stdscr.getmaxyx()
    fila = alto - 2
    texto = f"{mensaje} [S = si / cualquier tecla = no]: "
    _escribir(stdscr, fila, 0, ancho, " " * max(ancho - 1, 0))
    _escribir(stdscr, fila, 0, ancho, texto, curses.A_BOLD)
    stdscr.refresh()

    stdscr.nodelay(False)
    stdscr.timeout(-1)
    tecla = stdscr.getch()
    stdscr.nodelay(True)
    stdscr.timeout(REFRESCO_MS)

    return tecla in (ord("s"), ord("S"))


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
    """Divide por comas y sanitiza cada etiqueta: solo se conservan letras
    (incluye acentos/ñ vía \\w unicode), números, espacios y guiones.

    No es una defensa contra inyección SQL — toda la capa de datos ya usa
    consultas parametrizadas (`?`), así que eso está cubierto de raíz. La
    razón real es de integridad de datos: las etiquetas se guardan como
    "tag1, tag2" separadas por coma; una etiqueta que contuviera una coma
    (o caracteres de control) corrompería ese formato al volver a leerlo.
    """
    etiquetas = []
    for cruda in texto.split(","):
        limpia = re.sub(r"[^\w\s-]", "", cruda, flags=re.UNICODE).strip()
        if limpia:
            etiquetas.append(limpia)
    return etiquetas or None


def _crear_captura(stdscr, estado: EstadoMonitor) -> None:
    texto = _leer_texto(stdscr, "Etiquetas separadas por coma (Enter = GENERAL): ")
    try:
        captura_id, advertencia = realizar_captura(estado, etiquetas=_parsear_etiquetas(texto))
        mensaje = f"Captura #{captura_id} guardada correctamente."
        if advertencia:
            mensaje += f"  [Aviso: {advertencia}]"
        _mostrar_mensaje(stdscr, mensaje)
    except RuntimeError as error:
        _mostrar_mensaje(stdscr, f"Error al capturar: {error}")


def _dibujar_tabla_historial(stdscr, capturas: list[dict]) -> None:
    if _terminal_muy_pequena(stdscr):
        return

    stdscr.erase()
    alto, ancho = stdscr.getmaxyx()
    alto_contenido = max(alto - 3, 1)
    f, c = _dibujar_caja(stdscr, 0, ancho, alto_contenido, "HISTORIAL DE CAPTURAS")

    if not capturas:
        _escribir(stdscr, f, c, ancho, "No hay capturas registradas.")
    else:
        encabezado = f"{'ID':<5}{'Fecha':<21}{'CPU%':<8}{'RAM(KB)':<12}{'Etiquetas':<30}"
        _escribir(stdscr, f, c, ancho, encabezado, curses.A_BOLD | curses.color_pair(COLOR_TITULO))

        visibles = max(alto_contenido - 1, 0)
        for i, captura in enumerate(capturas[:visibles]):
            atributo = curses.A_DIM if i % 2 else curses.A_NORMAL
            linea = (f"{captura['id']:<5}{captura['fecha_hora']:<21}"
                     f"{captura['cpu_uso']:<8}{captura['ram_usada']:<12}{captura['etiquetas']:<30}")
            _escribir(stdscr, f + 1 + i, c, ancho, linea, atributo)

        if len(capturas) > visibles:
            _escribir(stdscr, alto - 1, 2, ancho,
                      f"(mostrando {visibles} de {len(capturas)} — filtra por etiqueta para acotar)",
                      curses.A_DIM)

    stdscr.refresh()


def _ver_procesos_capturados(stdscr, captura_id: int, procesos: list[dict]) -> None:
    encabezado = f"{'PID':<8}{'NOMBRE':<24}{'ESTADO':<8}{'USUARIO':<15}"
    filas = [f"{p['pid']:<8}{p['nombre']:<24}{p['estado']:<8}{p['usuario']:<15}" for p in procesos]
    _vista_lista_desplazable(stdscr, f"PROCESOS - CAPTURA #{captura_id}", encabezado, lambda: filas)


def _ver_usuarios_capturados(stdscr, captura_id: int, usuarios: list[dict]) -> None:
    encabezado = f"{'USUARIO':<15}{'TERMINAL':<12}{'TIEMPO DE CONEXION':<20}"
    filas = [f"{u['usuario']:<15}{u['terminal']:<12}{u['tiempo_conexion']:<20}" for u in usuarios]
    _vista_lista_desplazable(stdscr, f"USUARIOS - CAPTURA #{captura_id}", encabezado, lambda: filas)


def _mostrar_detalle_captura(stdscr, captura: dict) -> None:
    procesos = json.loads(captura.get("procesos_json") or "[]")
    usuarios = json.loads(captura.get("usuarios_json") or "[]")

    while True:
        if _terminal_muy_pequena(stdscr):
            stdscr.nodelay(False)
            stdscr.timeout(-1)
            tecla = stdscr.getch()
            stdscr.nodelay(True)
            stdscr.timeout(REFRESCO_MS)
            if tecla in (ord("q"), ord("Q"), 27, 10, 13):
                return
            continue  # cualquier otra tecla: reintenta por si la terminal ya se agrando

        stdscr.erase()
        alto, ancho = stdscr.getmaxyx()
        alto_contenido = max(alto - 3, 1)
        f, c = _dibujar_caja(stdscr, 0, ancho, alto_contenido, f"DETALLE DE CAPTURA #{captura['id']}")
        ancho_barra = max(min(ancho - 30, 40), 10)

        _escribir(stdscr, f, c, ancho, f"Fecha/Hora: {captura['fecha_hora']}    "
                  f"Etiquetas: {captura['etiquetas']}")

        fila = f + 2
        color_cpu = COLOR_ALERTA if captura["cpu_uso"] > 80 else COLOR_OK
        _escribir(stdscr, fila, c, ancho, "CPU", curses.A_BOLD)
        _dibujar_barra(stdscr, fila + 1, c, ancho_barra, captura["cpu_uso"], color_cpu, ancho)
        fila += 3

        ram_total = captura["ram_total"]
        ram_usada = captura["ram_usada"]
        porcentaje_ram = (ram_usada / ram_total * 100) if ram_total else 0.0
        color_ram = COLOR_ALERTA if porcentaje_ram > 85 else COLOR_OK
        _escribir(stdscr, fila, c, ancho, "RAM", curses.A_BOLD)
        _dibujar_barra(stdscr, fila + 1, c, ancho_barra, porcentaje_ram, color_ram, ancho)
        _escribir(stdscr, fila + 2, c, ancho, f"{ram_usada} / {ram_total} KB")
        fila += 4

        disco_total = captura["disco_total"]
        disco_usada = captura["disco_usada"]
        porcentaje_disco = (disco_usada / disco_total * 100) if disco_total else 0.0
        color_disco = COLOR_ALERTA if porcentaje_disco > 90 else COLOR_OK
        _escribir(stdscr, fila, c, ancho, "DISCO", curses.A_BOLD)
        _dibujar_barra(stdscr, fila + 1, c, ancho_barra, porcentaje_disco, color_disco, ancho)
        _escribir(stdscr, fila + 2, c, ancho, f"{disco_usada} / {disco_total} KB")
        fila += 4

        _escribir(stdscr, fila, c, ancho, "RED", curses.A_BOLD)
        _escribir(stdscr, fila + 1, c, ancho, f"Entrada: {captura['red_trafico_in']} bytes   "
                  f"Salida: {captura['red_trafico_out']} bytes")
        fila += 3

        _escribir(stdscr, fila, c, ancho,
                  f"PROCESOS: {len(procesos)} capturados   -> tecla [P] para ver la lista", curses.A_BOLD)
        fila += 1
        _escribir(stdscr, fila, c, ancho,
                  f"USUARIOS: {len(usuarios)} conectados   -> tecla [U] para ver la lista", curses.A_BOLD)

        _escribir(stdscr, alto - 1, 2, ancho,
                  "[P] procesos  [U] usuarios  [cualquier otra tecla] volver", curses.A_DIM)
        stdscr.refresh()

        stdscr.nodelay(False)
        stdscr.timeout(-1)
        tecla = stdscr.getch()
        stdscr.nodelay(True)
        stdscr.timeout(REFRESCO_MS)

        if tecla in (ord("p"), ord("P")):
            _ver_procesos_capturados(stdscr, captura["id"], procesos)
        elif tecla in (ord("u"), ord("U")):
            _ver_usuarios_capturados(stdscr, captura["id"], usuarios)
        else:
            return


def _ver_historial(stdscr) -> None:
    etiqueta = _leer_texto(stdscr, "Filtrar por etiqueta (Enter = ver todo): ")
    filtro = etiqueta or None

    while True:
        capturas = db_manager.listar_capturas(filtro)
        _dibujar_tabla_historial(stdscr, capturas)

        if not capturas:
            _esperar_tecla(stdscr)
            return

        id_texto = _leer_numero(stdscr, "ID para ver detalle (Enter para volver): ")
        if not id_texto:
            return

        captura = next((c for c in capturas if c["id"] == int(id_texto)), None)
        if captura is None:
            _mostrar_mensaje(stdscr, "No se encontro esa captura en la lista actual.")
            continue

        _mostrar_detalle_captura(stdscr, captura)


def _editar_etiquetas(stdscr) -> None:
    id_texto = _leer_numero(stdscr, "ID de la captura a editar: ")
    if not id_texto:
        return
    captura_id = int(id_texto)

    etiquetas_texto = _leer_texto(stdscr, "Nuevas etiquetas separadas por coma: ")
    nuevas_etiquetas = _parsear_etiquetas(etiquetas_texto)
    resumen = ", ".join(nuevas_etiquetas) if nuevas_etiquetas else "GENERAL"

    if not _confirmar(stdscr, f"¿Cambiar etiquetas de la captura #{captura_id} a [{resumen}]?"):
        _mostrar_mensaje(stdscr, "Edicion cancelada.")
        return

    exito = db_manager.actualizar_etiquetas(captura_id, nuevas_etiquetas)
    _mostrar_mensaje(stdscr, "Etiquetas actualizadas." if exito else "No se encontro esa captura.")


def _eliminar_registro(stdscr) -> None:
    id_texto = _leer_numero(stdscr, "ID de la captura a eliminar: ")
    if not id_texto:
        return
    captura_id = int(id_texto)

    if not _confirmar(stdscr, f"¿ELIMINAR la captura #{captura_id}? Esta accion no se puede deshacer."):
        _mostrar_mensaje(stdscr, "Eliminacion cancelada.")
        return

    exito = db_manager.eliminar_captura(captura_id)
    _mostrar_mensaje(stdscr, "Captura eliminada." if exito else "No se encontro esa captura.")


def _vista_lista_desplazable(stdscr, titulo: str, encabezado: str, obtener_filas) -> None:
    """Vista de lista en caja (estilo btop) con scroll real (flechas, RePag/AvPag,
    Inicio/Fin), fila de encabezado resaltada, filas alternadas para facilitar
    la lectura, y una barra de desplazamiento vertical en el borde derecho.

    `obtener_filas()` se llama cada vez que el usuario navega y debe devolver
    una lista de strings ya formateados (una línea por fila de datos). El
    diseño se recalcula en cada iteración a partir de `getmaxyx()`, por lo
    que se adapta automáticamente si la terminal cambia de tamaño mientras
    la vista está abierta.
    """
    offset = 0
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.keypad(True)
    try:
        while True:
            if _terminal_muy_pequena(stdscr):
                tecla = stdscr.getch()
                if tecla in (ord("q"), ord("Q"), 27, 10, 13):
                    return
                continue  # cualquier otra tecla: reintenta por si la terminal ya se agrando

            filas_texto = obtener_filas()
            alto, ancho = stdscr.getmaxyx()

            # La caja ocupa toda la pantalla salvo la ultima fila (pie de ayuda).
            # Dentro de la caja: 1 fila de encabezado + N filas de datos.
            alto_caja_contenido = max(alto - 3, 1)
            alto_lista = max(alto_caja_contenido - 1, 0)
            total = len(filas_texto)
            offset = max(0, min(offset, max(total - alto_lista, 0)))

            stdscr.erase()
            f, c = _dibujar_caja(stdscr, 0, ancho, alto_caja_contenido, titulo)
            _escribir(stdscr, f, c, ancho, encabezado, curses.A_BOLD | curses.color_pair(COLOR_TITULO))

            columna_barra = ancho - 2
            mostrar_barra = total > alto_lista > 0
            ancho_texto = (columna_barra - 1) if mostrar_barra else ancho

            for i, linea in enumerate(filas_texto[offset:offset + alto_lista]):
                atributo = curses.A_DIM if i % 2 else curses.A_NORMAL
                _escribir(stdscr, f + 1 + i, c, ancho_texto, linea, atributo)

            if mostrar_barra:
                proporcion = alto_lista / total
                largo_indicador = max(1, int(alto_lista * proporcion))
                maximo_offset = max(total - alto_lista, 1)
                inicio_indicador = int(offset / maximo_offset * (alto_lista - largo_indicador))
                for i in range(alto_lista):
                    caracter = "█" if inicio_indicador <= i < inicio_indicador + largo_indicador else "│"
                    _escribir(stdscr, f + 1 + i, columna_barra, ancho, caracter)

            if total:
                pie = (f"Mostrando {offset + 1}-{min(offset + alto_lista, total)} de {total}   "
                       f"[flechas] mover  [RePag/AvPag] pagina  [Inicio/Fin]  [Q/Enter] volver")
            else:
                pie = "Sin datos.  [Q/Enter] volver"
            _escribir(stdscr, alto - 1, 2, ancho, pie, curses.A_DIM)
            stdscr.refresh()

            tecla = stdscr.getch()
            if tecla == curses.KEY_RESIZE:
                continue
            elif tecla == curses.KEY_UP:
                offset -= 1
            elif tecla == curses.KEY_DOWN:
                offset += 1
            elif tecla == curses.KEY_PPAGE:
                offset -= alto_lista
            elif tecla == curses.KEY_NPAGE:
                offset += alto_lista
            elif tecla == curses.KEY_HOME:
                offset = 0
            elif tecla == curses.KEY_END:
                offset = max(total - alto_lista, 0)
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
