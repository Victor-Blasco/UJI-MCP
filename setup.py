#!/usr/bin/env python3
"""Asistente de configuración rápida e instalación del Pack MCP Aula Virtual UJI & Google Tasks.

Genera automáticamente los archivos de configuración para:
- Claude Desktop
- Antigravity (Agy)
- OpenCode
- Codex / VS Code (Roo Code, Cline, GitHub Copilot)
- Cursor / Windsurf
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable or "python"
AULAVIRTUAL_SCRIPT = BASE_DIR / "aulavirtual_server.py"
GTASKS_SCRIPT = BASE_DIR / "gtasks_server.py"


def format_path(p: Path) -> str:
    """Devuelve la ruta en formato estándar con barras inclinadas."""
    return str(p.resolve()).replace("\\", "/")


def generate_configs() -> dict[str, dict]:
    """Genera los diccionarios de configuración MCP para cada cliente."""
    aula_path = format_path(AULAVIRTUAL_SCRIPT)
    tasks_path = format_path(GTASKS_SCRIPT)
    py_path = format_path(Path(PYTHON_EXE))

    claude_agy_cursor = {
        "mcpServers": {
            "uji-aulavirtual": {
                "command": py_path,
                "args": [aula_path]
            },
            "google-tasks": {
                "command": py_path,
                "args": [tasks_path]
            }
        }
    }

    opencode = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "servers": {
                "uji-aulavirtual": {
                    "command": py_path,
                    "args": [aula_path]
                },
                "google-tasks": {
                    "command": py_path,
                    "args": [tasks_path]
                }
            }
        }
    }

    vscode_cline = {
        "servers": {
            "uji-aulavirtual": {
                "command": py_path,
                "args": [aula_path]
            },
            "google-tasks": {
                "command": py_path,
                "args": [tasks_path]
            }
        }
    }

    return {
        "claude": claude_agy_cursor,
        "agy": claude_agy_cursor,
        "opencode": opencode,
        "vscode": vscode_cline,
    }


def save_config_templates():
    """Guarda plantillas JSON en la carpeta configs/."""
    cfg_dir = BASE_DIR / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    configs = generate_configs()

    (cfg_dir / "claude_desktop_config.json").write_text(
        json.dumps(configs["claude"], indent=2), encoding="utf-8"
    )
    (cfg_dir / "agy_mcp_config.json").write_text(
        json.dumps(configs["agy"], indent=2), encoding="utf-8"
    )
    (cfg_dir / "opencode_mcp.json").write_text(
        json.dumps(configs["opencode"], indent=2), encoding="utf-8"
    )
    (cfg_dir / "vscode_mcp.json").write_text(
        json.dumps(configs["vscode"], indent=2), encoding="utf-8"
    )
    print(f"[OK] Archivos de configuración generados en: {cfg_dir}")


def install_requirements():
    """Instala las dependencias con pip."""
    req_file = BASE_DIR / "requirements.txt"
    print("\nInstalando dependencias necesarias...")
    subprocess.check_call([PYTHON_EXE, "-m", "pip", "install", "-r", str(req_file)])
    print("[OK] Dependencias instaladas con éxito.")


def connect_aulavirtual():
    """Ejecuta el asistente de conexión de Aula Virtual."""
    subprocess.check_call([PYTHON_EXE, str(AULAVIRTUAL_SCRIPT), "login"])


def connect_tasks():
    """Ejecuta el asistente de conexión de Google Tasks."""
    creds_file = BASE_DIR / "credentials.json"
    if not creds_file.exists():
        print(f"\n[AVISO] No se encontró 'credentials.json' en {BASE_DIR}")
        print("Para conectar Google Tasks, necesitas el archivo OAuth Desktop de Google Cloud.")
        print("Si no lo tienes, puedes seguir usando el MCP del Aula Virtual sin problemas.")
        resp = input("¿Tienes el archivo credentials.json para colocarlo ahora? (s/n): ").strip().lower()
        if resp != "s":
            return
    try:
        subprocess.check_call([PYTHON_EXE, str(GTASKS_SCRIPT), "auth"])
    except Exception as e:
        print(f"Error conectando Google Tasks: {e}")


def show_test_deadlines():
    """Muestra las entregas detectadas para verificar el funcionamiento."""
    try:
        subprocess.check_call([PYTHON_EXE, str(AULAVIRTUAL_SCRIPT), "deadlines"])
    except Exception as e:
        print(f"Error consultando entregas: {e}")


def show_logs():
    """Muestra el registro de trazabilidad."""
    try:
        subprocess.check_call([PYTHON_EXE, str(AULAVIRTUAL_SCRIPT), "logs", "-n", "60"])
    except Exception as e:
        print(f"Error leyendo logs: {e}")


def interactive_menu():
    print("=" * 65)
    print("   Pack MCP Aula Virtual UJI & Google Tasks - Configuración")
    print("=" * 65)
    print("1. Instalar dependencias (pip install -r requirements.txt)")
    print("2. Conectar tu cuenta de Aula Virtual UJI (Login)")
    print("3. Conectar tu cuenta de Google Tasks (Opcional)")
    print("4. Generar archivos de configuración MCP para tus clientes IA")
    print("5. Probar conexión (Ver próximas entregas del Máster)")
    print("6. Ver registro de trazabilidad / logs (aulavirtual.log)")
    print("7. Salir")
    print("=" * 65)

    while True:
        opt = input("\nElige una opción (1-7): ").strip()
        if opt == "1":
            install_requirements()
        elif opt == "2":
            connect_aulavirtual()
        elif opt == "3":
            connect_tasks()
        elif opt == "4":
            save_config_templates()
            print("\nPara tu cliente:")
            print("👉 Claude Desktop : Copia configs/claude_desktop_config.json a %APPDATA%/Claude/claude_desktop_config.json")
            print("👉 Antigravity (Agy): Copia el contenido a ~/.gemini/config/mcp_config.json")
            print("👉 OpenCode       : Copia configs/opencode_mcp.json a tu opencode.json")
            print("👉 VS Code / Codex: Copia configs/vscode_mcp.json a .vscode/mcp.json")
        elif opt == "5":
            show_test_deadlines()
        elif opt == "6":
            show_logs()
        elif opt == "7":
            print("¡Listo! Que aproveches el cuatrimestre.")
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configurador MCP UJI")
    parser.add_argument("--generate", choices=["claude", "agy", "opencode", "vscode", "all"], help="Genera configuración directa")
    args = parser.parse_args()

    if args.generate:
        save_config_templates()
        configs = generate_configs()
        if args.generate in configs:
            print(json.dumps(configs[args.generate], indent=2))
        else:
            print(json.dumps(configs, indent=2))
    else:
        interactive_menu()
