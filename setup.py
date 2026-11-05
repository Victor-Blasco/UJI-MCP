#!/usr/bin/env python3
"""Configurador y Asistente de Instalación para el Pack MCP Aula Virtual UJI & Google Tasks.

Guía interactiva paso a paso para configurar dependencias, vincular cuentas
y generar/fusionar configuraciones para Claude Desktop, Antigravity, OpenCode,
Codex / VS Code y Cursor.
Cumple estrictamente con las directrices de AGENTS.md (silencio por defecto,
menús persistentes, merge seguro y gestión idiomática de excepciones).
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
AULAVIRTUAL_SCRIPT = BASE_DIR / "aulavirtual_server.py"
GTASKS_SCRIPT = BASE_DIR / "gtasks_server.py"
PYTHON_EXE = sys.executable

DEBUG_MODE = False


def _get_server_entries(use_placeholders: bool = False) -> dict[str, Any]:
    """Genera las entradas JSON para uji-aulavirtual y google-tasks.

    Args:
        use_placeholders: Si es True, utiliza '<RUTA_A_UJI_MCP>' en vez de rutas absolutas.

    Returns:
        dict[str, Any]: Diccionario con la definición de los dos servidores MCP.
    """
    if use_placeholders:
        py_cmd = "python"
        av_path = "<RUTA_A_UJI_MCP>/aulavirtual_server.py"
        gt_path = "<RUTA_A_UJI_MCP>/gtasks_server.py"
    else:
        py_cmd = PYTHON_EXE.replace("\\", "/")
        av_path = str(AULAVIRTUAL_SCRIPT.resolve()).replace("\\", "/")
        gt_path = str(GTASKS_SCRIPT.resolve()).replace("\\", "/")

    return {
        "uji-aulavirtual": {
            "command": py_cmd,
            "args": [av_path],
        },
        "google-tasks": {
            "command": py_cmd,
            "args": [gt_path],
        },
    }


def _get_client_target_paths() -> dict[str, tuple[str, Path, Path]]:
    """Devuelve las rutas reales y de plantilla para cada cliente de IA soportado.

    Returns:
        dict[str, tuple[str, Path, Path]]: Mapeo de clave a tupla con
            (Nombre legible, Ruta de configuración en el sistema, Ruta de plantilla local).
    """
    home = Path.home()
    cfg_dir = BASE_DIR / "configs"

    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        claude_path = appdata / "Claude" / "claude_desktop_config.json"
        vscode_path = appdata / "Code" / "User" / "mcp.json"
        cursor_path = home / ".cursor" / "mcp.json"
    elif sys.platform == "darwin":
        claude_path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        vscode_path = home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
        cursor_path = home / ".cursor" / "mcp.json"
    else:
        claude_path = home / ".config" / "Claude" / "claude_desktop_config.json"
        vscode_path = home / ".config" / "Code" / "User" / "mcp.json"
        cursor_path = home / ".cursor" / "mcp.json"

    agy_path = home / ".gemini" / "config" / "mcp_config.json"
    opencode_path = home / ".config" / "opencode" / "opencode.json"

    return {
        "claude": ("Claude Desktop", claude_path, cfg_dir / "claude_desktop_config.json"),
        "agy": ("Antigravity (Agy)", agy_path, cfg_dir / "agy_mcp_config.json"),
        "opencode": ("OpenCode", opencode_path, cfg_dir / "opencode_mcp.json"),
        "vscode": ("Codex / VS Code", vscode_path, cfg_dir / "vscode_mcp.json"),
        "cursor": ("Cursor", cursor_path, cfg_dir / "cursor_mcp.json"),
    }


def _merge_and_write_config(client_key: str, target_path: Path, servers: dict[str, Any]) -> None:
    """Fusiona los servidores MCP en el archivo de configuración del cliente respetando claves previas.

    Args:
        client_key: Identificador del cliente ('claude', 'agy', 'opencode', 'vscode', 'cursor').
        target_path: Ruta al archivo JSON de configuración.
        servers: Diccionario con los servidores MCP a registrar.

    Raises:
        OSError: Si falla la creación de carpetas o la escritura en disco.
    """
    existing: dict[str, Any] = {}
    if target_path.exists():
        try:
            raw = target_path.read_text(encoding="utf-8").strip()
            if raw:
                existing = json.loads(raw)
        except (json.JSONDecodeError, OSError):
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
    """Instala (haciendo merge seguro) los MCPs únicamente en los clientes seleccionados.

    Args:
        selected_keys: Lista de claves de clientes seleccionados por el usuario.
    """
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
        except OSError as exc:
            print(f"  [!]  {label:<18} -> Error al configurar en {real_path}: {exc}")
            print(f"       Puedes copiar la plantilla de: {local_template_path}")


def choose_and_install_clients_menu() -> None:
    """Muestra el submenú interactivo para elegir en qué clientes de IA instalar los MCPs."""
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
    """Construye el comando para subprocesos propagando el flag --debug si está activo.

    Args:
        script: Ruta al script Python a ejecutar.
        extra_args: Argumentos adicionales de línea de comandos.

    Returns:
        list[str]: Lista de argumentos lista para subprocess.check_call.
    """
    cmd = [PYTHON_EXE, str(script)]
    if DEBUG_MODE:
        cmd.append("--debug")
    cmd.extend(extra_args)
    return cmd


def install_requirements() -> None:
    """Instala las dependencias necesarias mediante pip."""
    req_file = BASE_DIR / "requirements.txt"
    print("\nInstalando dependencias necesarias...")
    subprocess.check_call([PYTHON_EXE, "-m", "pip", "install", "-r", str(req_file)])
    print("[OK] Dependencias instaladas con éxito.")


def connect_aulavirtual() -> None:
    """Ejecuta el asistente de inicio de sesión del Aula Virtual UJI."""
    subprocess.check_call(_subproc_cmd(AULAVIRTUAL_SCRIPT, "login"))


def connect_tasks() -> None:
    """Ejecuta el flujo de autorización OAuth para Google Tasks."""
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
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Error conectando Google Tasks: {exc}")


def show_test_deadlines() -> None:
    """Consulta y muestra las próximas entregas detectadas para verificar la conexión."""
    try:
        subprocess.check_call(_subproc_cmd(AULAVIRTUAL_SCRIPT, "deadlines"))
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Error consultando entregas: {exc}")


def show_logs() -> None:
    """Muestra las últimas líneas del archivo de trazabilidad aulavirtual.log."""
    try:
        subprocess.check_call(_subproc_cmd(AULAVIRTUAL_SCRIPT, "logs", "-n", "60"))
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Error leyendo logs: {exc}")


def print_main_menu() -> None:
    """Imprime el menú de opciones disponible con el estado actual."""
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
    """Bucle interactivo principal persistente hasta salida explícita con '0'."""
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
