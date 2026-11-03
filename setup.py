#!/usr/bin/env python3
"""Asistente de configuración rápida e instalación del Pack MCP Aula Virtual UJI & Google Tasks.

Soporta instalación directa (merge seguro) y generación de plantillas para:
1. Claude Desktop
2. Antigravity (Agy)
3. OpenCode
4. Codex / VS Code (Roo Code, Cline, GitHub Copilot)
5. Cursor
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable or "python"
AULAVIRTUAL_SCRIPT = BASE_DIR / "aulavirtual_server.py"
GTASKS_SCRIPT = BASE_DIR / "gtasks_server.py"

DEBUG_MODE = False


def format_path(p: Path) -> str:
    """Devuelve la ruta en formato estándar con barras inclinadas."""
    return str(p.resolve()).replace("\\", "/")


def _get_server_entries(use_placeholders: bool = False) -> dict[str, dict[str, Any]]:
    """Devuelve las definiciones de servidores MCP con rutas reales o placeholders."""
    if use_placeholders:
        py_path = "python"
        aula_path = "<RUTA_A_UJI_MCP>/aulavirtual_server.py"
        tasks_path = "<RUTA_A_UJI_MCP>/gtasks_server.py"
    else:
        py_path = format_path(Path(PYTHON_EXE))
        aula_path = format_path(AULAVIRTUAL_SCRIPT)
        tasks_path = format_path(GTASKS_SCRIPT)

    return {
        "uji-aulavirtual": {
            "command": py_path,
            "args": [aula_path],
        },
        "google-tasks": {
            "command": py_path,
            "args": [tasks_path],
        },
    }


def generate_configs(use_placeholders: bool = False) -> dict[str, dict[str, Any]]:
    """Genera los diccionarios de configuración MCP para cada cliente."""
    servers = _get_server_entries(use_placeholders=use_placeholders)

    claude_agy_cursor = {"mcpServers": dict(servers)}
    opencode = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"servers": dict(servers)},
    }
    vscode_cline = {"servers": dict(servers)}

    return {
        "claude": claude_agy_cursor,
        "agy": claude_agy_cursor,
        "opencode": opencode,
        "vscode": vscode_cline,
        "cursor": claude_agy_cursor,
    }


def _get_client_target_paths() -> dict[str, tuple[str, Path, Path]]:
    """Devuelve para cada cliente: (Nombre legible, Ruta real del cliente, Ruta en configs/)."""
    home = Path.home()
    cfg_dir = BASE_DIR / "configs"

    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        claude_path = appdata / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        claude_path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        claude_path = home / ".config" / "Claude" / "claude_desktop_config.json"

    agy_path = home / ".gemini" / "config" / "mcp_config.json"
    opencode_path = home / ".config" / "opencode" / "opencode.json"
    vscode_path = BASE_DIR.parent / ".vscode" / "mcp.json" if (BASE_DIR.parent / ".vscode").exists() else BASE_DIR / ".vscode" / "mcp.json"
    cursor_path = home / ".cursor" / "mcp.json"

    return {
        "claude": ("Claude Desktop", claude_path, cfg_dir / "claude_desktop_config.json"),
        "agy": ("Antigravity (Agy)", agy_path, cfg_dir / "agy_mcp_config.json"),
        "opencode": ("OpenCode", opencode_path, cfg_dir / "opencode_mcp.json"),
        "vscode": ("Codex / VS Code", vscode_path, cfg_dir / "vscode_mcp.json"),
        "cursor": ("Cursor", cursor_path, cfg_dir / "cursor_mcp.json"),
    }


def _merge_and_write_config(client_key: str, target_path: Path, servers: dict[str, Any]) -> None:
    """Fusiona los MCPs en el archivo de configuración del cliente sin borrar otros servidores existentes."""
    existing: dict[str, Any] = {}
    if target_path.exists():
        try:
            raw = target_path.read_text(encoding="utf-8").strip()
            if raw:
                existing = json.loads(raw)
        except Exception:
            existing = {}

    if client_key == "opencode":
        existing.setdefault("$schema", "https://opencode.ai/config.json")
        mcp_block = existing.setdefault("mcp", {})
        srv_block = mcp_block.setdefault("servers", {})
        srv_block.update(servers)
    elif client_key == "vscode":
        srv_block = existing.setdefault("servers", {})
        srv_block.update(servers)
    else:
        srv_block = existing.setdefault("mcpServers", {})
        srv_block.update(servers)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def install_selected_clients(selected_keys: list[str]) -> None:
    """Instala (haciendo merge seguro) los MCPs únicamente en los clientes seleccionados."""
    servers = _get_server_entries(use_placeholders=False)
    targets = _get_client_target_paths()

    print("")
    for key in selected_keys:
        if key not in targets:
            continue
        label, real_path, local_template_path = targets[key]
        try:
            _merge_and_write_config(key, real_path, servers)
            print(f"  [OK] {label:<18} -> Configurado en: {real_path}")
        except Exception as exc:
            print(f"  [!]  {label:<18} -> Error al configurar en {real_path}: {exc}")
            print(f"       Puedes copiar la plantilla de: {local_template_path}")


def choose_and_install_clients_menu() -> None:
    """Submenú interactivo para elegir en qué clientes instalar los MCPs (permite selección múltiple)."""
    targets = _get_client_target_paths()
    option_map = {
        "1": "claude",
        "2": "agy",
        "3": "opencode",
        "4": "vscode",
        "5": "cursor",
    }

    print("\n" + "-" * 65)
    print("  ¿En qué clientes de IA quieres instalar los MCPs?")
    print("-" * 65)
    for num, key in option_map.items():
        label, real_path, _ = targets[key]
        print(f"  {num}. {label:<20} ({real_path})")
    print("  6. Todos los anteriores")
    print("  0. Cancelar y volver al menú principal")
    print("-" * 65)

    choice = input("Elige uno o varios números separados por comas o espacios (ej. 1, 2, 4): ").strip()
    if not choice or choice == "0":
        return

    tokens = [t.strip() for t in re.split(r"[,\s]+", choice) if t.strip()]
    if "6" in tokens or "all" in tokens:
        selected = list(option_map.values())
    else:
        selected = []
        for t in tokens:
            if t in option_map and option_map[t] not in selected:
                selected.append(option_map[t])

    if not selected:
        print("[!] No se seleccionó ningún cliente válido.")
        return

    install_selected_clients(selected)


def _subproc_cmd(script: Path, *extra_args: str) -> list[str]:
    cmd = [PYTHON_EXE, str(script)]
    if DEBUG_MODE:
        cmd.append("--debug")
    cmd.extend(extra_args)
    return cmd


def install_requirements() -> None:
    """Instala las dependencias con pip."""
    req_file = BASE_DIR / "requirements.txt"
    print("\nInstalando dependencias necesarias...")
    subprocess.check_call([PYTHON_EXE, "-m", "pip", "install", "-r", str(req_file)])
    print("[OK] Dependencias instaladas con éxito.")


def connect_aulavirtual() -> None:
    """Ejecuta el asistente de conexión de Aula Virtual."""
    subprocess.check_call(_subproc_cmd(AULAVIRTUAL_SCRIPT, "login"))


def connect_tasks() -> None:
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


def show_test_deadlines() -> None:
    """Muestra las entregas detectadas para verificar el funcionamiento."""
    try:
        subprocess.check_call(_subproc_cmd(AULAVIRTUAL_SCRIPT, "deadlines"))
    except Exception as e:
        print(f"Error consultando entregas: {e}")


def show_logs() -> None:
    """Muestra el registro de trazabilidad."""
    try:
        subprocess.check_call(_subproc_cmd(AULAVIRTUAL_SCRIPT, "logs", "-n", "60"))
    except Exception as e:
        print(f"Error leyendo logs: {e}")


def print_main_menu() -> None:
    """Imprime las opciones disponibles del menú principal."""
    debug_tag = " [MODO DEBUG ACTIVO]" if DEBUG_MODE else ""
    print("\n" + "=" * 65)
    print(f"   Pack MCP Aula Virtual UJI & Google Tasks{debug_tag}")
    print("=" * 65)
    print("  1. Instalar dependencias (pip install -r requirements.txt)")
    print("  2. Conectar tu cuenta de Aula Virtual UJI (Login 1 clic)")
    print("  3. Conectar tu cuenta de Google Tasks (Opcional)")
    print("  4. Instalar / Configurar MCPs en tus clientes de IA (Claude, Agy, OpenCode, VS Code, Cursor)")
    print("  5. Probar conexión (Ver próximas entregas del Aula Virtual)")
    if DEBUG_MODE:
        print("  6. Ver registro de trazabilidad / logs (aulavirtual.log)")
        print("  0. Salir")
    else:
        print("  0. Salir")
    print("=" * 65)


def interactive_menu() -> None:
    while True:
        print_main_menu()
        prompt = "Elige una opción (0-6): " if DEBUG_MODE else "Elige una opción (0-5): "
        opt = input(prompt).strip()
        if opt == "1":
            install_requirements()
        elif opt == "2":
            connect_aulavirtual()
        elif opt == "3":
            connect_tasks()
        elif opt == "4":
            choose_and_install_clients_menu()
        elif opt == "5":
            show_test_deadlines()
        elif opt == "6" and DEBUG_MODE:
            show_logs()
        elif opt in ("0", "salir", "exit", "q"):
            print("¡Listo! Que aproveches el cuatrimestre.")
            break
        else:
            print("[!] Opción inválida. Por favor, elige un número del menú.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configurador MCP UJI")
    parser.add_argument("--debug", action="store_true", help="Activa el modo de trazabilidad (logs detallados)")
    parser.add_argument(
        "--generate",
        nargs="+",
        choices=["claude", "agy", "opencode", "vscode", "cursor", "all"],
        help="Instala/genera configuración para uno o varios clientes",
    )
    args = parser.parse_args()

    if args.debug:
        DEBUG_MODE = True
        os.environ["MOODLE_DEBUG"] = "1"

    if args.generate:
        keys = ["claude", "agy", "opencode", "vscode", "cursor"] if "all" in args.generate else args.generate
        install_selected_clients(keys)
    else:
        interactive_menu()
