"""Webhook de Facebook Messenger e Instagram para el Agente Comercial de CDS - Cercos de Seguridad.

Comparte el mismo agente (`AgenteComercial`) que WhatsApp. Se monta en la app de
`servidor_whatsapp.py` con `app.include_router(router)`, así un solo servicio (Render) atiende
los tres canales.

- GET  /messenger/webhook  → verificación del webhook (Meta lo llama al configurarlo).
- POST /messenger/webhook  → recibe mensajes de Messenger (objeto "page") e Instagram
  (objeto "instagram"), los pasa al agente y responde por el mismo canal.

A diferencia de WhatsApp, aquí el ID del cliente (PSID/IGSID) NO es un teléfono, así que el
agente PIDE el teléfono antes de registrar un lead (ver instrucción de canal).

Requiere en .env: PAGE_ACCESS_TOKEN, MESSENGER_VERIFY_TOKEN (y ANTHROPIC_API_KEY, Kommo).
"""
from __future__ import annotations

import base64
import os
import time

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agente.agente import AgenteComercial
from agente.integraciones import messenger

router = APIRouter()

# Formato para Messenger/Instagram: texto plano, sin markdown; y PEDIR el teléfono antes de derivar.
_FORMATO_MSG = (
    "## Canal: {canal}\n"
    "Respondes por {canal} (mensajería de Meta). Escribe en texto plano y natural, en mensajes "
    "cortos. NO uses Markdown (ni **, ni #, ni tablas): este canal no lo renderiza. NO uses emojis. "
    "Pega los enlaces tal cual.\n"
    "IMPORTANTE: por este canal NO tienes el teléfono del cliente. Antes de registrar un lead, "
    "PÍDELE su número de teléfono (además del nombre); no derives a Kommo sin un teléfono de contacto."
)

# Sesiones por usuario de Messenger/Instagram (en memoria; se reinician con el proceso).
_sesiones: dict[str, dict] = {}


def _sesion(user_id: str, canal: str) -> dict:
    s = _sesiones.get(user_id)
    if s is None:
        nombre_canal = "Instagram" if canal == "instagram" else "Facebook Messenger"
        agente = AgenteComercial(canal=canal, extra_system=_FORMATO_MSG.format(canal=nombre_canal))
        s = {"agente": agente, "last": time.time()}
        _sesiones[user_id] = s
    return s


@router.get("/messenger/webhook", response_class=PlainTextResponse)
def verificar(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == os.getenv("MESSENGER_VERIFY_TOKEN"):
        return PlainTextResponse(p.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/messenger/webhook")
async def recibir(request: Request, bg: BackgroundTasks):
    data = await request.json()
    obj = data.get("object")  # "page" (Messenger) o "instagram"
    canal = "instagram" if obj == "instagram" else "messenger"
    try:
        for entry in data.get("entry", []):
            for evt in entry.get("messaging") or []:
                sender = (evt.get("sender") or {}).get("id")
                msg = evt.get("message") or {}
                # Ignorar ecos (mensajes salientes de la propia Página) y eventos sin mensaje.
                if not sender or not msg or msg.get("is_echo"):
                    continue
                bg.add_task(_procesar, sender, msg, canal)
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    # Responder 200 de inmediato; el agente procesa en segundo plano.
    return JSONResponse({"ok": True})


def _procesar(user_id: str, msg: dict, canal: str) -> None:
    agente = _sesion(user_id, canal)["agente"]
    try:
        texto = msg.get("text")
        imagenes = []
        for att in msg.get("attachments") or []:
            if att.get("type") == "image":
                url = (att.get("payload") or {}).get("url")
                if url:
                    datos, mime = messenger.descargar_media(url)
                    agente.adjuntar_archivo(datos, "foto_cliente.jpg", mime)  # para adjuntar al lead
                    imagenes.append({"base64": base64.standard_b64encode(datos).decode("utf-8"), "media_type": mime})
        if imagenes:
            respuesta = agente.responder(texto or "(el cliente envió una imagen)", imagenes=imagenes)
        elif texto:
            respuesta = agente.responder(texto)
        else:
            respuesta = "Por ahora leo mensajes de texto e imágenes. ¿En qué te ayudo?"
        if respuesta:
            messenger.enviar_texto(user_id, respuesta)
    except Exception as e:  # noqa: BLE001 - no romper el webhook por un mensaje
        print(f"[messenger] error procesando {user_id} ({canal}): {type(e).__name__}: {e}")
