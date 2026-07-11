"""Extracción de datos del sistema desde el sistema de archivos virtual /proc.

No depende de librerías externas (psutil, etc.): solo lectura y parseo
directo de /proc/cpuinfo, /proc/loadavg y /proc/meminfo.
"""

import time


def _leer_lineas(ruta: str) -> list[str]:
    try:
        with open(ruta, "r") as f:
            return f.readlines()
    except (FileNotFoundError, PermissionError, OSError) as error:
        raise RuntimeError(f"No se pudo leer {ruta}: {error}") from error


def obtener_info_cpuinfo() -> dict:
    """Número de núcleos y frecuencia (MHz) promedio desde /proc/cpuinfo."""
    lineas = _leer_lineas("/proc/cpuinfo")

    nucleos = 0
    frecuencias = []
    for linea in lineas:
        if linea.startswith("processor"):
            nucleos += 1
        elif linea.startswith("cpu MHz"):
            valor = linea.split(":", 1)[1].strip()
            frecuencias.append(float(valor))

    frecuencia_promedio = sum(frecuencias) / len(frecuencias) if frecuencias else 0.0

    return {
        "nucleos": nucleos,
        "frecuencia_mhz": round(frecuencia_promedio, 2),
    }


def obtener_loadavg() -> dict:
    """Carga promedio del sistema (1, 5 y 15 minutos) desde /proc/loadavg."""
    linea = _leer_lineas("/proc/loadavg")[0]
    partes = linea.split()

    return {
        "carga_1min": float(partes[0]),
        "carga_5min": float(partes[1]),
        "carga_15min": float(partes[2]),
    }


def _leer_jiffies_cpu() -> list[int]:
    linea = _leer_lineas("/proc/stat")[0]
    if not linea.startswith("cpu "):
        raise RuntimeError("Formato inesperado en /proc/stat")
    return [int(valor) for valor in linea.split()[1:]]


def obtener_uso_cpu(intervalo: float = 0.1) -> float:
    """Porcentaje de utilización de CPU, calculado por delta de jiffies en /proc/stat."""
    muestra_inicial = _leer_jiffies_cpu()
    time.sleep(intervalo)
    muestra_final = _leer_jiffies_cpu()

    deltas = [final - inicial for inicial, final in zip(muestra_inicial, muestra_final)]
    total = sum(deltas)
    idle = deltas[3] + deltas[4]  # idle + iowait

    if total <= 0:
        return 0.0

    uso_porcentaje = (1 - idle / total) * 100
    return round(uso_porcentaje, 2)


def obtener_info_meminfo() -> dict:
    """Memoria RAM (total, usada, libre) y Swap desde /proc/meminfo, en KB."""
    lineas = _leer_lineas("/proc/meminfo")

    valores = {}
    for linea in lineas:
        clave, _, resto = linea.partition(":")
        valores[clave.strip()] = int(resto.strip().split()[0])

    total = valores.get("MemTotal", 0)
    disponible = valores.get("MemAvailable", valores.get("MemFree", 0))
    usada = total - disponible

    swap_total = valores.get("SwapTotal", 0)
    swap_libre = valores.get("SwapFree", 0)
    swap_usada = swap_total - swap_libre

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
