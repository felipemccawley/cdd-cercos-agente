"""Procesa documentos que envía el cliente (PDF, Word) para que el agente los entienda.

- PDF: se pasa directo a Claude como bloque `document` (lo lee de forma nativa).
- Word (.docx): se extrae el texto y las imágenes embebidas (las bases de licitación suelen
  venir como imágenes dentro del Word), que se pasan como bloques `image`.
- Otros: se avisa que no se pudo leer y se pide reenviar como PDF/Word/foto.

Devuelve (texto_extra, bloques) para adjuntar al mensaje del agente.
"""
from __future__ import annotations

import base64
import html
import io
import re
import zipfile

_EXT_IMG = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}


def _b64(datos: bytes) -> str:
    return base64.standard_b64encode(datos).decode("utf-8")


def procesar(datos: bytes, mime: str, filename: str = "documento") -> tuple[str, list]:
    fl = (filename or "").lower()
    if mime == "application/pdf" or fl.endswith(".pdf"):
        bloque = {"type": "document", "source": {"type": "base64",
                  "media_type": "application/pdf", "data": _b64(datos)}}
        return (f"(El cliente adjuntó un PDF: {filename})", [bloque])

    if fl.endswith(".docx") or "wordprocessingml" in mime:
        texto, imagenes = _extraer_docx(datos)
        bloques = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": _b64(b)}}
                   for (b, m) in imagenes]
        nota = f"(El cliente adjuntó un documento Word: {filename}."
        if texto.strip():
            nota += " Texto del documento:\n" + texto.strip()
        if imagenes:
            nota += f"\n[Contiene {len(imagenes)} imagen(es), adjuntas a continuación]"
        nota += ")"
        return (nota, bloques)

    return (
        f"(El cliente adjuntó '{filename}' ({mime}), que no puedo leer. Pídele con amabilidad "
        "que lo reenvíe como PDF, Word o una foto.)",
        [],
    )


def _extraer_docx(datos: bytes) -> tuple[str, list]:
    texto = ""
    imagenes: list = []
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        try:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
            partes = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S)
            crudo = " ".join(partes)
            crudo = re.sub(r"<[^>]+>", "", crudo)  # quitar etiquetas XML residuales
            texto = re.sub(r"\s+", " ", html.unescape(crudo)).strip()
            if len(texto) < 15:  # doc de puras imágenes: sin texto útil
                texto = ""
        except KeyError:
            pass
        for n in z.namelist():
            if n.startswith("word/media/"):
                ext = n.rsplit(".", 1)[-1].lower()
                if ext in _EXT_IMG:
                    imagenes.append((z.read(n), _EXT_IMG[ext]))
    return texto, imagenes[:5]  # tope de 5 imágenes para no sobrecargar
