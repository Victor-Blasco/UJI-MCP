#!/usr/bin/env python3
"""Servidor MCP y CLI para Google Tasks.

100% Portable - Funciona en Windows, macOS y Linux.
Compatible con Claude Desktop, Antigravity, OpenCode, Codex / VS Code, Cursor y Windsurf.
Cumple estrictamente con las directrices de AGENTS.md (tipado moderno, docstrings Google, gestión de recursos).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

try:
    from mcp.server.mcpserver import MCPServer as _MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as _MCPServer
    except ImportError:
        _MCPServer = None

SCOPES = ["https://www.googleapis.com/auth/tasks"]

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CREDS_PATH = Path(
    os.environ.get("GTASKS_CREDENTIALS_PATH", BASE_DIR / "credentials.json")
)
DEFAULT_TOKEN_PATH = Path(
    os.environ.get("GTASKS_TOKEN_PATH", BASE_DIR / "token.json")
)

if _MCPServer:
    mcp = _MCPServer("google-tasks")
else:
    mcp = None


def _normalize_due(due: str | None) -> str | None:
    """Normaliza la fecha de vencimiento al formato RFC3339 exigido por Google Tasks.

    Args:
        due: Fecha en formato YYYY-MM-DD o RFC3339 completo.

    Returns:
        str | None: Cadena normalizada con sufijo T00:00:00.000Z o None si due está vacío.
    """
    if not due:
        return None
    due = due.strip()
    if len(due) == 10 and due[4] == "-" and due[7] == "-":
        return f"{due}T00:00:00.000Z"
    return due


def get_tasks_service(interactive: bool = False) -> Any:
    """Autentica con OAuth 2.0 y devuelve el recurso cliente de la API de Google Tasks.

    Args:
        interactive: Si es True, permite abrir el navegador para login si no hay token.

    Returns:
        Resource: Cliente de Google Tasks de googleapiclient.discovery.build.

    Raises:
        FileNotFoundError: Si no existe el archivo credentials.json necesario para autenticar.
        RuntimeError: Si el flujo de autorización OAuth falla.
    """
    creds = None
    if DEFAULT_TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(DEFAULT_TOKEN_PATH), SCOPES)
        except (json.JSONDecodeError, ValueError, OSError):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                DEFAULT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if not DEFAULT_CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"No se encontró el archivo de credenciales en: {DEFAULT_CREDS_PATH}\n"
                    "Coloca tu archivo 'credentials.json' (Desktop App) en esta carpeta o ejecuta:\n"
                    f'python "{Path(__file__).resolve()}" auth'
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(DEFAULT_CREDS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
            DEFAULT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("tasks", "v1", credentials=creds)


def list_tasklists() -> list[dict[str, Any]]:
    """Lista todas las listas de tareas del usuario autenticado en Google Tasks.

    Returns:
        list[dict[str, Any]]: Lista de diccionarios con claves 'id', 'title' y 'updated'.

    Raises:
        RuntimeError: Si la llamada a la API de Google falla.
    """
    service = get_tasks_service()
    res = service.tasklists().list(maxResults=100).execute()
    return [
        {"id": item.get("id"), "title": item.get("title"), "updated": item.get("updated")}
        for item in res.get("items", [])
    ]


def create_tasklist(title: str) -> dict[str, Any]:
    """Crea una nueva lista de tareas en la cuenta de Google Tasks.

    Args:
        title: Título legible para la nueva lista de tareas (ej. 'Aula Virtual UJI').

    Returns:
        dict[str, Any]: Metadatos de la lista creada (incluyendo su 'id').

    Raises:
        ValueError: Si el título está vacío.
        RuntimeError: Si la API de Google devuelve un error.
    """
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("El título de la lista de tareas no puede estar vacío.")
    service = get_tasks_service()
    return service.tasklists().insert(body={"title": clean_title}).execute()


def list_tasks(
    tasklist_id: str = "@default",
    show_completed: bool = True,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Lista las tareas de una lista específica ('@default' representa la lista principal).

    Args:
        tasklist_id: Identificador de la lista de tareas (por defecto '@default').
        show_completed: Si es True, incluye también tareas ya marcadas como completadas.
        max_results: Límite máximo de tareas a recuperar (1 a 100).

    Returns:
        list[dict[str, Any]]: Tareas con id, title, notes, status, due y webViewLink.

    Raises:
        RuntimeError: Si la consulta a la API de Google falla.
    """
    service = get_tasks_service()
    res = (
        service.tasks()
        .list(
            tasklist=tasklist_id,
            showCompleted=show_completed,
            showHidden=show_completed,
            maxResults=max_results,
        )
        .execute()
    )
    return [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "notes": t.get("notes", ""),
            "status": t.get("status"),
            "due": t.get("due"),
            "completed": t.get("completed"),
            "parent": t.get("parent"),
            "webViewLink": t.get("webViewLink"),
        }
        for t in res.get("items", [])
    ]


def create_task(
    title: str,
    notes: str = "",
    due: str = "",
    tasklist_id: str = "@default",
    parent: str = "",
) -> dict[str, Any]:
    """Crea una nueva tarea en Google Tasks con fecha límite y notas opcionales.

    Args:
        title: Título de la tarea.
        notes: Descripción, instrucciones o enlaces asociados a la tarea.
        due: Fecha de vencimiento en formato YYYY-MM-DD (ej. '2026-11-20').
        tasklist_id: ID de la lista donde crear la tarea ('@default' para principal).
        parent: ID de la tarea padre si se desea anidar como subtarea.

    Returns:
        dict[str, Any]: Objeto de la tarea creada por la API de Google Tasks.

    Raises:
        ValueError: Si el título está vacío.
        RuntimeError: Si la inserción falla en Google Tasks.
    """
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("El título de la tarea no puede estar vacío.")

    service = get_tasks_service()
    body: dict[str, Any] = {"title": clean_title}
    if notes:
        body["notes"] = notes
    norm_due = _normalize_due(due)
    if norm_due:
        body["due"] = norm_due

    kwargs: dict[str, Any] = {"tasklist": tasklist_id, "body": body}
    if parent:
        kwargs["parent"] = parent

    return service.tasks().insert(**kwargs).execute()


def update_task(
    task_id: str,
    title: str = "",
    notes: str = "",
    status: str = "",
    due: str = "",
    tasklist_id: str = "@default",
) -> dict[str, Any]:
    """Actualiza los campos de una tarea existente en Google Tasks.

    Args:
        task_id: Identificador de la tarea a modificar.
        title: Nuevo título (dejar vacío para mantener el actual).
        notes: Nuevas notas (dejar vacío para mantener las actuales).
        status: 'needsAction' (pendiente) o 'completed' (completada).
        due: Nueva fecha de entrega YYYY-MM-DD (dejar vacío para mantener).
        tasklist_id: ID de la lista que contiene la tarea.

    Returns:
        dict[str, Any]: Tarea actualizada tras llamar a la API.

    Raises:
        ValueError: Si task_id está vacío.
        RuntimeError: Si la actualización en Google falla.
    """
    clean_id = task_id.strip()
    if not clean_id:
        raise ValueError("task_id es obligatorio para actualizar una tarea.")

    service = get_tasks_service()
    current = service.tasks().get(tasklist=tasklist_id, task=clean_id).execute()

    if title:
        current["title"] = title.strip()
    if notes:
        current["notes"] = notes
    if status in ("needsAction", "completed"):
        current["status"] = status
        if status == "needsAction":
            current.pop("completed", None)
    norm_due = _normalize_due(due)
    if norm_due:
        current["due"] = norm_due

    return (
        service.tasks()
        .update(tasklist=tasklist_id, task=clean_id, body=current)
        .execute()
    )


def complete_task(task_id: str, tasklist_id: str = "@default") -> dict[str, Any]:
    """Marca una tarea como completada ('completed') en Google Tasks.

    Args:
        task_id: ID de la tarea a dar por finalizada.
        tasklist_id: ID de la lista donde reside la tarea (por defecto '@default').

    Returns:
        dict[str, Any]: Metadatos de la tarea actualizada.
    """
    return update_task(task_id=task_id, status="completed", tasklist_id=tasklist_id)


def delete_task(task_id: str, tasklist_id: str = "@default") -> dict[str, str]:
    """Elimina permanentemente una tarea de Google Tasks.

    Args:
        task_id: ID de la tarea a eliminar.
        tasklist_id: ID de la lista de tareas correspondiente.

    Returns:
        dict[str, str]: Confirmación {'status': 'deleted', 'task_id': task_id}.

    Raises:
        ValueError: Si task_id está vacío.
        RuntimeError: Si la API de Google no puede eliminar la tarea.
    """
    clean_id = task_id.strip()
    if not clean_id:
        raise ValueError("task_id es obligatorio para eliminar una tarea.")

    service = get_tasks_service()
    service.tasks().delete(tasklist=tasklist_id, task=clean_id).execute()
    return {"status": "deleted", "task_id": clean_id}


if mcp:
    mcp.tool()(list_tasklists)
    mcp.tool()(create_tasklist)
    mcp.tool()(list_tasks)
    mcp.tool()(create_task)
    mcp.tool()(update_task)
    mcp.tool()(complete_task)
    mcp.tool()(delete_task)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Google Tasks MCP & CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("auth", help="Autentica con Google Tasks vía navegador")
    sub.add_parser("lists", help="Lista todas las listas de tareas")

    p_list = sub.add_parser("tasks", help="Lista las tareas")
    p_list.add_argument("--list-id", default="@default")
    p_list.add_argument("--hide-completed", action="store_true")

    p_add = sub.add_parser("add", help="Crea una nueva tarea")
    p_add.add_argument("title", help="Título")
    p_add.add_argument("--notes", default="", help="Notas")
    p_add.add_argument("--due", default="", help="Fecha límite (YYYY-MM-DD)")
    p_add.add_argument("--list-id", default="@default")

    p_done = sub.add_parser("done", help="Completa una tarea")
    p_done.add_argument("task_id", help="ID de la tarea")
    p_done.add_argument("--list-id", default="@default")

    p_del = sub.add_parser("delete", help="Elimina una tarea")
    p_del.add_argument("task_id", help="ID de la tarea")
    p_del.add_argument("--list-id", default="@default")

    args = parser.parse_args()

    if args.cmd == "auth":
        get_tasks_service(interactive=True)
        print(f"\n[OK] Autenticación completada. Token guardado en {DEFAULT_TOKEN_PATH}")
    elif args.cmd == "lists":
        print(json.dumps(list_tasklists(), indent=2, ensure_ascii=False))
    elif args.cmd == "tasks":
        print(json.dumps(list_tasks(tasklist_id=args.list_id, show_completed=not args.hide_completed), indent=2, ensure_ascii=False))
    elif args.cmd == "add":
        print(json.dumps(create_task(title=args.title, notes=args.notes, due=args.due, tasklist_id=args.list_id), indent=2, ensure_ascii=False))
    elif args.cmd == "done":
        print(json.dumps(complete_task(task_id=args.task_id, tasklist_id=args.list_id), indent=2, ensure_ascii=False))
    elif args.cmd == "delete":
        print(json.dumps(delete_task(task_id=args.task_id, tasklist_id=args.list_id), indent=2, ensure_ascii=False))
    else:
        if mcp:
            mcp.run()
        else:
            parser.print_help()


if __name__ == "__main__":
    _cli()
