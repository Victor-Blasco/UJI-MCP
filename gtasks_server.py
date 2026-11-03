#!/usr/bin/env python3
"""Servidor MCP y CLI para Google Tasks.

100% Portable - Funciona en Windows, macOS y Linux.
Compatible con Claude Desktop, Antigravity, OpenCode, Codex / VS Code, Cursor y Windsurf.
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
    """Asegura el formato RFC3339 exigido por la API de Google Tasks."""
    if not due:
        return None
    due = due.strip()
    if len(due) == 10 and due[4] == "-" and due[7] == "-":
        return f"{due}T00:00:00.000Z"
    return due


def get_tasks_service(interactive: bool = False):
    """Autentica y devuelve el cliente oficial de Google Tasks."""
    creds = None
    if DEFAULT_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(DEFAULT_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            DEFAULT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
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
    """Lista todas las listas de tareas del usuario."""
    service = get_tasks_service()
    res = service.tasklists().list(maxResults=100).execute()
    return [
        {"id": item.get("id"), "title": item.get("title"), "updated": item.get("updated")}
        for item in res.get("items", [])
    ]


def create_tasklist(title: str) -> dict[str, Any]:
    """Crea una nueva lista de tareas en Google Tasks."""
    service = get_tasks_service()
    return service.tasklists().insert(body={"title": title}).execute()


def list_tasks(
    tasklist_id: str = "@default",
    show_completed: bool = True,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Lista las tareas de una lista específica ('@default' es la principal)."""
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
    """Crea una nueva tarea en Google Tasks."""
    service = get_tasks_service()
    body: dict[str, Any] = {"title": title}
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
    """Actualiza una tarea existente."""
    service = get_tasks_service()
    current = service.tasks().get(tasklist=tasklist_id, task=task_id).execute()

    if title:
        current["title"] = title
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
        .update(tasklist=tasklist_id, task=task_id, body=current)
        .execute()
    )


def complete_task(task_id: str, tasklist_id: str = "@default") -> dict[str, Any]:
    """Marca una tarea como completada."""
    return update_task(task_id=task_id, status="completed", tasklist_id=tasklist_id)


def delete_task(task_id: str, tasklist_id: str = "@default") -> dict[str, str]:
    """Elimina una tarea."""
    service = get_tasks_service()
    service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
    return {"status": "deleted", "task_id": task_id}


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
