# Manual de Instalación

## Requisitos
- Linux (Ubuntu Desktop, Ubuntu Server o equivalente)
- Python 3.10+
- Git

## Pasos

1. Clonar el repositorio:
   ```bash
   git clone <url-del-repositorio>
   cd MiniMonitorRecursos
   ```

2. Crear y activar un entorno virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Inicializar la base de datos:
   ```bash
   python3 -m src.database.db_manager
   ```
