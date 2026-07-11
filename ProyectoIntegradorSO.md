**CARRERA DE INGENIERÍA DE SOFTWARE**

**SISTEMAS OPERATIVOS**

**PROYECTO INTEGRADOR.**

### Título del Proyecto:

**Desarrollo de un Mini Monitor de Recursos para Linux utilizando Python**

### Duración

5 semanas a partir de la fecha de asignación.

### Modalidad

Trabajo grupal.

- Mínimo: 2 estudiantes.
- Máximo: 3 estudiantes.

### Herramientas Obligatorias

- Linux (Ubuntu Desktop, Ubuntu Server o distribución equivalente)
- Visual Studio Code (VSC)
- Python 3
- Git y GitHub (recomendado)
- SQLite, PostgreSQL o archivos JSON para almacenamiento

# **1. Introducción**

Los sistemas operativos modernos proporcionan mecanismos para monitorear el estado y utilización de los recursos computacionales. El acceso a esta información permite administrar de forma eficiente la CPU, memoria, procesos, almacenamiento y red.

En este proyecto, los estudiantes deberán desarrollar una aplicación de monitoreo para Linux que integre conceptos fundamentales de Sistemas Operativos estudiados durante el semestre, incluyendo procesos, hilos, ejecución concurrente y administración de recursos.

# **2. Objetivo General**

Diseñar e implementar un Mini Monitor de Recursos para Linux que permita visualizar información del sistema operativo y administrar registros mediante operaciones CRUD, utilizando Python y Visual Studio Code.

# 3. Objetivos Específicos

- Analizar la estructura de monitoreo de recursos en Linux.
- Obtener información del sistema mediante el sistema de archivos virtual /proc.
- Implementar procesos concurrentes utilizando fork().
- Implementar hilos utilizando threading.
- Ejecutar comandos Linux mediante llamadas al sistema.
- Diseñar e implementar operaciones CRUD para almacenar registros de monitoreo.
- Elaborar un artículo científico basado en los resultados obtenidos.
- Presentar y defender técnicamente la solución desarrollada.

# **4. Requerimientos Funcionales**

La aplicación deberá mostrar como mínimo:

## Módulo CPU

- Número de núcleos.
- Frecuencia del procesador.
- Porcentaje de utilización.

## Módulo Memoria

- Memoria total.
- Memoria utilizada.
- Memoria libre.
- Memoria Swap.

## Módulo Procesos

- PID.
- Nombre del proceso.
- Estado.
- Usuario propietario.

## Módulo Usuarios

- Usuarios conectados.
- Tiempo de conexión.

## Módulo Disco

- Espacio total.
- Espacio utilizado.
- Espacio libre.

## Módulo Red

- Interfaces de red.
- Direcciones IP.
- Estadísticas básicas de tráfico.

# **5. Requerimientos Técnicos Obligatorios**

La solución deberá utilizar obligatoriamente:

## Sistema de archivos /proc

Por ejemplo:

- /proc/cpuinfo
- /proc/meminfo
- /proc/net/dev
- /proc/loadavg

## Procesos

Implementar al menos un proceso hijo mediante:

os.fork()

## Hilos

Implementar al menos dos hilos concurrentes utilizando:

threading.Thread()

## Ejecución de comandos Linux

Utilizar comandos del sistema mediante:

os.system()

o

subprocess

Ejemplos:

- ps
- who
- df
- free
- ip

# **6. CRUD Obligatorio**

La aplicación deberá permitir:

## Crear

Registrar una captura del estado del sistema.

## Consultar

Visualizar monitoreos previamente almacenados.

## Actualizar

Modificar comentarios o etiquetas asociadas a los monitoreos.

## Eliminar

Eliminar registros almacenados.

Los datos podrán almacenarse en:

- SQLite
- PostgreSQL
- JSON

# **7. Arquitectura Referencial**

        [ Usuario ]
            |
            v
    [Interfaz Python]
            |
    +---------+---------+
    |    |    |    |    |
    v    v    v    v    v
    CPU  RAM  Proc Disco Red
    |    |    |    |    |
    +---------+---------+
        |
        v
    [ Base de Datos ]
            |
            v
        [ CRUD ]

# **8. Cronograma de Trabajo**

## Semana 1

- Formación de grupos.
- Análisis de requerimientos.
- Diseño de arquitectura.
- Diseño de base de datos.

## Semana 2

- Implementación de CPU.
- Implementación de RAM.
- Lectura desde /proc.

## Semana 3

- Implementación de Disco.
- Implementación de Red.
- Implementación de Usuarios y Procesos.

## Semana 4

- Implementación de fork().
- Implementación de hilos.
- Desarrollo del CRUD.

## Semana 5

- Integración final.
- Pruebas.
- Correcciones.
- Elaboración del artículo.
- Elaboración de presentación.
- Grabación del video.

# **9. Entregables**

## 1. Código Fuente en su Git-Hub

Debe incluir:

- Código completo.
- Comentarios.
- Manual de instalación.
- Manual de ejecución.

## 2. Artículo Científico IEEE

Extensión:

- Entre 4 y 6 páginas.

Contenido mínimo:

- Título.
- Autores.
- Resumen.
- Palabras clave.
- Introducción.
- Metodología.
- Desarrollo.
- Resultados.
- Conclusiones.
- Referencias bibliográficas.

## 3. Video Demostrativo

Duración:

- Entre 5 y 10 minutos formato horizontal, 4K, HD..

Debe mostrar:

- Funcionamiento completo.
- Monitoreo de recursos.
- Operaciones CRUD.
- Uso de procesos e hilos.

## 4. Presentación

Máximo:

- 10 diapositivas, todo el grupo, de manera presencial.

Contenido sugerido:

1. Portada.
2. Problema.
3. Objetivos.
4. Arquitectura.
5. Tecnologías utilizadas.
6. Desarrollo.
7. Resultados.
8. Evidencias.
9. Conclusiones.
10. Preguntas.

# **10. Sustentación**

Cada grupo dispondrá de:

- 10 minutos de exposición.

Distribución sugerida:

- 7 minutos de presentación.
- 3 minutos de preguntas.

Todos los integrantes deberán participar activamente.

## **11. Fecha de Entrega**

Todos los entregables deberán presentarse el último día de clases de la asignatura, de acuerdo con el cronograma académico establecido.

### Observación

Se valorará especialmente la originalidad de la solución, la correcta aplicación de los conceptos de Sistemas Operativos y la calidad técnica del software desarrollado.
