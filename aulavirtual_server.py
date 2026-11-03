#!/usr/bin/env python3
"""Servidor MCP y CLI para el Aula Virtual de la Universitat Jaume I (UJI).

100% Portable y Universal para cualquier grado, máster o asignatura de la UJI.
Incluye sistema completo de trazabilidad (logs) en archivo y consola.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import functools
import html
import http.server
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable

import requests

try:
    from mcp.server.mcpserver import MCPServer as _MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as _MCPServer
    except ImportError:
        _MCPServer = None

MOODLE_BASE_URL = os.environ.get("MOODLE_BASE_URL", "https://aulavirtual.uji.es").rstrip("/")
REST_ENDPOINT = f"{MOODLE_BASE_URL}/webservice/rest/server.php"

BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = Path(os.environ.get("MOODLE_TOKEN_FILE", BASE_DIR / "aulavirtual_token.json"))
LOG_FILE = Path(os.environ.get("MOODLE_LOG_FILE", BASE_DIR / "aulavirtual.log"))

# Configuración de trazabilidad (Logging desactivado por defecto; se activa con --debug o MOODLE_DEBUG=1)
logger = logging.getLogger("uji-aulavirtual")
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.NullHandler())
logger.disabled = True
DEBUG_ENABLED = False


def enable_debug_logging() -> None:
    """Activa la trazabilidad completa en archivo (aulavirtual.log) y por consola (stderr)."""
    global DEBUG_ENABLED
    if DEBUG_ENABLED:
        return
    DEBUG_ENABLED = True
    logger.disabled = False
    os.environ["MOODLE_DEBUG"] = "1"

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] [PID:%(process)d] %(funcName)s: %(message)s")
    )
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(console)


if os.environ.get("MOODLE_DEBUG") == "1" or "--debug" in sys.argv:
    enable_debug_logging()


def trace_tool(func: Callable) -> Callable:
    """Decorador para registrar la trazabilidad completa de cada herramienta MCP / función."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        logger.info("START %s | args=%s kwargs=%s", func.__name__, args, kwargs)
        try:
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            summary = f"len={len(result)}" if isinstance(result, (list, dict)) else type(result).__name__
            logger.info("SUCCESS %s (%.1f ms) | %s", func.__name__, elapsed, summary)
            return result
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.error("ERROR %s (%.1f ms): %s\n%s", func.__name__, elapsed, exc, traceback.format_exc())
            raise

    return wrapper


def get_workspace_root() -> Path:
    """Busca la raíz del proyecto buscando carpetas de asignaturas o el directorio actual."""
    env_root = os.environ.get("AULAVIRTUAL_WORKSPACE")
    if env_root:
        return Path(env_root).resolve()

    curr = Path.cwd().resolve()
    for p in [curr, *curr.parents[:4], BASE_DIR, *BASE_DIR.parents[:3]]:
        if any(p.glob("SJK*")) or (p / ".git").exists() or (p / ".agents").exists():
            return p
    return curr


def _extract_course_meta(c: dict[str, Any]) -> tuple[str, str]:
    """Extrae dinámicamente el código (ej. SJK006, EI1049) y nombre limpio de cualquier asignatura de la UJI."""
    shortname = str(c.get("shortname", "")).strip()
    fullname = str(c.get("fullname", "")).strip()

    code_match = re.match(r"^([A-Za-z]{2,5}\d{3,4})", shortname)
    if code_match:
        code = code_match.group(1).upper()
    else:
        code = re.sub(r"-\d{4}[-/]\d{4}$", "", shortname) or str(c.get("id", "CURSO"))

    clean_name = re.sub(r"\(\d{4}[-/]\d{4}\)\s*$", "", fullname).strip()
    if " - " in clean_name:
        clean_name = clean_name.split(" - ", 1)[1].strip()

    return code, (clean_name or fullname or code)


if _MCPServer:
    mcp = _MCPServer("uji-aulavirtual")
else:
    mcp = None


def get_token() -> str:
    """Recupera el wstoken guardado o desde variable de entorno."""
    env_token = os.environ.get("MOODLE_TOKEN")
    if env_token:
        return env_token.strip()

    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token = data.get("token") or data.get("wstoken")
            if token:
                return token.strip()
        except Exception as exc:
            logger.warning("Error leyendo archivo de token %s: %s", TOKEN_FILE, exc)

    msg = (
        f"No se ha encontrado el token de acceso del Aula Virtual en: {TOKEN_FILE}\n"
        "Ejecuta en tu terminal para iniciar sesión:\n"
        f'python "{Path(__file__).resolve()}" login'
    )
    logger.error(msg)
    raise RuntimeError(msg)


def save_token(token: str, user_info: dict[str, Any] | None = None) -> None:
    """Guarda el wstoken con permisos de lectura exclusivos para el propietario (0600)."""
    payload = {
        "token": token.strip(),
        "siteurl": MOODLE_BASE_URL,
        "updated_at": datetime.datetime.now().isoformat(),
        "user_info": user_info or {},
    }
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    logger.info("Token guardado correctamente en %s para usuario %s", TOKEN_FILE, (user_info or {}).get("username"))


def _validate_moodle_url(url: str) -> None:
    """Verifica que una URL pertenezca estrictamente al dominio HTTPS del Aula Virtual para no exponer el token."""
    parsed = urllib.parse.urlparse(url)
    expected_host = urllib.parse.urlparse(MOODLE_BASE_URL).netloc.lower()
    if parsed.scheme.lower() != "https" or parsed.netloc.lower() != expected_host:
        logger.error("Intento de acceso a URL externa bloqueado: %s", url)
        raise ValueError(
            f"URL bloqueada por seguridad: '{url}'. Solo se permiten descargas desde https://{expected_host}/"
        )


def _sanitize_filename(filename: str) -> str:
    """Limpia un nombre de archivo evitando Path Traversal y caracteres inválidos."""
    base = Path(filename).name.strip()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    if not base or base in (".", ".."):
        raise ValueError(f"Nombre de archivo inválido: '{filename}'")
    return base


def _flatten_params(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Convierte estructuras anidadas de Python a parámetros de formulario PHP para Moodle."""
    out: dict[str, str] = {}
    for key, val in data.items():
        curr_key = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(val, dict):
            out.update(_flatten_params(val, curr_key))
        elif isinstance(val, (list, tuple)):
            for i, elem in enumerate(val):
                if isinstance(elem, dict):
                    out.update(_flatten_params(elem, f"{curr_key}[{i}]"))
                else:
                    out[f"{curr_key}[{i}]"] = str(elem)
        elif val is not None:
            out[curr_key] = str(val)
    return out


def call_moodle_api(wsfunction: str, **kwargs) -> Any:
    """Realiza una petición a la API REST de Moodle con trazabilidad de tiempos y errores."""
    token = get_token()
    params = {
        "wstoken": token,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
    }
    extra_params = _flatten_params(kwargs)
    all_params = {**params, **extra_params}

    t0 = time.perf_counter()
    logger.debug("Moodle API REQUEST -> wsfunction=%s params=%s", wsfunction, extra_params)
    resp = requests.post(REST_ENDPOINT, data=all_params, timeout=25)
    elapsed = (time.perf_counter() - t0) * 1000
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and data.get("exception"):
        msg = data.get("message", "Error desconocido de Moodle")
        code = data.get("errorcode", "")
        logger.error("Moodle API EXCEPTION en %s (%.1f ms): [%s] %s", wsfunction, elapsed, code, msg)
        raise RuntimeError(f"Error Moodle [{code}]: {msg}")

    logger.debug("Moodle API RESPONSE <- wsfunction=%s (%.1f ms) HTTP %s", wsfunction, elapsed, resp.status_code)
    return data


def resolve_course_id(course_id_or_code: str | int) -> int:
    """Convierte cualquier código (ej. 'SJK006', 'EI1049', 'MT1022'), nombre o ID en el courseid numérico de Moodle."""
    raw = str(course_id_or_code).strip()
    if raw.isdigit():
        return int(raw)

    upper = raw.upper()
    courses = list_courses()

    exact_matches = [
        c for c in courses
        if str(c.get("code", "")).upper() == upper or str(c.get("shortname", "")).upper().startswith(f"{upper}-20")
    ]
    if exact_matches:
        cid = int(exact_matches[0]["id"])
        logger.debug("Resuelta asignatura '%s' (coincidencia exacta) -> ID %d", course_id_or_code, cid)
        return cid

    for c in courses:
        if (
            upper in str(c.get("code", "")).upper()
            or upper in str(c.get("shortname", "")).upper()
            or upper in str(c.get("fullname", "")).upper()
        ):
            cid = int(c["id"])
            logger.debug("Resuelta asignatura '%s' (coincidencia parcial) -> ID %d", course_id_or_code, cid)
            return cid

    raise ValueError(
        f"No se encontró la asignatura '{course_id_or_code}' entre tus cursos matriculados del Aula Virtual."
    )


def _find_local_course_dir(course_code: str, default_name: str) -> Path:
    """Localiza o sugiere la carpeta local para cualquier asignatura de la UJI."""
    root = get_workspace_root()
    for item in root.glob(f"*{course_code}*"):
        if item.is_dir():
            return item
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", default_name).strip()
    return root / f"{course_code} - {safe_name}"


def _clean_html(raw_html: str) -> str:
    """Elimina etiquetas HTML y decodifica entidades para lectura limpia."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


@trace_tool
def get_user_profile() -> dict[str, Any]:
    """Obtiene el perfil y datos del usuario autenticado en el Aula Virtual."""
    info = call_moodle_api("core_webservice_get_site_info")
    return {
        "username": info.get("username"),
        "fullname": info.get("fullname"),
        "userid": info.get("userid"),
        "sitename": info.get("sitename"),
        "siteurl": info.get("siteurl"),
        "userpictureurl": info.get("userpictureurl"),
    }


@trace_tool
def list_courses() -> list[dict[str, Any]]:
    """Lista todas las asignaturas matriculadas del usuario en la UJI con sus IDs, códigos y rutas locales."""
    profile = get_user_profile()
    userid = profile["userid"]
    raw_courses = call_moodle_api("core_enrol_get_users_courses", userid=userid)

    results = []
    for c in raw_courses:
        cid = c.get("id")
        shortname = c.get("shortname", "")
        fullname = c.get("fullname", "")

        code, clean_name = _extract_course_meta(c)
        local_dir = _find_local_course_dir(code, clean_name)

        results.append({
            "id": cid,
            "shortname": shortname,
            "fullname": fullname,
            "code": code,
            "clean_name": clean_name,
            "local_directory": str(local_dir) if local_dir.exists() else None,
            "suggested_directory": str(local_dir),
            "url": f"{MOODLE_BASE_URL}/course/view.php?id={cid}",
        })
    return results


@trace_tool
def get_course_contents(course_id_or_code: str) -> list[dict[str, Any]]:
    """Obtiene los temas, secciones, archivos (PDF, notebooks) y tareas de una asignatura."""
    cid = resolve_course_id(course_id_or_code)
    sections = call_moodle_api("core_course_get_contents", courseid=cid)

    clean_sections = []
    for s in sections:
        modules = []
        for m in s.get("modules", []):
            files = []
            for f in m.get("contents", []):
                files.append({
                    "filename": f.get("filename"),
                    "filesize": f.get("filesize"),
                    "fileurl": f.get("fileurl"),
                    "mimetype": f.get("mimetype"),
                    "timecreated": f.get("timecreated"),
                    "timemodified": f.get("timemodified"),
                })
            modules.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "modname": m.get("modname"),
                "url": m.get("url"),
                "description": _clean_html(m.get("description", "")),
                "files": files,
            })

        clean_sections.append({
            "id": s.get("id"),
            "name": s.get("name"),
            "summary": _clean_html(s.get("summary", "")),
            "modules": modules,
        })
    return clean_sections


@trace_tool
def get_assignments(course_id_or_code: str = "") -> list[dict[str, Any]]:
    """Lista las tareas y prácticas de una asignatura o de todas las asignaturas."""
    kwargs: dict[str, Any] = {}
    if course_id_or_code:
        kwargs["courseids"] = [resolve_course_id(course_id_or_code)]

    res = call_moodle_api("mod_assign_get_assignments", **kwargs)
    assignments_list = []

    for c in res.get("courses", []):
        cid = c.get("id")
        c_short = c.get("shortname", "")

        for a in c.get("assignments", []):
            due = a.get("duedate", 0)
            cutoff = a.get("cutoffdate", 0)
            due_iso = datetime.datetime.fromtimestamp(due).isoformat() if due else None
            cutoff_iso = datetime.datetime.fromtimestamp(cutoff).isoformat() if cutoff else None

            attachments = [
                {"filename": att.get("filename"), "fileurl": att.get("fileurl")}
                for att in a.get("introattachments", [])
            ]

            assignments_list.append({
                "assignment_id": a.get("id"),
                "cmid": a.get("cmid"),
                "course_id": cid,
                "course_code": c_short,
                "name": a.get("name"),
                "instructions": _clean_html(a.get("intro", "")),
                "duedate_ts": due,
                "duedate": due_iso,
                "cutoffdate": cutoff_iso,
                "attachments": attachments,
                "url": f"{MOODLE_BASE_URL}/mod/assign/view.php?id={a.get('cmid')}",
            })

    assignments_list.sort(key=lambda x: x["duedate_ts"] if x["duedate_ts"] else 9999999999)
    return assignments_list


@trace_tool
def get_submission_status(assign_id: int) -> dict[str, Any]:
    """Consulta si una tarea concreta ya ha sido entregada, calificada y el feedback recibido."""
    res = call_moodle_api("mod_assign_get_submission_status", assignid=assign_id)
    last_attempt = res.get("lastattempt", {})
    sub = last_attempt.get("submission", {})
    feedback = res.get("feedback", {})

    status = sub.get("status", "new")
    submitted_files = []
    for plugin in sub.get("plugins", []):
        if plugin.get("type") == "file":
            for area in plugin.get("fileareas", []):
                for f in area.get("files", []):
                    submitted_files.append({"filename": f.get("filename"), "fileurl": f.get("fileurl")})

    return {
        "status": status,
        "grading_status": last_attempt.get("gradingstatus"),
        "timemodified": sub.get("timemodified"),
        "submitted_files": submitted_files,
        "grade": feedback.get("grade", {}).get("grade"),
        "grade_for_display": feedback.get("gradefordisplay"),
    }


@trace_tool
def get_upcoming_deadlines(days_ahead: int = 45) -> list[dict[str, Any]]:
    """Obtiene los eventos y entregas del calendario del Aula Virtual ordenados por fecha."""
    now = int(datetime.datetime.now().timestamp())
    limit = now + (days_ahead * 86400)

    res = call_moodle_api(
        "core_calendar_get_action_events_by_timesort",
        timesortfrom=now,
        timesortto=limit,
        limitnum=50,
    )

    events = []
    for ev in res.get("events", []):
        ts = ev.get("timesort")
        events.append({
            "id": ev.get("id"),
            "name": ev.get("name"),
            "event_type": ev.get("eventtype"),
            "description": _clean_html(ev.get("description", "")),
            "date": datetime.datetime.fromtimestamp(ts).isoformat() if ts else None,
            "course": ev.get("course", {}).get("shortname"),
            "url": ev.get("url"),
            "action_name": ev.get("action", {}).get("name"),
            "action_url": ev.get("action", {}).get("url"),
        })
    return events


@trace_tool
def get_course_announcements(course_id_or_code: str, limit: int = 5) -> list[dict[str, Any]]:
    """Lee los avisos y mensajes recientes publicados por los profesores en el foro de noticias."""
    cid = resolve_course_id(course_id_or_code)
    forums = call_moodle_api("mod_forum_get_forums_by_courses", courseids=[cid])

    announcement_forums = [
        f for f in forums if f.get("type") in ("news", "general") or "aviso" in f.get("name", "").lower() or "noticia" in f.get("name", "").lower()
    ]
    if not announcement_forums and forums:
        announcement_forums = [forums[0]]

    posts = []
    for f in announcement_forums:
        discussions = call_moodle_api("mod_forum_get_forum_discussions", forumid=f["id"])
        for d in discussions.get("discussions", [])[:limit]:
            created_ts = d.get("created", 0)
            posts.append({
                "subject": d.get("name"),
                "author": d.get("userfullname"),
                "date": datetime.datetime.fromtimestamp(created_ts).isoformat() if created_ts else None,
                "message": _clean_html(d.get("message", "")),
                "discussion_id": d.get("discussion"),
            })
    return posts


@trace_tool
def download_course_file(
    file_url: str,
    filename: str,
    course_id_or_code: str = "",
    section_name: str = "",
) -> dict[str, str]:
    """Descarga un archivo organizándolo entre 01_Teoria, 02_Laboratorio o fuentes."""
    _validate_moodle_url(file_url)
    clean_filename = _sanitize_filename(filename)
    token = get_token()

    target_root = get_workspace_root()
    if course_id_or_code:
        try:
            cid = resolve_course_id(course_id_or_code)
            for c in list_courses():
                if int(c["id"]) == cid:
                    target_root = Path(c["suggested_directory"])
                    break
        except Exception:
            code_clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", course_id_or_code).strip()
            if code_clean:
                target_root = _find_local_course_dir(code_clean, code_clean)

    subfolder = "fuentes"
    text_to_check = f"{section_name} {clean_filename}".lower()
    if any(k in text_to_check for k in ["lab", "práct", "practic", "sesión", "sesion", "taller", "tarea", "entrega", "notebook", ".ipynb"]):
        subfolder = "02_Laboratorio"
    elif any(k in text_to_check for k in ["teor", "tema", "lección", "leccion", "capítulo", "slide", "diapositiv", "transparencia", "unidad"]):
        subfolder = "01_Teoria"

    target_dir = (target_root / subfolder).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = (target_dir / clean_filename).resolve()

    if not target_path.is_relative_to(target_dir):
        raise ValueError("Ruta de destino fuera del directorio permitido.")

    sep = "&" if "?" in file_url else "?"
    download_url = f"{file_url}{sep}token={token}"

    resp = requests.get(download_url, stream=True, timeout=60, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        redir_url = resp.headers.get("Location", "")
        _validate_moodle_url(redir_url)
        resp = requests.get(redir_url, stream=True, timeout=60, allow_redirects=False)
    resp.raise_for_status()

    with open(target_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)

    logger.info("Archivo descargado en %s (%d bytes)", target_path, target_path.stat().st_size)
    return {
        "status": "success",
        "saved_path": str(target_path),
        "filesize_bytes": str(target_path.stat().st_size),
        "subfolder": subfolder,
    }


@trace_tool
def sync_assignments_to_gtasks(
    tasklist_title: str = "Aula Virtual UJI",
    days_ahead: int = 90,
) -> dict[str, Any]:
    """Sincroniza automáticamente las entregas pendientes del Aula Virtual con Google Tasks."""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from gtasks_server import create_task, create_tasklist, list_tasklists, list_tasks
    except ImportError:
        raise RuntimeError("No se encontró el módulo 'gtasks_server.py' en la misma carpeta.")

    tasklists = list_tasklists()
    target_list_id = None
    for tl in tasklists:
        if tl.get("title", "").strip().lower() == tasklist_title.strip().lower():
            target_list_id = tl.get("id")
            break

    if not target_list_id:
        new_list = create_tasklist(tasklist_title)
        target_list_id = new_list.get("id")

    existing_tasks = list_tasks(tasklist_id=target_list_id, show_completed=True, max_results=100)
    existing_titles = {t.get("title", "").strip().lower() for t in existing_tasks}

    assignments = get_assignments()
    now_ts = int(datetime.datetime.now().timestamp())
    limit_ts = now_ts + (days_ahead * 86400)

    created_tasks = []
    skipped_count = 0

    for a in assignments:
        due_ts = a.get("duedate_ts", 0)
        if not due_ts or due_ts < now_ts or due_ts > limit_ts:
            continue

        c_code = a.get("course_code") or "UJI"
        title = f"[{c_code}] {a.get('name')}".strip()

        if title.lower() in existing_titles:
            skipped_count += 1
            continue

        try:
            status_info = get_submission_status(a["assignment_id"])
            if status_info.get("status") == "submitted":
                skipped_count += 1
                continue
        except Exception:
            pass

        due_date_str = datetime.datetime.fromtimestamp(due_ts).strftime("%Y-%m-%d")
        notes = f"Aula Virtual: {a.get('url')}\n\nInstrucciones:\n{a.get('instructions', '')[:400]}"

        new_t = create_task(
            title=title,
            notes=notes,
            due=due_date_str,
            tasklist_id=target_list_id,
        )
        created_tasks.append({
            "title": title,
            "due": due_date_str,
            "task_id": new_t.get("id"),
        })

    return {
        "tasklist_id": target_list_id,
        "tasklist_title": tasklist_title,
        "created_count": len(created_tasks),
        "skipped_existing_or_submitted": skipped_count,
        "created_tasks": created_tasks,
    }


if mcp:
    mcp.tool()(get_user_profile)
    mcp.tool()(list_courses)
    mcp.tool()(get_course_contents)
    mcp.tool()(get_assignments)
    mcp.tool()(get_submission_status)
    mcp.tool()(get_upcoming_deadlines)
    mcp.tool()(get_course_announcements)
    mcp.tool()(download_course_file)
    mcp.tool()(sync_assignments_to_gtasks)


def register_protocol_handler() -> bool:
    """Registra en Windows el protocolo moodlemobile:// para captura automática en 1 clic."""
    if sys.platform != "win32":
        logger.info("Sistema no Windows (%s): omitiendo registro de protocolo.", sys.platform)
        return False
    try:
        import winreg

        py_exe = sys.executable
        script_path = str(Path(__file__).resolve())
        debug_flag = " --debug" if DEBUG_ENABLED else ""
        cmd = f'"{py_exe}" "{script_path}"{debug_flag} handle-url "%1"'

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\moodlemobile")
        winreg.SetValue(key, "", winreg.REG_SZ, "URL:Moodle Mobile Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        cmd_key = winreg.CreateKey(key, r"shell\open\command")
        winreg.SetValue(cmd_key, "", winreg.REG_SZ, cmd)
        winreg.CloseKey(cmd_key)
        winreg.CloseKey(key)
        logger.info("Protocolo moodlemobile:// registrado en HKCU -> %s", cmd)
        return True
    except Exception as exc:
        logger.error("Error registrando protocolo moodlemobile://: %s", exc)
        return False


def _start_local_login_bridge(launch_url: str, start_time: float) -> tuple[http.server.HTTPServer, int]:
    """Levanta una página puente local en 127.0.0.1 para que el clic del usuario tenga User-Gesture en Chromium."""

    class BridgeHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("BridgeHTTP: " + format, *args)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/status":
                authenticated = False
                user_str = ""
                if TOKEN_FILE.exists():
                    try:
                        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                        up_dt = datetime.datetime.fromisoformat(data.get("updated_at", ""))
                        if up_dt.timestamp() >= start_time - 2:
                            authenticated = True
                            ui = data.get("user_info", {})
                            user_str = f"{ui.get('fullname', '')} ({ui.get('username', '')})"
                    except Exception:
                        pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"authenticated": authenticated, "user": user_str}).encode("utf-8"))
                return

            if parsed.path == "/submit":
                qs = urllib.parse.parse_qs(parsed.query)
                val = (qs.get("val") or [""])[0].strip()
                try:
                    process_auth_input(val)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                except Exception as exc:
                    logger.error("Error en /submit manual desde puente web: %s", exc)
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
                return

            logger.info("Navegador abrió la página puente de autenticación (GET %s)", self.path)
            page = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Conectar Aula Virtual UJI - MCP</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 32px; max-width: 520px; width: 90%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); text-align: center; }}
  h1 {{ font-size: 1.4rem; margin-top: 0; color: #38bdf8; }}
  p {{ color: #cbd5e1; line-height: 1.5; font-size: 0.95rem; }}
  .btn {{ display: inline-block; background: #0284c7; color: white; font-weight: 600; text-decoration: none; padding: 14px 26px; border-radius: 8px; margin: 16px 0; font-size: 1.05rem; transition: background 0.2s; cursor: pointer; border: none; }}
  .btn:hover {{ background: #0369a1; }}
  .status {{ margin-top: 18px; padding: 12px; border-radius: 8px; background: #0f172a; font-size: 0.9rem; color: #94a3b8; }}
  .ok {{ background: #064e3b !important; color: #6ee7b7 !important; font-weight: 600; }}
  details {{ margin-top: 20px; text-align: left; color: #94a3b8; font-size: 0.85rem; }}
  input {{ width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: white; margin-top: 8px; box-sizing: border-box; }}
</style>
</head>
<body>
<div class="card">
  <h1>🎓 Conectar Aula Virtual UJI</h1>
  <p>Haz clic en el botón azul. Si el navegador te pregunta <b>"¿Abrir Python?"</b> (o <i>Moodle Mobile</i>), pulsa <b>Abrir</b>:</p>
  <a class="btn" href="{launch_url}" target="_blank">🔗 Conectar con Aula Virtual UJI (1 clic)</a>
  <div id="status" class="status">⏳ Esperando confirmación del navegador...</div>
  <details>
    <summary>¿Tu navegador bloquea ventanas emergentes? Pegar manualmente</summary>
    <p>Si al pulsar el botón se queda una pestaña en blanco sin preguntar "Abrir", pega aquí la dirección <code>moodlemobile://token=...</code> o tu cookie <code>MoodleSessionaulavirtualuji</code>:</p>
    <input id="manual" placeholder="Pega aquí token o cookie y pulsa Enter..." onkeydown="if(event.key==='Enter')sendManual()">
    <button class="btn" style="padding:8px 16px;font-size:0.85rem;margin-top:8px" onclick="sendManual()">Validar</button>
  </details>
</div>
<script>
async function sendManual() {{
  const val = document.getElementById('manual').value;
  const st = document.getElementById('status');
  st.textContent = 'Validando...';
  const r = await fetch('/submit?val=' + encodeURIComponent(val));
  const j = await r.json();
  if (!j.ok) st.textContent = '❌ ' + j.error;
}}
setInterval(async () => {{
  try {{
    const r = await fetch('/status');
    const j = await r.json();
    if (j.authenticated) {{
      const st = document.getElementById('status');
      st.className = 'status ok';
      st.textContent = '✅ ¡Conectado con éxito como ' + j.user + '! Ya puedes cerrar esta pestaña.';
    }}
  }} catch (e) {{}}
}}, 1200);
</script>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

    server = http.server.HTTPServer(("127.0.0.1", 0), BridgeHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


def interactive_login() -> None:
    """Flujo de login asistido con puente web local + protocolo Windows."""
    logger.info("=== Iniciando flujo interactive_login ===")
    registered = register_protocol_handler()

    passport = str(int(time.time()))
    launch_url = f"{MOODLE_BASE_URL}/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport={passport}"
    start_time = time.time()

    server, port = _start_local_login_bridge(launch_url, start_time)
    bridge_url = f"http://127.0.0.1:{port}/"
    logger.info("Servidor puente local escuchando en %s (protocolo registrado=%s)", bridge_url, registered)

    print("\n" + "=" * 65)
    print("  Abriendo asistente de conexión en tu navegador: " + bridge_url)
    print("  1. Pulsa el botón azul 'Conectar con Aula Virtual UJI'.")
    print("  2. Cuando el navegador pregunte '¿Abrir Python?', pulsa ABRIR.")
    if DEBUG_ENABLED:
        print("  (Modo DEBUG activo -> Log en: " + str(LOG_FILE) + ")")
    print("=" * 65 + "\n")

    webbrowser.open(bridge_url)

    try:
        for _ in range(90):
            if TOKEN_FILE.exists():
                try:
                    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                    updated = data.get("updated_at")
                    if updated:
                        up_dt = datetime.datetime.fromisoformat(updated)
                        if up_dt.timestamp() >= start_time - 2:
                            name = data.get("user_info", {}).get("fullname", "tu usuario")
                            username = data.get("user_info", {}).get("username", "")
                            logger.info("Autenticación completada exitosamente para %s (%s)", name, username)
                            print(f"\n[OK] ¡Sesión iniciada y token permanente guardado para {name} ({username})!")
                            time.sleep(1.5)
                            server.shutdown()
                            return
                except Exception:
                    pass
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Espera en navegador cancelada por el usuario (Ctrl+C). Pasando a entrada por consola.")

    server.shutdown()
    print("\n[Entrada directa por terminal]")
    user_input = input("Pega tu cookie 'MoodleSessionaulavirtualuji' o token: ").strip()
    if user_input:
        process_auth_input(user_input)


def process_auth_input(raw_input: str) -> None:
    """Procesa de forma flexible cualquier tipo de entrada de autenticación con trazabilidad."""
    raw_input = raw_input.strip()
    logger.info("Procesando entrada de autenticación (longitud=%d)", len(raw_input))

    if "token=" in raw_input:
        logger.info("Detectado formato URL moodlemobile://token=...")
        raw_payload = raw_input.split("token=")[1].split("&")[0].strip().rstrip("/")
        # Añadir padding base64 si faltase
        pad = len(raw_payload) % 4
        if pad:
            raw_payload += "=" * (4 - pad)
        decoded = base64.b64decode(raw_payload).decode("utf-8", "ignore")
        parts = decoded.split(":::") if ":::" in decoded else decoded.split("###")
        logger.debug("Partes decodificadas de moodlemobile://: %d bloques", len(parts))
        # Probar segundo bloque (wstoken en Moodle 4.x) y si no, el primero
        candidates = [parts[1], parts[0]] if len(parts) > 1 else [parts[0]]
        last_err = None
        for cand in candidates:
            try:
                _verify_and_save_token(cand)
                return
            except Exception as exc:
                last_err = exc
                logger.warning("Candidato de token falló validación: %s", exc)
        raise RuntimeError(f"No se pudo validar el token recibido de moodlemobile://: {last_err}")

    if re.fullmatch(r"[0-9a-fA-F]{32}", raw_input):
        logger.info("Detectado formato hexadecimal de 32 caracteres. Probando como wstoken directo...")
        try:
            _verify_and_save_token(raw_input)
            return
        except Exception as exc:
            logger.info("No es un wstoken directo (%s). Probando como cookie de sesión...", exc)

    login_flow_from_cookie(raw_input)


def _verify_and_save_token(token: str) -> None:
    """Valida un wstoken contra la API y lo guarda si es correcto."""
    token = token.strip()
    os.environ["MOODLE_TOKEN"] = token
    info = call_moodle_api("core_webservice_get_site_info")
    save_token(token, info)
    print(f"\n[OK] Autenticación completada con éxito para: {info.get('fullname')} ({info.get('username')})")
    print(f"Token permanente guardado en: {TOKEN_FILE}")


def login_flow_from_cookie(cookie_val: str) -> None:
    """Extrae automáticamente el wstoken permanente usando una cookie de sesión MoodleSessionaulavirtualuji."""
    cookie_val = cookie_val.strip()
    logger.info("Intercambiando cookie MoodleSessionaulavirtualuji (len=%d) en launch.php...", len(cookie_val))
    session = requests.Session()
    session.cookies.set("MoodleSessionaulavirtualuji", cookie_val, domain="aulavirtual.uji.es")
    passport = str(int(time.time()))
    url = f"{MOODLE_BASE_URL}/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport={passport}"

    resp = session.get(url, allow_redirects=False, timeout=20)
    loc = resp.headers.get("Location", "")
    logger.info("Respuesta de launch.php: HTTP %d | Location presente=%s", resp.status_code, "token=" in loc)

    if "token=" not in loc:
        logger.error("launch.php no devolvió token. Location=%s", loc)
        raise RuntimeError(
            f"No se pudo obtener el token desde launch.php (HTTP {resp.status_code}, Location={loc}). "
            "Verifica que la sesión del Aula Virtual siga activa en el navegador."
        )

    process_auth_input(loc)


def show_logs(lines: int = 50) -> None:
    """Muestra las últimas líneas del archivo de trazabilidad."""
    if not LOG_FILE.exists():
        print(f"Aún no existe archivo de logs en: {LOG_FILE}")
        return
    all_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"=== Últimas {min(lines, len(all_lines))} líneas de {LOG_FILE} ===")
    for ln in all_lines[-lines:]:
        print(ln)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Aula Virtual UJI MCP & CLI")
    parser.add_argument("--debug", action="store_true", help="Activa trazabilidad detallada (logs en consola y archivo)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("login", help="Inicia sesión interactiva con tu cuenta de la UJI")
    p_handle = sub.add_parser("handle-url", help="Maneja la URL moodlemobile:// lanzada por el navegador")
    p_handle.add_argument("url", help="URL completa")

    p_cookie = sub.add_parser("from-cookie", help="Autentica pasando la cookie MoodleSessionaulavirtualuji")
    p_cookie.add_argument("cookie", help="Valor de la cookie de sesión")

    p_token = sub.add_parser("set-token", help="Configura y valida el wstoken de Moodle directamente")
    p_token.add_argument("token", help="Clave de 32 caracteres")

    sub.add_parser("whoami", help="Verifica el perfil del usuario autenticado")
    sub.add_parser("courses", help="Lista las asignaturas matriculadas")

    p_assign = sub.add_parser("assignments", help="Lista tareas y prácticas pendientes")
    p_assign.add_argument("--course", default="", help="Código de asignatura (ej. SJK006)")

    sub.add_parser("deadlines", help="Muestra las próximas fechas de entrega del calendario")

    p_sync = sub.add_parser("sync", help="Sincroniza tareas del Aula Virtual con Google Tasks")
    p_sync.add_argument("--list-title", default="Aula Virtual UJI")

    p_logs = sub.add_parser("logs", help="Muestra el registro de trazabilidad (aulavirtual.log)")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Número de líneas a mostrar")

    args = parser.parse_args()
    if args.debug:
        enable_debug_logging()

    logger.debug("CLI invocado: argv=%s cwd=%s", sys.argv, Path.cwd())

    if args.cmd == "login":
        interactive_login()
    elif args.cmd == "handle-url":
        logger.info("handle-url invocado desde Windows con URL de longitud %d", len(args.url))
        try:
            process_auth_input(args.url)
        except Exception as exc:
            logger.error("Fallo crítico en handle-url: %s\n%s", exc, traceback.format_exc())
            raise
    elif args.cmd == "from-cookie":
        process_auth_input(args.cookie)
    elif args.cmd == "set-token":
        _verify_and_save_token(args.token)
    elif args.cmd == "whoami":
        print(json.dumps(get_user_profile(), indent=2, ensure_ascii=False))
    elif args.cmd == "courses":
        print(json.dumps(list_courses(), indent=2, ensure_ascii=False))
    elif args.cmd == "assignments":
        print(json.dumps(get_assignments(args.course), indent=2, ensure_ascii=False))
    elif args.cmd == "deadlines":
        print(json.dumps(get_upcoming_deadlines(), indent=2, ensure_ascii=False))
    elif args.cmd == "sync":
        print(json.dumps(sync_assignments_to_gtasks(args.list_title), indent=2, ensure_ascii=False))
    elif args.cmd == "logs":
        show_logs(args.lines)
    else:
        if mcp:
            logger.info("Iniciando servidor MCP uji-aulavirtual sobre stdio")
            mcp.run()
        else:
            parser.print_help()


if __name__ == "__main__":
    _cli()
