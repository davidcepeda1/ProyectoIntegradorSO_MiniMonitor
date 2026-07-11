# Manual de Ejecución

## Ejecutar el monitor

```bash
python3 -m src.main
```

El panel principal muestra en vivo CPU, Memoria (incluida Swap), Disco e
interfaces de Red con sus direcciones IP y tráfico. Los módulos de Procesos
y Usuarios se consultan bajo demanda (no se muestran en el panel principal
para no saturarlo) con las teclas `[P]` y `[U]`.

## Controles de la interfaz (TUI)

- `[C]` Crear captura del estado actual del sistema.
- `[V]` Visualizar historial de capturas almacenadas (permite ver el detalle completo de una captura por su ID).
- `[E]` Editar etiquetas de un registro del historial.
- `[D]` Eliminar un registro del historial.
- `[P]` Ver lista de procesos (PID, nombre, estado, usuario), con scroll.
- `[U]` Ver usuarios conectados y tiempo de conexión, con scroll.
- `[Q]` o `Ctrl+C` Salir de la aplicación.

Dentro de las vistas `[P]` y `[U]` (listas con posiblemente más filas de las
que caben en pantalla): `↑`/`↓` mueve una fila, `RePág`/`AvPág` mueve una
página completa, `Inicio`/`Fin` salta al principio/final de la lista, y una
barra de desplazamiento vertical en el borde derecho indica la posición
actual dentro del total (estilo btop). `[Q]` o `Enter` regresa al panel
principal.
