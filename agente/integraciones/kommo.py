"""Integración con Kommo CRM.

- Si hay credenciales (`KOMMO_SUBDOMAIN` + `KOMMO_TOKEN`), crea el lead REAL vía la API v4:
  lead + contacto (nombre, teléfono, correo) + una nota con todo el detalle del proyecto.
  El Round Robin lo dispara Kommo automáticamente al entrar el lead al pipeline configurado.
- Si no hay credenciales, cae a modo SIMULADO (registra en leads_simulados.jsonl).

Variables de entorno:
    KOMMO_SUBDOMAIN   p.ej. "cds"  (de cds.kommo.com)
    KOMMO_TOKEN       token de larga duración (Bearer) de una integración privada
    KOMMO_PIPELINE_ID (opcional) pipeline donde crear el lead
    KOMMO_STATUS_ID   (opcional) etapa inicial del lead
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

import httpx

_EJECUTIVOS = ["Ejecutivo 1", "Ejecutivo 2", "Ejecutivo 3", "Ejecutivo 4", "Ejecutivo 5"]
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LEADS_PATH = os.path.join(_PROJECT_ROOT, "leads_simulados.jsonl")

_PLACEHOLDER_TEL = {"(whatsapp del cliente)", "(sin teléfono)", ""}


def crear_lead(datos: dict) -> dict:
    """Crea un Lead en Kommo (real si hay credenciales; simulado si no)."""
    subdominio = os.getenv("KOMMO_SUBDOMAIN")
    token = os.getenv("KOMMO_TOKEN")
    if subdominio and token:
        try:
            return _crear_lead_real(datos, subdominio, token)
        except Exception as e:  # noqa: BLE001 - reportar el error sin romper la conversación
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "modo": "real (falló)"}
    return _crear_lead_simulado(datos)


# --- Real (API Kommo v4) -----------------------------------------------------

def _nota_detalle(datos: dict) -> str:
    campos = [
        ("Tipo de proyecto", datos.get("tipo_proyecto")),
        ("Producto recomendado", datos.get("producto_recomendado")),
        ("Metros cuadrados", datos.get("metros_cuadrados")),
        ("Ciudad", datos.get("ciudad")),
        ("Empresa", datos.get("empresa")),
        ("Fecha estimada", datos.get("fecha_estimada")),
        ("Nivel de intención", datos.get("nivel_intencion")),
        ("Observaciones", datos.get("observaciones")),
    ]
    lineas = [f"{k}: {v}" for k, v in campos if v not in (None, "")]
    return "Lead generado por el Agente IA.\n" + "\n".join(lineas)


def _crear_lead_real(datos: dict, subdominio: str, token: str) -> dict:
    base = f"https://{subdominio}.kommo.com"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    nombre = datos.get("nombre") or "Lead web"
    tipo = datos.get("tipo_proyecto") or "consulta"
    nivel = datos.get("nivel_intencion") or ""

    lead: dict = {"name": f"{tipo.capitalize()} — {nombre}"}
    if os.getenv("KOMMO_PIPELINE_ID"):
        lead["pipeline_id"] = int(os.getenv("KOMMO_PIPELINE_ID"))
    if os.getenv("KOMMO_STATUS_ID"):
        lead["status_id"] = int(os.getenv("KOMMO_STATUS_ID"))

    # Contacto con teléfono/correo (campos estándar de Kommo).
    contacto_cf = []
    tel = (datos.get("telefono") or "").strip()
    if tel.lower() not in _PLACEHOLDER_TEL:
        contacto_cf.append({"field_code": "PHONE", "values": [{"value": tel, "enum_code": "WORK"}]})
    if datos.get("correo"):
        contacto_cf.append({"field_code": "EMAIL", "values": [{"value": datos["correo"], "enum_code": "WORK"}]})

    embedded: dict = {"tags": [{"name": tipo}] + ([{"name": nivel}] if nivel else [])}
    contacto = {"name": nombre}
    if contacto_cf:
        contacto["custom_fields_values"] = contacto_cf
    embedded["contacts"] = [contacto]
    lead["_embedded"] = embedded

    with httpx.Client(timeout=20) as client:
        # /complex crea lead + contacto en una sola llamada.
        r = client.post(f"{base}/api/v4/leads/complex", headers=headers, json=[lead])
        r.raise_for_status()
        creado = r.json()[0]
        lead_id = creado["id"]

        # Notas: (1) resumen del proyecto y (2) la conversación completa con el agente.
        notas = [{"note_type": "common", "params": {"text": _nota_detalle(datos)}}]
        conversacion = datos.get("_conversacion")
        if conversacion:
            notas.append({
                "note_type": "common",
                "params": {"text": "🗨️ Conversación completa con el agente:\n\n" + conversacion[:60000]},
            })
        client.post(f"{base}/api/v4/leads/{lead_id}/notes", headers=headers, json=notas)

    # Adjuntar los archivos que envió el cliente (fotos, PDF) para que el vendedor los descargue.
    archivos = datos.get("_archivos") or []
    if archivos:
        _adjuntar_archivos(base, token, lead_id, archivos)

    return {
        "ok": True,
        "lead_id": lead_id,
        "url": f"{base}/leads/detail/{lead_id}",
        "round_robin": "lo asigna Kommo según la distribución del pipeline",
        "modo": "real",
        "nota": "Lead creado en Kommo.",
    }


def telefono_de_lead(lead_id: int | str) -> str | None:
    """Obtiene el teléfono del contacto principal de un lead (para el handoff)."""
    sub = os.getenv("KOMMO_SUBDOMAIN")
    tok = os.getenv("KOMMO_TOKEN")
    if not (sub and tok):
        return None
    base = f"https://{sub}.kommo.com"
    h = {"Authorization": f"Bearer {tok}"}
    try:
        lead = httpx.get(f"{base}/api/v4/leads/{lead_id}?with=contacts", headers=h, timeout=20).json()
        contactos = lead.get("_embedded", {}).get("contacts", [])
        if not contactos:
            return None
        cid = contactos[0]["id"]
        c = httpx.get(f"{base}/api/v4/contacts/{cid}", headers=h, timeout=20).json()
        for cf in c.get("custom_fields_values") or []:
            if cf.get("field_code") == "PHONE":
                for v in cf.get("values", []):
                    if v.get("value"):
                        return str(v["value"])
    except Exception:  # noqa: BLE001
        return None
    return None


# --- Adjuntar archivos al lead (Drive de Kommo) ------------------------------

def _adjuntar_archivos(base: str, token: str, lead_id: int, archivos: list) -> None:
    """Sube cada archivo al Drive de Kommo y lo vincula al lead (para que el vendedor lo descargue)."""
    hj = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        drive = httpx.get(f"{base}/api/v4/account?with=drive_url",
                          headers={"Authorization": f"Bearer {token}"}, timeout=20).json().get("drive_url")
    except Exception:  # noqa: BLE001
        return
    if not drive:
        return
    for arch in archivos:
        try:
            uuid = _subir_al_drive(drive, token, arch["datos"], arch.get("filename", "archivo"),
                                   arch.get("mime", "application/octet-stream"))
            if uuid:
                httpx.put(f"{base}/api/v4/leads/{lead_id}/files", headers=hj, json=[{"file_uuid": uuid}], timeout=20)
        except Exception:  # noqa: BLE001 - no romper el lead por un archivo
            continue


def _subir_al_drive(drive: str, token: str, datos: bytes, filename: str, mime: str) -> str | None:
    hj = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    hbin = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
    sesion = httpx.post(f"{drive}/v1.0/sessions", headers=hj,
                        json={"file_name": filename, "file_size": len(datos), "content_type": mime},
                        timeout=20).json()
    url = sesion["upload_url"]
    part = sesion["max_part_size"]
    uuid = None
    off = 0
    while off < len(datos):
        chunk = datos[off:off + part]
        j = httpx.post(url, headers=hbin, content=chunk, timeout=60).json()
        off += len(chunk)
        if j.get("next_url"):
            url = j["next_url"]
        if j.get("uuid"):
            uuid = j["uuid"]
    return uuid


# --- Simulado ----------------------------------------------------------------

def _siguiente_ejecutivo() -> str:
    n = 0
    if os.path.exists(_LEADS_PATH):
        with open(_LEADS_PATH, encoding="utf-8") as f:
            n = sum(1 for _ in f)
    return _EJECUTIVOS[n % len(_EJECUTIVOS)]


def _crear_lead_simulado(datos: dict) -> dict:
    lead_id = "LEAD-" + uuid.uuid4().hex[:8].upper()
    ejecutivo = _siguiente_ejecutivo()
    registro = {
        "lead_id": lead_id,
        "creado": datetime.now().isoformat(timespec="seconds"),
        "ejecutivo_asignado": ejecutivo,
        "datos": datos,
        "modo": "SIMULADO",
    }
    with open(_LEADS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "lead_id": lead_id,
        "ejecutivo_asignado": ejecutivo,
        "round_robin": "disparado",
        "modo": "SIMULADO",
        "nota": "Lead registrado en modo SIMULADO (sin credenciales Kommo).",
    }
