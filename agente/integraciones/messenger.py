"""Cliente de la Messenger Platform (Meta): enviar mensajes por Facebook Messenger e Instagram.

Un mismo **token de Página** (con permisos `pages_messaging` + `instagram_manage_messages`)
sirve para AMBOS canales, porque la cuenta de Instagram Business está vinculada a la Página.
El envío usa `/me/messages`, que se resuelve a la Página desde el token.

Variables de entorno:
    PAGE_ACCESS_TOKEN        token de acceso de la Página (permanente, de System User)
    MESSENGER_VERIFY_TOKEN   texto secreto para verificar el webhook (lo defines tú)
"""
from __future__ import annotations

import os

import httpx

_GRAPH = "https://graph.facebook.com/v21.0"


def _token() -> str:
    return os.environ["PAGE_ACCESS_TOKEN"]


def enviar_texto(destino: str, texto: str) -> dict:
    """Envía un mensaje de texto al usuario `destino` (PSID de Messenger o IGSID de Instagram)."""
    url = f"{_GRAPH}/me/messages"
    payload = {
        "recipient": {"id": destino},
        "messaging_type": "RESPONSE",
        "message": {"text": texto[:2000]},
    }
    r = httpx.post(url, params={"access_token": _token()}, json=payload, timeout=30)
    resp = r.json() if r.content else {}
    return {"status": r.status_code, "resp": resp, "message_id": resp.get("message_id")}


def descargar_media(url: str) -> tuple[bytes, str]:
    """Descarga un adjunto (imagen) desde la URL que entrega el webhook. Devuelve (bytes, mime)."""
    r = httpx.get(url, timeout=60)
    mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
    return r.content, mime
