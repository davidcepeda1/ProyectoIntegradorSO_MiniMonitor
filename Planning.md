# 🚀 Plan de Trabajo Técnico: Mini Monitor de Recursos Linux

Este documento establece la estrategia de desarrollo ágil y los prompts de IA optimizados para la construcción del **Mini Monitor de Recursos**. Toda la codificación aquí planificada responde estrictamente a la especificación oficial detallada en el archivo `ProyectoIntegradorSO.md`.

---

## 🔗 1. Alineación con Requerimientos Oficiales

Para asegurar la máxima nota y cubrir los criterios de evaluación del docente, este plan se acopla directamente a las secciones de `ProyectoIntegradorSO.md`:
* [cite_start]**Módulos de Monitoreo:** Cumple con la extracción de datos de CPU, Memoria, Procesos, Usuarios, Disco y Red[cite: 34, 35, 39, 44, 49, 52, 56].
* [cite_start]**Concurrencia y Kernel:** Implementación mandatoria de `/proc`, `os.fork()`, `threading.Thread()` y llamadas de comandos[cite: 61, 62, 68, 71, 74].
* [cite_start]**Persistencia Integrada:** Arquitectura CRUD completa utilizando SQLite enfocado en el sistema dinámico de **Etiquetas (Tags)**[cite: 85, 86, 96].

---

## 📅 2. Cronograma de Desarrollo Semanal y Prompts de IA

[cite_start]A continuación se detalla el plan de acción por semanas[cite: 116]. Cada bloque incluye el **Prompt de Contexto Completo** óptimo para alimentar a la IA y generar el código correspondiente.

### [cite_start]📊 Semana 1: Diseño de Arquitectura y Base de Datos (Fase Actual) [cite: 117]
* [cite_start]**Objetivos:** Inicialización del repositorio, definición del esquema de carpetas y despliegue del modelo relacional[cite: 118, 120, 121].
* **Enfoque Creativo:** Interfaz avanzada en Terminal (TUI) tipo `htop` y uso de SQLite para un CRUD ágil con soporte para múltiples tags desde la creación.

#### 🤖 Prompt Semana 1 (Corregido para Sistema de Tags):
> **Rol:** Eres un Ingeniero de Software experto en Linux y Sistemas Operativos.
> **Contexto:** Estoy desarrollando el Mini Monitor de Recursos en Python 3 detallado en `ProyectoIntegradorSO.md`. El sistema debe estar estrictamente modularizado y usará un sistema avanzado de etiquetas (tags) para clasificar los reportes.
> **Tarea:** Genera el script inicial de la base de datos en Python (`src/database/db_manager.py`) utilizando `sqlite3`. Diseña una tabla llamada `capturas` que almacene: `id` (autoincremental), `fecha_hora`, `cpu_uso` (REAL), `ram_total`, `ram_usada`, `disco_total`, `disco_usada`, `red_trafico_in`, `red_trafico_out` (todos INTEGER) y una columna `etiquetas` (TEXT). Asegura que el código incluya la lógica para insertar registros permitiendo pasar una lista de strings (ej. `['CRÍTICO', 'RAM']`) que se guarden como una sola cadena separada por comas (`"CRÍTICO, RAM"`), y que por defecto guarde `['GENERAL']` si viene vacía. Incluye las funciones básicas para inicializar la base de datos.

---

### [cite_start]💻 Semana 2: Monitoreo Esencial (CPU, RAM y /proc) [cite: 122]
* [cite_start]**Objetivos:** Lectura directa y parseo de datos desde el sistema de archivos virtual `/proc`[cite: 125].
* [cite_start]**Requerimientos:** Módulos de CPU y Memoria[cite: 123, 124].

#### 🤖 Prompt Semana 2:
> **Rol:** Experto en Kernel de Linux y Python.
> [cite_start]**Contexto:** Continuando con el proyecto del Mini Monitor descrito en `ProyectoIntegradorSO.md`, necesito el módulo de extracción de datos del sistema de archivos virtual `/proc`[cite: 62].
> **Tarea:** Escribe el código para `src/core/proc_parser.py`. Debe contener funciones puras en Python para abrir, leer y limpiar (parsear) los archivos nativos:
> [cite_start]1. `/proc/cpuinfo` y `/proc/loadavg` para obtener: número de núcleos, frecuencia y porcentaje de utilización actual de la CPU[cite: 64, 67].
> [cite_start]2. `/proc/meminfo` para obtener: Memoria RAM total, utilizada, libre y memoria Swap[cite: 65].
> No uses librerías externas como `psutil`. Devuelve la información en diccionarios limpios de Python. Incluye manejo de excepciones si los archivos no existen o no se pueden leer.

* **Nota de diseño (implementada):** `/proc/loadavg` reporta la *carga promedio* (cola de procesos esperando CPU), no un porcentaje de uso — puede superar 100 fácilmente y no equivale a "% de utilización". Se mantiene como métrica informativa (cumple el requisito de usar el archivo), pero el **% de uso de CPU real** se calcula con el método estándar de SO: leer `/proc/stat` dos veces con un pequeño intervalo (`time.sleep`) y calcular `(1 - delta_idle / delta_total) * 100` sobre los jiffies acumulados.

---

### [cite_start]🛜 Semana 3: Módulos Complementarios (Disco, Red, Usuarios y Procesos) [cite: 127, 129]
* [cite_start]**Objetivos:** Implementar extracción de almacenamiento, interfaces de red, usuarios activos y lista de procesos[cite: 127, 128, 129].
* [cite_start]**Requerimientos:** Módulos de Procesos, Usuarios, Disco y Red mediante comandos nativos ejecutados con `subprocess`[cite: 74, 78].

#### 🤖 Prompt Semana 3:
> **Rol:** Administrador de Sistemas Linux y Desarrollador Python.
> **Contexto:** Tengo el sistema de base de datos y los parsers de CPU/RAM de mi proyecto basado en `ProyectoIntegradorSO.md`. [cite_start]Ahora necesito mapear el resto de recursos del sistema mediante comandos de Linux utilizando la librería `subprocess` de Python[cite: 78].
> **Tarea:** Desarrolla el archivo `src/core/cmd_runner.py` que ejecute comandos del sistema operativo y procese sus salidas de texto para extraer:
> [cite_start]1. **Módulo Disco:** Espacio total, utilizado y libre mediante el comando `df`[cite: 82].
> [cite_start]2. **Módulo Procesos:** PID, Nombre, Estado y Usuario propietario ejecutando `ps`[cite: 80].
> [cite_start]3. **Módulo Usuarios:** Usuarios conectados y tiempo de conexión usando `who`[cite: 81].
> [cite_start]4. **Módulo Red:** Interfaces, IPs y estadísticas básicas usando `ip` o leyendo `/proc/net/dev`[cite: 66, 84].
> Asegúrate de limpiar las cadenas de texto (`stdout.decode()`) y estructurar los retornos como listas de diccionarios.

* **Nota de diseño (implementada):** Para el Módulo Red se combinaron dos fuentes: el comando `ip -o -4 addr show` (subprocess) para listar interfaces y direcciones IP —cumple el requisito de ejecución de comandos Linux—, y `/proc/net/dev` para los contadores de tráfico (bytes recibidos/enviados), ya que su formato de texto fijo es mucho más estable de parsear que la salida human-readable de `ip -s link`. Para el Módulo Usuarios, `who` solo reporta la hora de login; se calculó la duración de la sesión (`ahora - login`) para que "tiempo de conexión" sea un dato real y no solo un timestamp. Todos los comandos se ejecutan con `subprocess.run(lista_de_args, ...)` sin `shell=True`, evitando inyección de comandos.

---

### [cite_start]🔀 Semana 4: Concurrencia Avanzada (Fork, Hilos y CRUD Completo) [cite: 131, 132, 133]
* [cite_start]**Objetivos:** Implementar la arquitectura de procesos, hilos y persistencia histórica[cite: 131, 132, 133].
* [cite_start]**Requerimientos:** Al menos 1 proceso hijo con `os.fork()`, 2 hilos con `threading.Thread()` y operaciones CRUD avanzadas con tags[cite: 70, 73, 85, 86].
* **Nota de diseño (revisada):** No dividimos la aplicación completa con `fork()`. `curses`/`blessed` requiere control único de la terminal, así que tener un padre-TUI y un hijo-DB corriendo en paralelo arriesga corrupción de pantalla y obliga a montar IPC (pipe/`multiprocessing.Queue`) solo para eso. En su lugar, `fork()` se usa de forma acotada: el **proceso padre** mantiene el control exclusivo de la TUI y de los hilos en tiempo real; el **proceso hijo** se lanza puntualmente (p. ej. al presionar `[C]` Crear captura) para ejecutar en paralelo los comandos "pesados" (`ps`, `df`, `who`) y devolver el resultado al padre por un `os.pipe()`, que luego lo persiste en SQLite. Esto sigue cumpliendo el requisito de "al menos un proceso hijo mediante `os.fork()`" con menor riesgo técnico y sin duplicar el manejo de la terminal.
* **Nota de diseño (señales):** En Python las señales solo se capturan de forma confiable en el hilo principal (`signal.signal` no funciona en hilos secundarios). El manejo de `SIGINT`/salida limpia se hace en el hilo principal; el Hilo B se dedica exclusivamente a detectar picos de tráfico de red comparando deltas entre lecturas de `/proc/net/dev`.
* **Nota de diseño (implementada — fork en proceso multihilo):** `os.fork()` en un proceso con varios hilos activos solo clona el hilo que lo invoca; los hilos A y B **no existen** en el proceso hijo. Por eso `_proceso_hijo_captura()` (en `src/main.py`) nunca toca el lock ni el estado compartido `EstadoMonitor` — únicamente ejecuta comandos (`df`, `who`) y escribe el resultado en el pipe antes de terminar con `os._exit()`. El padre combina ese resultado con las métricas de CPU/RAM ya calculadas por el Hilo A y persiste la captura en SQLite. Vale la pena mencionar este detalle en la sustentación como evidencia de comprensión de concurrencia en SO.

#### 🤖 Prompt Semana 4:
> **Rol:** Arquitecto de Software experto en Concurrencia en Sistemas Operativos.
> **Contexto:** Tengo listos los parsers y la base de datos de mi Mini Monitor Linux según los requerimientos de `ProyectoIntegradorSO.md`. [cite_start]Ahora implementaremos el core concurrente en `src/main.py` y completaremos el CRUD en `src/database/db_manager.py`[cite: 133].
> **Tarea:** Escribe la estructura concurrente del programa respetando lo siguiente:
> 1. El **proceso principal** mantiene el control exclusivo de la interfaz de usuario en terminal (TUI) y del manejo de señales (`SIGINT` para salida limpia). [cite_start]Cuando el usuario dispare una captura (tecla `[C]`), usa `os.fork()` para lanzar un **proceso hijo** que ejecute en paralelo los comandos pesados del sistema (`ps`, `df`, `who`)[cite: 70], comunique el resultado al padre mediante un `os.pipe()`, y termine (`os._exit`). El padre recibe los datos por el pipe y los persiste en SQLite sin bloquear la TUI.
> [cite_start]2. Dentro del proceso principal, implementa **dos hilos concurrentes** usando `threading.Thread()`[cite: 73]: El **Hilo A** actualizará las métricas en tiempo real (CPU/RAM) cada segundo y el **Hilo B** comparará deltas de `/proc/net/dev` para detectar picos de tráfico de red y marcarlos en la interfaz. Ninguno de los dos hilos maneja señales del sistema.
> [cite_start]3. Completa el CRUD con soporte para el sistema de Etiquetas (Tags): una función para Crear una captura (Create), Consultar listados filtrando por etiqueta usando el operador `LIKE` de SQL (Read), Actualizar modificando exclusivamente las etiquetas de una captura existente (Update), y Eliminar registros por ID (Delete)[cite: 86].

---

### [cite_start]🎨 Semana 5: Integración de Interfaz TUI, Pruebas y Entregables [cite: 135, 136, 141]
* [cite_start]**Objetivos:** Ensamblaje de la interfaz visual en terminal, pruebas finales y consolidación de documentación de entrega[cite: 135, 136, 141].

#### 🤖 Prompt Semana 5:
> **Rol:** Diseñador UX/UI de Terminal (TUI) y Desarrollador Python Senior.
> **Contexto:** Todo el backend concurrente y de datos funciona según la especificación de `ProyectoIntegradorSO.md`. Necesito la capa visual interactiva (`src/ui/tui.py`) para emular un entorno profesional estilo `htop`.
> **Tarea:** Genera el código para la interfaz interactiva usando la librería estándar `curses` o `blessed`. Debe mostrar paneles divididos en colores para CPU, RAM, Procesos, Disco y Red. Debe incluir un menú inferior donde el usuario pueda presionar teclas específicas para: [C] Crear captura, [V] Visualizar historial, [E] Editar etiquetas de un registro del historial, y [D] Eliminar un registro. Asegura que la pantalla se refresque de manera limpia sin parpadeos molestos (flickering) mediante hilos independientes.

* **Nota de diseño (implementada — curses en vez de blessed):** Se eligió `curses` (biblioteca estándar) sobre `blessed` para no depender de `pip install` en el entorno de evaluación. `curses.wrapper()` garantiza que la terminal se restaure correctamente incluso ante una excepción no controlada, y el redibujado usa `noutrefresh()` + `doupdate()` para minimizar parpadeo. El hilo principal es el único que controla la pantalla (curses no es thread-safe); los Hilos A/B solo escriben en `EstadoMonitor` bajo lock. El manejador de `SIGINT` ya no imprime nada directamente (corrompería la pantalla de curses): solo señaliza la salida, y el mensaje final se imprime después de que `curses.wrapper()` restaura la terminal. Verificado end-to-end en una pseudo-terminal real (`pty.fork`): renderizado de paneles con datos reales, y los cuatro flujos CRUD (`[C]`, `[V]`, `[E]`, `[D]`) confirmados contra la base de datos.
* **Corrección de UX (post-entrega, reportada por el usuario):** Los diálogos de entrada de texto (`_leer_texto`, usados por `[C]`, `[E]`, `[D]`, filtro de `[V]`) heredaban el modo no-bloqueante con timeout de 1s que el bucle principal usa para refrescar los paneles — `nodelay`/`timeout` son atributos de la ventana, no se resetean solos entre llamadas. Resultado: si el usuario tardaba más de un segundo en escribir o hacía una pausa entre teclas, la captura de texto se cortaba sola, dando "ID inválido" o saliendo del modo edición sin aviso. Se corrigió forzando `stdscr.nodelay(False)` + `stdscr.timeout(-1)` (bloqueo real, sin límite) antes de cada `getstr()`, restaurando el modo original del bucle principal al terminar. Además, `[V]` Ver historial ahora permite entrar el ID de una fila para ver el detalle completo de esa captura (antes solo mostraba la tabla resumida), ya que era difícil "hacer algo" con una captura recién creada más allá de verla truncada en una tabla.

---

## 📂 3. Arquitectura del Repositorio de Código

Estructura modular limpia que mapea los componentes solicitados en la solución:

```text
mini_monitor_so/
│
├── ProyectoIntegradorSO.md # Requerimientos oficiales del proyecto
├── Planning.md             # Este archivo (Guía de desarrollo y Prompts)
│
├── src/
│   ├── __init__.py
│   ├── main.py            # Orquestador del programa (os.fork e hilos)
│   │
│   ├── core/              # Módulo de extracción de datos del S.O.
│   │   ├── __init__.py
│   │   ├── proc_parser.py # Extractor de /proc/cpuinfo, meminfo, net/dev
│   │   └── cmd_runner.py  # Ejecutor de comandos (df, ps, who) via subprocess
│   │
│   ├── database/          # Persistencia de datos (CRUD)
│   │   ├── __init__.py
│   │   └── db_manager.py  # Conexión a SQLite y funciones Create, Read, Update, Delete
│   │
│   └── ui/                # Renderizado visual
│       ├── __init__.py
│       └── tui.py         # Interfaz interactiva de terminal con menús de comandos
│
├── docs/                  # Manuales solicitados en la Sección 9 de los entregables
│   ├── manual_instalacion.md
│   └── manual_ejecucion.md
│
├── requirements.txt       # Librerías necesarias (ej. blessed)
└── .gitignore             # Exclusión de entornos virtuales y bases de datos locales (.db)