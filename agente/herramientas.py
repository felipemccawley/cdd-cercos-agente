"""Definición y ejecución de las herramientas (tools) que usa el agente.

El esquema JSON de cada tool se envía a la API de Claude; `ejecutar` despacha la
llamada a la función Python correspondiente y devuelve el resultado como string.
"""
from __future__ import annotations

import json
from typing import Any

from . import catalogo
from .integraciones import kommo, tienda

# --- Esquemas de herramientas (para la API de Claude) -----------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "buscar_productos",
        "description": (
            "Busca productos en el catálogo oficial de CDS - Cercos de Seguridad. Úsalo para "
            "listar opciones de una categoría o encontrar un producto. Devuelve un resumen (id, "
            "nombre, precios neto, specs). NUNCA inventes productos: usa solo lo que devuelve esto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": ["cercos_3d", "cercos_358", "componentes"],
                    "description": "Categoría a filtrar (opcional).",
                },
                "texto": {
                    "type": "string",
                    "description": "Texto libre para filtrar (p.ej. '358', 'poste', '2.08'). Opcional.",
                },
            },
        },
    },
    {
        "name": "obtener_ficha",
        "description": (
            "Devuelve la ficha técnica completa de un producto por su id (dimensiones, alambre, "
            "acabado, precios neto). Si un campo es 'no_especificado' o trae 'advertencia', "
            "decláralo y ofrece derivar a un ejecutivo; no lo inventes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"producto_id": {"type": "string", "description": "id del producto (p.ej. 'cerco-3d-180')."}},
            "required": ["producto_id"],
        },
    },
    {
        "name": "cotizar_cerco",
        "description": (
            "Cotiza un cerco por METROS LINEALES. Calcula paneles (2,5 m c/u) + postes "
            "(paneles + 1) y el total con IVA. Úsalo SIEMPRE que el cliente dé los metros; no "
            "calcules a mano. El total es del material; el despacho lo cotiza un ejecutivo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "producto_id": {"type": "string", "description": "id de un cerco (cerco-3d-180, cerco-3d-208, cerco-358-240)."},
                "metros_lineales": {"type": "number"},
            },
            "required": ["producto_id", "metros_lineales"],
        },
    },
    {
        "name": "cotizar_componente",
        "description": (
            "Cotiza un componente suelto (panel, poste o brazo anti-escalada) por cantidad de "
            "unidades, con IVA. Úsalo cuando el cliente pide repuestos o piezas sueltas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "producto_id": {"type": "string", "description": "id de un componente (comp-poste-30, comp-panel-358, etc.)."},
                "cantidad": {"type": "number"},
            },
            "required": ["producto_id", "cantidad"],
        },
    },
    # NOTA (fase de lanzamiento): la tool `generar_link_compra` está DESACTIVADA a propósito.
    # En esta fase el agente no deriva al checkout del sitio, sino que cotiza y deriva la
    # conversación a una persona vía Kommo (`registrar_lead_kommo`). El código del enlace Shopify
    # (`_t_link` / integraciones.tienda) queda listo para reactivarlo en la fase 2: basta volver a
    # agregar el esquema aquí y su entrada en `_DISPATCH`.
    {
        "name": "registrar_lead_kommo",
        "description": (
            "Registra un lead en Kommo y dispara el Round Robin para asignar un ejecutivo. Úsalo "
            "cuando el cliente quiere coordinar despacho, pide factura, es un proyecto grande o de "
            "licitación, o prefiere hablar con un ejecutivo. Completa todos los datos que tengas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string"},
                "empresa": {"type": "string"},
                "telefono": {"type": "string"},
                "correo": {"type": "string"},
                "ciudad": {"type": "string"},
                "tipo_proyecto": {
                    "type": "string",
                    "enum": ["cerco_3d", "cerco_358", "componentes", "licitacion", "otro"],
                },
                "producto_recomendado": {"type": "string"},
                "metros_lineales": {"type": "number"},
                "fecha_estimada": {"type": "string"},
                "nivel_intencion": {"type": "string", "enum": ["ALTA", "MEDIA", "BAJA"]},
                "observaciones": {"type": "string"},
            },
            "required": ["tipo_proyecto", "nivel_intencion"],
        },
    },
]


# --- Ejecución ---------------------------------------------------------------

def ejecutar(nombre: str, entrada: dict) -> str:
    """Despacha una llamada de herramienta y devuelve el resultado serializado."""
    try:
        resultado = _DISPATCH[nombre](entrada)
    except KeyError:
        return json.dumps({"ok": False, "error": f"Herramienta desconocida: {nombre}"}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 - devolver el error al modelo, no romper el loop
        resultado = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return json.dumps(resultado, ensure_ascii=False, default=str)


def _t_buscar(e: dict):
    return {"resultados": catalogo.buscar(e.get("categoria"), e.get("texto"))}


def _t_ficha(e: dict):
    info = catalogo.obtener_producto(e["producto_id"])
    if info is None:
        return {"ok": False, "error": f"No existe el producto '{e['producto_id']}'."}
    cat_nombre, cat, prod = info
    return {"categoria": cat_nombre, "uso": cat.get("uso"), "ficha": prod}


def _t_cotizar_cerco(e: dict):
    return catalogo.cotizar_cerco(e["producto_id"], float(e["metros_lineales"]))


def _t_cotizar_componente(e: dict):
    return catalogo.cotizar_componente(e["producto_id"], float(e["cantidad"]))


def _t_link(e: dict):
    pid = e["producto_id"]
    info = catalogo.obtener_producto(pid)
    if info is None:
        return {"ok": False, "motivo": f"No existe el producto '{pid}'."}
    cat_nombre, cat, prod = info

    if cat.get("venta_por_unidad"):
        cantidad = int(e.get("cantidad") or 0)
        if cantidad <= 0:
            return {"ok": False, "motivo": "Falta la cantidad de unidades para este componente."}
        url = tienda.enlace_componente(pid, cantidad)
        if not url:
            return {"ok": False, "motivo": "Este componente aún no está mapeado en la tienda; deriva a ejecutivo."}
        return {"ok": True, "producto": prod.get("nombre"), "cantidad": cantidad, "url_compra": url,
                "nota": "Enlace al carrito de cercosdeseguridad.cl; el cliente paga en el sitio."}

    # Cerco: se necesita metros lineales para armar paneles + postes.
    metros = e.get("metros_lineales")
    if metros is None:
        return {"ok": False, "motivo": "Falta metros_lineales para armar el carrito del cerco."}
    coti = catalogo.cotizar_cerco(pid, float(metros))
    if not coti.get("ok"):
        return coti
    n_paneles = coti["paneles"]["cantidad"]
    n_postes = coti["postes"]["cantidad"]
    url = tienda.enlace_cerco(pid, n_paneles, n_postes)
    if not url:
        return {"ok": False, "motivo": "Este cerco aún no está mapeado en la tienda; deriva a ejecutivo."}
    return {
        "ok": True,
        "producto": coti["producto"],
        "paneles": n_paneles,
        "postes": n_postes,
        "total_clp": coti["total_clp"],
        "url_compra": url,
        "nota": "Enlace al carrito de cercosdeseguridad.cl (paneles + postes); el cliente paga en el sitio.",
    }


def _t_lead(e: dict):
    return kommo.crear_lead(e)


_DISPATCH = {
    "buscar_productos": _t_buscar,
    "obtener_ficha": _t_ficha,
    "cotizar_cerco": _t_cotizar_cerco,
    "cotizar_componente": _t_cotizar_componente,
    # "generar_link_compra": _t_link,   # DESACTIVADA en fase de lanzamiento (ver nota arriba)
    "registrar_lead_kommo": _t_lead,
}
