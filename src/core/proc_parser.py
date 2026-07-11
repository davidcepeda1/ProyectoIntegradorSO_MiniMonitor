"""Extracción de datos del sistema desde el sistema de archivos virtual /proc.

No depende de librerías externas (psutil, etc.): solo lectura y parseo
directo de /proc/cpuinfo, /proc/loadavg, /proc/meminfo y /proc/stat.

Blindaje: ninguna función pública de este módulo lanza excepciones hacia
arriba. Si un archivo de /proc no existe, no se puede leer (permisos) o
viene con un formato inesperado (truncado, vacío, kernel distinto), la
función atrapa el error y devuelve un diccionario con valores por defecto
en 0 / 0.0 en vez de propagar la excepción. Se usa 0 (no "N/D") porque
estos valores se usan en comparaciones y barras de uso en la TUI
(`cpu_uso > 80`, cálculos de porcentaje, etc.) — un string ahí rompería
esa aritmética con un TypeError.
"""

import time

CPU_INFO_VACIO = {"nucleos": 0, "frecuencia_mhz": 0.0}
LOADAVG_VACIO = {"carga_1min": 0.0, "carga_5min": 0.0, "carga_15min": 0.0}
MEMINFO_VACIO = {
    "ram_total_kb": 0,
    "ram_usada_kb": 0,
    "ram_libre_kb": 0,
    "swap_total_kb": 0,
    "swap_usada_kb": 0,
    "swap_libre_kb": 0,
}


def _leer_lineas(ruta: str) -> list[str] | None:
    """Lee un archivo de /proc. Devuelve None (en vez de lanzar) si no se
    puede leer, para que cada función decida su propio valor por defecto."""
    try:
        with open(ruta, "r") as f:
            return f.readlines()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def obtener_info_cpuinfo() -> dict:
    """Número de núcleos y frecuencia (MHz) promedio desde /proc/cpuinfo."""
    lineas = _leer_lineas("/proc/cpuinfo")
    if lineas is None:
        return dict(CPU_INFO_VACIO)

    nucleos = 0
    frecuencias = []
    for linea in lineas:
        if linea.startswith("processor"):
            nucleos += 1
        elif linea.startswith("cpu MHz"):
            try:
                valor = linea.split(":", 1)[1].strip()
                frecuencias.append(float(valor))
            except (IndexError, ValueError):
                continue  # linea con formato inesperado: se ignora, no se aborta el parseo completo

    frecuencia_promedio = sum(frecuencias) / len(frecuencias) if frecuencias else 0.0

    return {
        "nucleos": nucleos,
        "frecuencia_mhz": round(frecuencia_promedio, 2),
    }


def obtener_loadavg() -> dict:
    """Carga promedio del sistema (1, 5 y 15 minutos) desde /proc/loadavg."""
    lineas = _leer_lineas("/proc/loadavg")
    if not lineas:
        return dict(LOADAVG_VACIO)

    try:
        partes = lineas[0].split()
        return {
            "carga_1min": float(partes[0]),
            "carga_5min": float(partes[1]),
            "carga_15min": float(partes[2]),
        }
    except (IndexError, ValueError):
        return dict(LOADAVG_VACIO)


def _leer_jiffies_cpu() -> list[int] | None:
    lineas = _leer_lineas("/proc/stat")
    if not lineas or not lineas[0].startswith("cpu "):
        return None
    try:
        return [int(valor) for valor in lineas[0].split()[1:]]
    except ValueError:
        return None


def obtener_uso_cpu(intervalo: float = 0.1) -> float:
    """Porcentaje de utilización de CPU, calculado por delta de jiffies en /proc/stat."""
    muestra_inicial = _leer_jiffies_cpu()
    if muestra_inicial is None:
        return 0.0

    time.sleep(intervalo)
    muestra_final = _leer_jiffies_cpu()
    if muestra_final is None or len(muestra_final) != len(muestra_inicial) or len(muestra_final) < 5:
        return 0.0

    deltas = [final - inicial for inicial, final in zip(muestra_inicial, muestra_final)]
    total = sum(deltas)
    idle = deltas[3] + deltas[4]  # idle + iowait

    if total <= 0:
        return 0.0

    uso_porcentaje = (1 - idle / total) * 100
    return round(max(0.0, min(uso_porcentaje, 100.0)), 2)


def obtener_info_meminfo() -> dict:
    """Memoria RAM (total, usada, libre) y Swap desde /proc/meminfo, en KB."""
    lineas = _leer_lineas("/proc/meminfo")
    if lineas is None:
        return dict(MEMINFO_VACIO)

    valores = {}
    for linea in lineas:
        clave, separador, resto = linea.partition(":")
        if not separador:
            continue
        try:
            valores[clave.strip()] = int(resto.strip().split()[0])
        except (IndexError, ValueError):
            continue  # linea con formato inesperado: se ignora

    total = valores.get("MemTotal", 0)
    disponible = valores.get("MemAvailable", valores.get("MemFree", 0))
    usada = max(total - disponible, 0)

    swap_total = valores.get("SwapTotal", 0)
    swap_libre = valores.get("SwapFree", 0)
    swap_usada = max(swap_total - swap_libre, 0)

    return {
        "ram_total_kb": total,
        "ram_usada_kb": usada,
        "ram_libre_kb": disponible,
        "swap_total_kb": swap_total,
        "swap_usada_kb": swap_usada,
        "swap_libre_kb": swap_libre,
    }


def obtener_info_cpu(intervalo: float = 0.1) -> dict:
    """Combina núcleos, frecuencia, carga promedio y % de uso en un solo dict."""
    info = obtener_info_cpuinfo()
    info.update(obtener_loadavg())
    info["uso_porcentaje"] = obtener_uso_cpu(intervalo)
    return info


if __name__ == "__main__":
    print("CPU:", obtener_info_cpu())
    print("Memoria:", obtener_info_meminfo())
