"""Agente Comercial IA de CDS - Cercos de Seguridad — bucle conversacional sobre la API de Claude.

Mantiene la conversación multi-turno y ejecuta las herramientas (catálogo, cotización,
enlaces de compra, Kommo) mediante un agentic loop manual.

Uso (CLI):  python -m agente.agente
Requiere:   ANTHROPIC_API_KEY en el entorno (o `ant auth login`).
"""
from __future__ import annotations

import base64
import mimetypes
import os
import sys

import anthropic

from . import herramientas

# Carga ANTHROPIC_API_KEY (y demás) desde un archivo .env si python-dotenv está instalado.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

MODELO = os.getenv("AGENTE_MODELO", "claude-sonnet-4-6")
MAX_TOKENS = 4096
EFFORT = os.getenv("AGENTE_EFFORT", "medium")  # low | medium | high

_AGENTE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROMPT_PATH = os.path.join(_AGENTE_DIR, "system_prompt.md")
_EMPRESA_PATH = os.path.join(_AGENTE_DIR, "empresa.md")


def cargar_system_prompt() -> str:
    """Prompt de sistema = persona/reglas + (si existe) la info de la empresa."""
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        prompt = f.read()
    if os.path.exists(_EMPRESA_PATH):
        with open(_EMPRESA_PATH, encoding="utf-8") as f:
            prompt += "\n\n---\n\n" + f.read()
    return prompt


def _bloque_imagen(img) -> dict:
    """Convierte una imagen en un content block de la API de Claude.

    Acepta: ruta de archivo local (str), URL http(s) (str), bytes, o dict
    {"base64": ..., "media_type": ...} / {"url": ...}. Útil para fotos de WhatsApp.
    """
    if isinstance(img, dict):
        if "url" in img:
            return {"type": "image", "source": {"type": "url", "url": img["url"]}}
        return {"type": "image", "source": {"type": "base64",
                "media_type": img.get("media_type", "image/jpeg"), "data": img["base64"]}}
    if isinstance(img, (bytes, bytearray)):
        data = base64.standard_b64encode(bytes(img)).decode("utf-8")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
    if isinstance(img, str) and img.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": img}}
    media = mimetypes.guess_type(img)[0] or "image/jpeg"
    with open(img, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


class AgenteComercial:
    """Encapsula el estado de una conversación con un cliente."""

    def __init__(self, client: anthropic.Anthropic | None = None, on_tool=None,
                 canal: str | None = None, extra_system: str | None = None) -> None:
        self.client = client or anthropic.Anthropic()
        self.system = cargar_system_prompt()
        # `extra_system` permite adaptar el comportamiento por canal (p. ej. formato WhatsApp,
        # o inyectar el número de teléfono del cliente).
        if extra_system:
            self.system += "\n\n---\n\n" + extra_system
        self.canal = canal
        self.messages: list[dict] = []
        # Archivos que envía el cliente (fotos, PDF), para adjuntarlos al lead en Kommo.
        self.archivos_cliente: list[dict] = []
        # Callback opcional (nombre, entrada, salida_str) para observar el uso de herramientas.
        self.on_tool = on_tool

    def adjuntar_archivo(self, datos: bytes, filename: str, mime: str) -> None:
        """Registra un archivo que envió el cliente (para adjuntarlo al lead si se deriva)."""
        self.archivos_cliente.append({"datos": datos, "filename": filename, "mime": mime})

    def responder(self, mensaje_usuario: str, imagenes=None, adjuntos=None) -> str:
        """Procesa un mensaje del cliente y devuelve la respuesta de texto del agente.

        `imagenes` (opcional) es una lista de fotos del cliente — rutas locales, URLs http(s),
        bytes o dicts {"base64", "media_type"} / {"url"}. Pensado para fotos de WhatsApp
        (el terreno, el cierre actual, el portón). Si se entregan, se adjuntan al turno del cliente.
        """
        contenido = []
        if adjuntos:  # bloques ya armados (document/image), p. ej. de un PDF o Word
            contenido.extend(adjuntos)
        if imagenes:
            contenido.extend(_bloque_imagen(img) for img in imagenes)
        if contenido:
            contenido.append({"type": "text", "text": mensaje_usuario})
            self.messages.append({"role": "user", "content": contenido})
        else:
            self.messages.append({"role": "user", "content": mensaje_usuario})

        # Agentic loop: repetir mientras Claude pida ejecutar herramientas.
        while True:
            resp = self.client.messages.create(
                model=MODELO,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT},
                tools=herramientas.TOOLS,
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "refusal":
                return "(El asistente no puede continuar con esta solicitud.)"

            if resp.stop_reason != "tool_use":
                return self._texto(resp.content)

            # Ejecutar todas las herramientas solicitadas y devolver resultados.
            tool_results = []
            for bloque in resp.content:
                if bloque.type == "tool_use":
                    entrada = dict(bloque.input)
                    # Al registrar un lead, adjuntar la conversación completa y los archivos del cliente.
                    if bloque.name == "registrar_lead_kommo":
                        entrada["_conversacion"] = self._transcripcion()
                        entrada["_archivos"] = self.archivos_cliente
                    salida = herramientas.ejecutar(bloque.name, entrada)
                    if self.on_tool:
                        self.on_tool(bloque.name, bloque.input, salida)
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": bloque.id, "content": salida}
                    )
            self.messages.append({"role": "user", "content": tool_results})

    @staticmethod
    def _texto(content) -> str:
        return "\n".join(b.text for b in content if b.type == "text").strip()

    def _transcripcion(self) -> str:
        """Arma la transcripción legible de la conversación (para adjuntar al lead)."""
        def tipo(b):
            return b.get("type") if isinstance(b, dict) else getattr(b, "type", None)

        def texto(b):
            return b.get("text") if isinstance(b, dict) else getattr(b, "text", "")

        lineas = []
        for m in self.messages:
            c = m["content"]
            if m["role"] == "user":
                if isinstance(c, str):
                    lineas.append(f"Cliente: {c}")
                elif isinstance(c, list):
                    tipos = [tipo(b) for b in c]
                    if "tool_result" in tipos:
                        continue  # resultado de herramienta: interno, no va
                    txt = " ".join(t for t in (texto(b) for b in c if tipo(b) == "text") if t)
                    if "document" in tipos:
                        prefijo = "Cliente: [envió un documento] "
                    elif "image" in tipos:
                        prefijo = "Cliente: [envió una foto] "
                    else:
                        prefijo = "Cliente: "
                    lineas.append((prefijo + txt).strip())
            elif m["role"] == "assistant":
                if isinstance(c, str):
                    if c.startswith("[Vendedor]"):
                        lineas.append("Vendedor: " + c[len("[Vendedor]"):].strip())
                    else:
                        lineas.append(f"Agente: {c}")
                elif isinstance(c, list):
                    for b in c:
                        if tipo(b) == "text" and texto(b):
                            lineas.append(f"Agente: {texto(b)}")
        return "\n".join(lineas)


def _repl() -> None:
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        print("⚠️  Falta ANTHROPIC_API_KEY en el entorno (o ejecuta `ant auth login`).", file=sys.stderr)
        sys.exit(1)

    agente = AgenteComercial()
    print("🔒 Agente Comercial CDS - Cercos de Seguridad — escribe tu consulta. (Ctrl-C o 'salir' para terminar)")
    print("   Tip: envía una foto con  /foto <ruta-imagen> <mensaje opcional>\n")
    # Saludo inicial proactivo.
    print("Agente:", agente.responder("Hola"), "\n")
    try:
        while True:
            try:
                entrada = input("Tú: ").strip()
            except EOFError:
                break
            if not entrada or entrada.lower() in {"salir", "exit", "quit"}:
                break
            if entrada.lower().startswith("/foto "):
                resto = entrada[len("/foto "):].strip()
                partes = resto.split(maxsplit=1)
                ruta = partes[0]
                texto = partes[1] if len(partes) > 1 else "Te envío una foto."
                print("\nAgente:", agente.responder(texto, imagenes=[ruta]), "\n")
                continue
            print("\nAgente:", agente.responder(entrada), "\n")
    except KeyboardInterrupt:
        pass
    print("\n👋 ¡Gracias por visitar CDS - Cercos de Seguridad!")


if __name__ == "__main__":
    _repl()
