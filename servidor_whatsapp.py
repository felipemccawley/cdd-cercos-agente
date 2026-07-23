"""Webhook de WhatsApp (Meta Cloud API) para el Agente Comercial de CDS - Cercos de Seguridad.

- GET  /whatsapp/webhook  → verificación del webhook (Meta lo llama al configurarlo).
- POST /whatsapp/webhook  → recibe mensajes (texto y fotos), los pasa al agente y responde.

Cada número de WhatsApp tiene su propia conversación (sesión en memoria). El número del cliente
se usa como su teléfono al registrar leads (no se lo preguntamos).

Correr local:  uvicorn servidor_whatsapp:app --port 8000
Requiere en .env: ANTHROPIC_API_KEY y las variables WHATSAPP_* (y opcionalmente Kommo).
"""
from __future__ import annotations

import asyncio
import base64
import os
import time

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agente.agente import AgenteComercial
from agente.integraciones import documentos, kommo, whatsapp

app = FastAPI(title="CDS - Cercos de Seguridad (WhatsApp + Messenger + Instagram)")

# Canal Messenger/Instagram (mismo agente, otro webhook). Se monta aquí para que un solo
# servicio atienda los tres canales. Si el módulo no está disponible, el server sigue con WhatsApp.
try:
    from canal_messenger import router as messenger_router

    app.include_router(messenger_router)
except Exception as _e:  # noqa: BLE001
    print(f"[messenger] router no montado: {type(_e).__name__}: {_e}")

# --- Seguimiento de conversaciones silenciosas -------------------------------
# Si el cliente deja de responder: a los SEGUIMIENTO_MINUTOS se le envía UN mensaje suave;
# si sigue en silencio a los RESCATE_MINUTOS, se registra un lead de rescate en Kommo con la
# transcripción y archivos, para que un vendedor lo retome. (Requiere hosting siempre activo.)
SEGUIMIENTO_MINUTOS = int(os.getenv("SEGUIMIENTO_MINUTOS", "45"))
RESCATE_MINUTOS = int(os.getenv("RESCATE_MINUTOS", "240"))
MENSAJE_SEGUIMIENTO = os.getenv(
    "MENSAJE_SEGUIMIENTO",
    "Hola, ¿seguimos con tu cotización de cerco? Cualquier duda que tengas, aquí estoy.",
)

# --- Handoff a humano ---------------------------------------------------------
# Si un vendedor responde desde otra herramienta (p. ej. Kommo) en la misma conversación,
# el bot se PAUSA en ese chat por PAUSA_HUMANO_HORAS (cada intervención humana renueva la pausa).
PAUSA_HUMANO_HORAS = float(os.getenv("PAUSA_HUMANO_HORAS", "6"))

# Instrucción de formato para el canal WhatsApp (texto plano, mensajes cortos, sin emojis).
_FORMATO_WA = (
    "## Canal: WhatsApp\n"
    "Respondes por WhatsApp. Escribe en texto plano y natural, en mensajes cortos. NO uses "
    "Markdown: nada de **, de #, de tablas ni de listas con guiones. Para enfatizar puedes usar "
    "*una palabra* entre asteriscos simples (negrita de WhatsApp), con moderación. NO uses emojis. "
    "Usa saltos de línea con mesura. Pega los enlaces tal cual, sin corchetes."
)

# Sesiones por número de WhatsApp (en memoria; se reinician si se reinicia el proceso).
_sesiones: dict[str, dict] = {}


def _sesion(wa_id: str) -> dict:
    s = _sesiones.get(wa_id)
    if s is None:
        extra = (
            _FORMATO_WA
            + f"\n\nEl número de WhatsApp del cliente es {wa_id}. Úsalo como su teléfono al "
            "registrar un lead; no se lo preguntes."
        )
        agente = AgenteComercial(canal="whatsapp", extra_system=extra)
        s = {"agente": agente, "last": time.time(), "avisado": False, "cerrada": False,
             "rescatada": False, "humano_hasta": 0.0, "ids_bot": set()}

        def _marcar_cierre(nombre, entrada, salida, _s=s):
            # En la fase de lanzamiento, el cierre es la derivación a una persona: si se registró
            # el lead, la conversación quedó resuelta y no corresponde seguimiento ni rescate.
            if nombre == "registrar_lead_kommo" and '"ok": true' in salida:
                _s["cerrada"] = True

        agente.on_tool = _marcar_cierre
        _sesiones[wa_id] = s
    return s


def _agente(wa_id: str) -> AgenteComercial:
    return _sesion(wa_id)["agente"]


@app.get("/whatsapp/webhook", response_class=PlainTextResponse)
def verificar(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == os.getenv("WHATSAPP_VERIFY_TOKEN"):
        return PlainTextResponse(p.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


@app.post("/whatsapp/webhook")
async def recibir(request: Request, bg: BackgroundTasks):
    data = await request.json()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages") or []:
                    bg.add_task(_procesar, msg.get("from"), msg)
                for eco in value.get("message_echoes") or []:
                    bg.add_task(_procesar_eco, eco)
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    # Responder 200 de inmediato; el agente procesa en segundo plano.
    return JSONResponse({"ok": True})


def _procesar_eco(eco: dict) -> None:
    """Mensaje SALIENTE del número. Si no lo envió el bot, un humano tomó la conversación."""
    wa_id = eco.get("to")
    if not wa_id:
        return
    s = _sesion(wa_id)
    if eco.get("id") and eco["id"] in s["ids_bot"]:
        return  # es un mensaje del propio bot: ignorar
    s["humano_hasta"] = time.time() + PAUSA_HUMANO_HORAS * 3600
    texto = (eco.get("text") or {}).get("body") or f"[mensaje {eco.get('type','?')}]"
    if s["agente"].messages:
        s["agente"].messages.append({"role": "assistant", "content": f"[Vendedor] {texto}"})
    print(f"[handoff] humano atendiendo a {wa_id}; bot en pausa {PAUSA_HUMANO_HORAS} h")


def _procesar(wa_id: str, msg: dict) -> None:
    tipo = msg.get("type")
    s = _sesion(wa_id)
    s["last"] = time.time()
    agente = s["agente"]
    try:
        # Conversación en manos de un humano: registrar sin responder.
        if time.time() < s["humano_hasta"]:
            if tipo == "text":
                agente.messages.append({"role": "user", "content": msg["text"]["body"]})
            elif tipo == "image":
                datos, mime = whatsapp.descargar_media(msg["image"]["id"])
                agente.adjuntar_archivo(datos, "foto_cliente.jpg", mime)
                agente.messages.append({"role": "user", "content": "[envió una foto] " + (msg["image"].get("caption") or "")})
            elif tipo == "document":
                doc = msg["document"]
                datos, mime = whatsapp.descargar_media(doc["id"])
                agente.adjuntar_archivo(datos, doc.get("filename", "documento"), mime)
                agente.messages.append({"role": "user", "content": f"[envió un documento: {doc.get('filename','')}]"})
            return

        if tipo == "text":
            respuesta = agente.responder(msg["text"]["body"])
        elif tipo == "image":
            datos, mime = whatsapp.descargar_media(msg["image"]["id"])
            agente.adjuntar_archivo(datos, "foto_cliente.jpg", mime)  # para adjuntar al lead
            b64 = base64.standard_b64encode(datos).decode("utf-8")
            caption = msg["image"].get("caption") or "(el cliente envió una foto)"
            respuesta = agente.responder(caption, imagenes=[{"base64": b64, "media_type": mime}])
        elif tipo == "document":
            doc = msg["document"]
            datos, mime = whatsapp.descargar_media(doc["id"])
            filename = doc.get("filename", "documento")
            agente.adjuntar_archivo(datos, filename, mime)  # para adjuntar al lead
            caption = doc.get("caption") or ""
            texto_extra, bloques = documentos.procesar(datos, mime, filename)
            respuesta = agente.responder(f"{caption}\n{texto_extra}".strip(), adjuntos=bloques)
        else:
            respuesta = "Por ahora leo mensajes de texto y fotos. ¿En qué te ayudo?"
        if respuesta:
            r = whatsapp.enviar_texto(wa_id, respuesta)
            if r.get("message_id"):
                s["ids_bot"].add(r["message_id"])  # para distinguir ecos propios de los del vendedor
    except Exception as e:  # noqa: BLE001 - no romper el webhook por un mensaje
        print(f"[whatsapp] error procesando {wa_id}: {type(e).__name__}: {e}")


# --- Endpoints de handoff (pausar/reanudar el bot en una conversación) --------
HANDOFF_CLAVE = os.getenv("HANDOFF_CLAVE", "")


def _normalizar_tel(t: str | None) -> str | None:
    import re as _re
    d = _re.sub(r"\D", "", t or "")
    if len(d) == 9 and d.startswith("9"):
        d = "56" + d  # celular chileno sin código de país
    return d or None


def _pausar(wa_id: str, horas: float, origen: str) -> dict:
    s = _sesion(wa_id)
    s["humano_hasta"] = time.time() + horas * 3600
    if s["agente"].messages:
        s["agente"].messages.append({"role": "assistant", "content": "[Vendedor] (tomó la conversación)"})
    print(f"[handoff/{origen}] bot en pausa {horas} h para {wa_id}")
    return {"ok": True, "tel": wa_id, "pausado_horas": horas}


@app.api_route("/handoff/pausa", methods=["GET", "POST"])
async def handoff_pausa(request: Request):
    p = request.query_params
    if not HANDOFF_CLAVE or p.get("clave") != HANDOFF_CLAVE:
        return JSONResponse({"ok": False, "error": "clave inválida"}, status_code=403)
    wa = _normalizar_tel(p.get("tel"))
    if not wa:
        return JSONResponse({"ok": False, "error": "falta ?tel="}, status_code=400)
    horas = float(p.get("horas") or PAUSA_HUMANO_HORAS)
    return JSONResponse(_pausar(wa, horas, "manual"))


@app.api_route("/handoff/reanudar", methods=["GET", "POST"])
async def handoff_reanudar(request: Request):
    p = request.query_params
    if not HANDOFF_CLAVE or p.get("clave") != HANDOFF_CLAVE:
        return JSONResponse({"ok": False, "error": "clave inválida"}, status_code=403)
    wa = _normalizar_tel(p.get("tel"))
    if not wa or wa not in _sesiones:
        return JSONResponse({"ok": False, "error": "sin sesión para ese tel"}, status_code=404)
    _sesiones[wa]["humano_hasta"] = 0.0
    print(f"[handoff/manual] bot reanudado para {wa}")
    return JSONResponse({"ok": True, "tel": wa, "reanudado": True})


@app.post("/handoff/kommo")
async def handoff_kommo(request: Request):
    """Webhook desde Kommo (Digital Pipeline → 'Enviar webhook' al mover el lead de etapa).
    Obtiene el teléfono del lead y pausa el bot para esa conversación."""
    if not HANDOFF_CLAVE or request.query_params.get("clave") != HANDOFF_CLAVE:
        return JSONResponse({"ok": False, "error": "clave inválida"}, status_code=403)
    form = dict(await request.form())
    lead_id = next((v for k, v in form.items() if k.startswith("leads[") and k.endswith("][id]")), None)
    if not lead_id:
        return JSONResponse({"ok": False, "error": "sin lead id en el payload"}, status_code=400)
    tel = kommo.telefono_de_lead(lead_id)
    wa = _normalizar_tel(tel)
    if not wa:
        return JSONResponse({"ok": False, "error": f"lead {lead_id} sin teléfono"}, status_code=404)
    return JSONResponse(_pausar(wa, PAUSA_HUMANO_HORAS, f"kommo lead {lead_id}"))


def _detectar_tipo(transcripcion: str) -> str:
    t = transcripcion.lower()
    if "licitaci" in t or "bases" in t or "municipal" in t:
        return "licitacion"
    if "358" in t or "alta seguridad" in t:
        return "cerco_358"
    if "3d" in t or "acmafor" in t or "1.8" in t or "2.08" in t or "cerco" in t or "panel" in t:
        return "cerco_3d"
    if "poste" in t or "repuesto" in t or "brazo" in t:
        return "componentes"
    return "otro"


def _rescatar(wa_id: str, s: dict) -> None:
    """Registra en Kommo un lead de rescate con lo que haya de la conversación."""
    ag = s["agente"]
    trans = ag._transcripcion()
    s["rescatada"] = True
    if not trans.strip():
        return
    res = kommo.crear_lead({
        "nombre": f"WhatsApp +{wa_id}",
        "telefono": f"+{wa_id}",
        "tipo_proyecto": _detectar_tipo(trans),
        "nivel_intencion": "MEDIA",
        "observaciones": ("CONVERSACIÓN INCOMPLETA — el cliente dejó de responder en WhatsApp. "
                          "Lead de rescate generado automáticamente; hacer seguimiento. "
                          "La conversación completa está en la nota adjunta."),
        "_conversacion": trans,
        "_archivos": ag.archivos_cliente,
    })
    print(f"[rescate] {wa_id} -> lead {res.get('lead_id')} ({res.get('modo')})")


def _revisar_sesiones() -> None:
    """Una pasada de revisión: envía seguimientos y rescata conversaciones abandonadas."""
    ahora = time.time()
    for wa_id, s in list(_sesiones.items()):
        try:
            inactivo_min = (ahora - s["last"]) / 60
            if s["cerrada"] or s["rescatada"]:
                if inactivo_min > 48 * 60:  # limpiar sesiones viejas
                    _sesiones.pop(wa_id, None)
                continue
            if time.time() < s["humano_hasta"]:
                continue  # la conversación la atiende un humano: no molestar
            if inactivo_min >= RESCATE_MINUTOS:
                _rescatar(wa_id, s)
            elif inactivo_min >= SEGUIMIENTO_MINUTOS and not s["avisado"]:
                r = whatsapp.enviar_texto(wa_id, MENSAJE_SEGUIMIENTO)
                if r.get("message_id"):
                    s["ids_bot"].add(r["message_id"])
                s["agente"].messages.append({"role": "assistant", "content": MENSAJE_SEGUIMIENTO})
                s["avisado"] = True
                print(f"[seguimiento] enviado a {wa_id}")
        except Exception as e:  # noqa: BLE001
            print(f"[vigilante] error con {wa_id}: {type(e).__name__}: {e}")


async def _vigilante() -> None:
    """Revisa cada 5 min las conversaciones en silencio."""
    while True:
        await asyncio.sleep(300)
        _revisar_sesiones()


@app.on_event("startup")
async def _iniciar_vigilante():
    asyncio.create_task(_vigilante())


@app.get("/")
def home():
    return {"servicio": "WhatsApp CDS - Cercos de Seguridad", "sesiones_activas": len(_sesiones),
            "seguimiento_min": SEGUIMIENTO_MINUTOS, "rescate_min": RESCATE_MINUTOS}
