"""Cliente de la WhatsApp Cloud API (Meta): enviar mensajes y descargar fotos.

Variables de entorno:
    WHATSAPP_TOKEN              token de acceso (temporal de prueba o permanente de System User)
    WHATSAPP_PHONE_NUMBER_ID    ID del número de teléfono (de la app de WhatsApp en Meta)
    WHATSAPP_VERIFY_TOKEN       texto secreto que tú inventas, para verificar el webhook
"""
from __future__ import annotations

import os

import httpx

_GRAPH = "https://graph.facebook.com/v21.0"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"}


def enviar_texto(destino: str, texto: str) -> dict:
    """Envía un mensaje de texto al número `destino` (wa_id)."""
    url = f"{_GRAPH}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": texto[:4096], "preview_url": True},
    }
    r = httpx.post(url, headers=_headers(), json=payload, timeout=30)
    resp = r.json() if r.content else {}
    try:
        message_id = resp["messages"][0]["id"]
    except (KeyError, IndexError, TypeError):
        message_id = None
    return {"status": r.status_code, "resp": resp, "message_id": message_id}


def descargar_media(media_id: str) -> tuple[bytes, str]:
    """Descarga una imagen enviada por el cliente. Devuelve (bytes, media_type)."""
    meta = httpx.get(f"{_GRAPH}/{media_id}", headers=_headers(), timeout=30).json()
    url = meta.get("url")
    mime = meta.get("mime_type", "image/jpeg")
    data = httpx.get(url, headers=_headers(), timeout=60).content
    return data, mime
