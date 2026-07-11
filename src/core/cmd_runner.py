"""Extracción de datos del sistema mediante comandos Linux ejecutados con subprocess.

Cubre los módulos de Disco, Procesos, Usuarios y Red. Los contadores de
tráfico de red se leen de /proc/net/dev (más estable de parsear que la
salida de `ip -s link`); las interfaces y direcciones IP sí se obtienen
del comando `ip`, cumpliendo el requisito de ejecución de comandos Linux.
"""

import re
import subprocess
from datetime import datetime

FS_PSEUDO = {"tmpfs", "devtmpfs", "overlay", "squashfs", "efivarfs", "proc", "sysfs"}


def _ejecutar(comando: list[str]) -> str:
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            check=True,
        )
        return resultado.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as error:
        raise RuntimeError(f"Fallo al ejecutar {' '.join(comando)}: {error}") from error


def obtener_disco() -> list[dict]:
    """Espacio total, usado y libre por sistema de archivos real, vía `df`."""
    salida = _ejecutar(["df", "-k", "--output=source,fstype,size,used,avail,pcent,target"])
    lineas = salida.strip().splitlines()[1:]

    discos = []
    for linea in lineas:
        partes = linea.split()
        if len(partes) < 7:
            continue
        origen, tipo_fs, total, usado, libre, porcentaje, punto_montaje = partes[0], partes[1], *partes[2:]
        if tipo_fs in FS_PSEUDO:
            continue
        discos.append({
            "origen": origen,
            "tipo_fs": tipo_fs,
            "total_kb": int(total),
            "usado_kb": int(usado),
            "libre_kb": int(libre),
            "porcentaje": porcentaje,
            "punto_montaje": punto_montaje,
        })
    return discos


def obtener_disco_principal() -> dict:
    """Disco correspondiente al punto de montaje raíz ('/'), para persistir en la BD."""
    for disco in obtener_disco():
        if disco["punto_montaje"] == "/":
            return disco
    raise RuntimeError("No se encontró el sistema de archivos raíz ('/') en `df`.")


def obtener_procesos() -> list[dict]:
    """PID, nombre, estado y usuario propietario de cada proceso, vía `ps`."""
    salida = _ejecutar(["ps", "-eo", "pid,comm,stat,user", "--no-headers"])

    procesos = []
    for linea in salida.strip().splitlines():
        partes = linea.split(maxsplit=3)
        if len(partes) < 4:
            continue
        pid, nombre, estado, usuario = partes
        procesos.append({
            "pid": int(pid),
            "nombre": nombre,
            "estado": estado,
            "usuario": usuario,
        })
    return procesos


def _usuarios_via_who() -> list[dict]:
    """Usuarios conectados y tiempo de conexión (calculado), vía `who`.

    `who` depende de /run/utmp, una base de datos de sesiones de login que
    solo actualizan programas como login/getty/sshd. En sistemas con
    sesiones gestionadas por systemd-logind (Wayland, muchas distros
    modernas) puede legítimamente no reportar nada aunque haya un usuario
    con sesión activa.
    """
    try:
        salida = _ejecutar(["who"])
    except RuntimeError:
        return []

    usuarios = []
    ahora = datetime.now()
    for linea in salida.strip().splitlines():
        if not linea:
            continue
        partes = linea.split()
        if len(partes) < 4:
            continue
        usuario, terminal, fecha, hora = partes[0], partes[1], partes[2], partes[3]

        try:
            login = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
            delta = ahora - login
            horas, resto = divmod(int(delta.total_seconds()), 3600)
            minutos = resto // 60
            tiempo_conexion = f"{horas}h {minutos}m"
        except ValueError:
            tiempo_conexion = "desconocido"

        usuarios.append({
            "usuario": usuario,
            "terminal": terminal,
            "tiempo_conexion": tiempo_conexion,
        })
    return usuarios


def _usuarios_via_loginctl() -> list[dict]:
    """Respaldo para `who`: sesiones reportadas por systemd-logind.

    Se usa cuando `who` no encuentra nada porque la sesión activa nunca se
    registró en el utmp clásico (caso típico en Wayland). Se descartan las
    sesiones clase "manager" (procesos internos de systemd, no logins).
    """
    try:
        salida = _ejecutar(["loginctl", "list-sessions", "--no-legend"])
    except RuntimeError:
        return []

    usuarios = []
    for linea in salida.strip().splitlines():
        partes = linea.split()
        if len(partes) < 7:
            continue
        session_id, usuario, clase, terminal = partes[0], partes[2], partes[5], partes[6]
        if clase != "user":
            continue

        try:
            desde = _ejecutar(["loginctl", "show-session", session_id, "-p", "Timestamp", "--value"]).strip()
        except RuntimeError:
            desde = ""

        usuarios.append({
            "usuario": usuario,
            "terminal": terminal if terminal != "-" else "?",
            "tiempo_conexion": f"desde {desde}" if desde else "activa (systemd)",
        })
    return usuarios


def _usuarios_via_w() -> list[dict]:
    """Ultimo respaldo: comando `w`, que en algunos sistemas detecta sesiones
    (via /proc) que ni `who` ni utmp reportan correctamente."""
    try:
        salida = _ejecutar(["w", "-h"])
    except RuntimeError:
        return []

    usuarios = []
    for linea in salida.strip().splitlines():
        partes = linea.split()
        if len(partes) < 3:
            continue
        usuario, terminal, login_desde = partes[0], partes[1], partes[2]
        usuarios.append({
            "usuario": usuario,
            "terminal": terminal,
            "tiempo_conexion": f"desde {login_desde}",
        })
    return usuarios


def obtener_usuarios() -> list[dict]:
    """Usuarios conectados y tiempo de conexión.

    Se intenta primero con `who` (el comando que exige explícitamente la
    sección 5 del enunciado). Si no reporta nada —posible en sistemas con
    sesiones gestionadas por systemd-logind en vez del utmp clásico— se
    recurre a `loginctl` y, como último recurso, a `w`.
    """
    for obtener in (_usuarios_via_who, _usuarios_via_loginctl, _usuarios_via_w):
        usuarios = obtener()
        if usuarios:
            return usuarios
    return []


def obtener_interfaces_red() -> list[dict]:
    """Interfaces de red y direcciones IPv4, vía `ip`."""
    salida = _ejecutar(["ip", "-o", "-4", "addr", "show"])

    patron = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\S+)")
    interfaces = []
    for linea in salida.strip().splitlines():
        coincidencia = patron.match(linea)
        if coincidencia:
            interfaces.append({
                "interfaz": coincidencia.group(1),
                "ip": coincidencia.group(2),
            })
    return interfaces


def obtener_trafico_red() -> dict:
    """Estadísticas de tráfico (bytes recibidos/enviados) por interfaz, desde /proc/net/dev."""
    try:
        with open("/proc/net/dev", "r") as f:
            lineas = f.readlines()[2:]
    except (FileNotFoundError, PermissionError, OSError) as error:
        raise RuntimeError(f"No se pudo leer /proc/net/dev: {error}") from error

    trafico = {}
    for linea in lineas:
        interfaz, _, resto = linea.partition(":")
        interfaz = interfaz.strip()
        campos = resto.split()
        if len(campos) < 9:
            continue
        trafico[interfaz] = {
            "rx_bytes": int(campos[0]),
            "tx_bytes": int(campos[8]),
        }
    return trafico


def obtener_red() -> list[dict]:
    """Combina interfaces/IPs (`ip`) con estadísticas de tráfico (/proc/net/dev)."""
    interfaces = obtener_interfaces_red()
    trafico = obtener_trafico_red()

    red = []
    for datos in interfaces:
        stats = trafico.get(datos["interfaz"], {"rx_bytes": 0, "tx_bytes": 0})
        red.append({**datos, **stats})
    return red


def obtener_trafico_total() -> dict:
    """Suma de bytes in/out de todas las interfaces reales (excluye loopback), para la BD."""
    trafico = obtener_trafico_red()
    rx_total = sum(v["rx_bytes"] for k, v in trafico.items() if k != "lo")
    tx_total = sum(v["tx_bytes"] for k, v in trafico.items() if k != "lo")
    return {"red_trafico_in": rx_total, "red_trafico_out": tx_total}


if __name__ == "__main__":
    print("Disco principal:", obtener_disco_principal())
    print("Procesos (primeros 5):", obtener_procesos()[:5])
    print("Usuarios:", obtener_usuarios())
    print("Red:", obtener_red())
    print("Tráfico total:", obtener_trafico_total())
