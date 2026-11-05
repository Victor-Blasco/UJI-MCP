# 🎓 Pack MCP: Aula Virtual UJI & Google Tasks

Conecta tu asistente de Inteligencia Artificial favorito (**Claude Desktop**, **Antigravity / Agy**, **OpenCode**, **Codex / VS Code**, **Cursor**, **Windsurf**) directamente con el **Aula Virtual de la Universitat Jaume I (Moodle)** y con **Google Tasks**.

---

## ⚡ ¿Qué te permite hacer desde tu IA?

* 📅 **Consultar entregas pendientes:** *"¿Qué prácticas tengo que entregar esta semana en el máster?"*
* 🔄 **Sincronizar con el móvil:** *"Sincroniza todas las entregas del Aula Virtual con mi Google Tasks"* (crea la lista `Aula Virtual UJI` con fechas exactas y links directos).
* 📥 **Descarga inteligente de materiales:** *"Descarga el notebook de Spark de Big Data"* (lo guarda en `01_Teoria/` o `02_Laboratorio/` de forma ordenada).
* 📢 **Revisar avisos de profesores:** *"¿Hay algún aviso nuevo en el foro de Computer Vision o Machine Learning?"*
* 📝 **Estado de entregas y notas:** *"Comprueba si ya he entregado la práctica 1 de SJK004 y si está calificada"*.

---

## 🚀 Instalación Rápida (1 Minuto)

### En Windows
Haz doble clic en **`conectar.bat`** (o ejecuta `python setup.py` en la terminal).

### En Mac / Linux
Abre la terminal en esta carpeta y ejecuta:
```bash
python3 setup.py
```

El asistente interactivo te guiará con este menú:
1. **Opción 1:** Instala las dependencias (`pip install -r requirements.txt`).
2. **Opción 2:** Conecta tu cuenta del Aula Virtual UJI (Login 1 clic en el navegador con la app oficial de Moodle; sin copiar cookies a mano).
3. **Opción 3 (Opcional):** Conecta Google Tasks si quieres sincronización con tu móvil.
4. **Opción 4:** Instala o fusiona automáticamente los MCPs en los clientes de IA que elijas (Claude, Antigravity, OpenCode, VS Code, Cursor).

---

## 🛠️ Configuración en Clientes de IA

Ejecutando `python setup.py --generate all` se crean las plantillas listas en la carpeta `configs/`.

---

### 1. Claude Desktop
Abre tu archivo de configuración de Claude:
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Pega o añade el bloque generado en `configs/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "uji-aulavirtual": {
      "command": "python",
      "args": ["RUTA_ABSOLUTA/aulavirtual_server.py"]
    },
    "google-tasks": {
      "command": "python",
      "args": ["RUTA_ABSOLUTA/gtasks_server.py"]
    }
  }
}
```

---

### 2. Antigravity (Agy)
En tu archivo global `~/.gemini/config/mcp_config.json` (o en `.agents/mcp_config.json`), añade:
```json
{
  "mcpServers": {
    "uji-aulavirtual": {
      "command": "python",
      "args": ["RUTA_ABSOLUTA/aulavirtual_server.py"]
    },
    "google-tasks": {
      "command": "python",
      "args": ["RUTA_ABSOLUTA/gtasks_server.py"]
    }
  }
}
```

---

### 3. OpenCode
En tu archivo de configuración `opencode.json` (o `.opencode/mcp.json`):
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "uji-aulavirtual": {
        "command": "python",
        "args": ["RUTA_ABSOLUTA/aulavirtual_server.py"]
      },
      "google-tasks": {
        "command": "python",
        "args": ["RUTA_ABSOLUTA/gtasks_server.py"]
      }
    }
  }
}
```

---

### 4. Codex / VS Code (Roo Code, Cline, GitHub Copilot Agent)
En la carpeta `.vscode/mcp.json` de tu espacio de trabajo:
```json
{
  "servers": {
    "uji-aulavirtual": {
      "command": "python",
      "args": ["RUTA_ABSOLUTA/aulavirtual_server.py"]
    },
    "google-tasks": {
      "command": "python",
      "args": ["RUTA_ABSOLUTA/gtasks_server.py"]
    }
  }
}
```

---

### 5. Cursor / Windsurf
El instalador (Opción 4) lo configura automáticamente en `~/.cursor/mcp.json`.
Si prefieres hacerlo manualmente en la UI, ve a **Settings > Features > MCP**, pulsa **Add new MCP server**:
* **Name:** `uji-aulavirtual`
* **Type:** `command`
* **Command:** `python RUTA_ABSOLUTA/aulavirtual_server.py`

---

## 💻 Uso directo por Terminal (Sin IA)

Si algún día no tienes la IA abierta y solo quieres una consulta rápida por terminal:

```bash
# Ver próximas entregas de todas las asignaturas
python aulavirtual_server.py deadlines

# Ver asignaturas matriculadas
python aulavirtual_server.py courses

# Ver notas del libro de calificaciones (global o por asignatura)
python aulavirtual_server.py grades --course SJK004

# Detectar materiales nuevos o modificados en Moodle
python aulavirtual_server.py new-materials --course SJK004

# Ver avisos y notificaciones de la campana
python aulavirtual_server.py notifications

# Sincronizar entregas pendientes con Google Tasks
python aulavirtual_server.py sync

# Crear una tarea rápida en Google Tasks
python gtasks_server.py add "Estudiar examen parcial" --due 2026-11-20
```

---

## 🔒 Privacidad y Seguridad
* **100% Local:** Ningún token ni contraseña sale de tu ordenador ni pasa por ningún servidor intermedio.
* **Token persistente:** Utiliza la API oficial de Web Services de Moodle Mobile de la UJI, evitando tener que repetir el login de 2FA continuamente.


---

## 🔍 Modo Debug y Diagnóstico

Si en algún momento necesitas ver las trazas de comunicación con el Aula Virtual o depurar una sincronización:
```bash
python setup.py --debug
# o directamente en el servidor:
python aulavirtual_server.py --debug --login
```
Esto habilitará el visor de logs en el menú y registrará las llamadas en `aulavirtual.log`.
