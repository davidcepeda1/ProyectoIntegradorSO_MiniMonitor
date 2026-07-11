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


def obtener_usuarios() -> list[dict]:
    """Usuarios conectados y tiempo de conexión (calculado), vía `who`."""
    salida = _ejecutar(["who"])

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
