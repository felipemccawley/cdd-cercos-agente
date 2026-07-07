"""Enlaces de compra hacia la tienda Shopify de cercosdeseguridad.cl.

En vez de cobrar con un servicio propio, el agente envía al cliente a un carrito ya armado
de la tienda (que cobra con los medios de pago del sitio). Shopify permite un "cart permalink":

    {SHOP_BASE_URL}/cart/{variant_id}:{cantidad}[,{variant_id}:{cantidad}...]

Para un cerco, el carrito lleva los paneles y los postes en una sola línea. Los IDs de variante
salen del catálogo (campo `shopify_variant_id` de cada panel/poste/componente).
"""
from __future__ import annotations

import os

from .. import catalogo

SHOP_BASE_URL = os.getenv("SHOP_BASE_URL", "https://www.cercosdeseguridad.cl").rstrip("/")


def _permalink(items: list[tuple[str, int]]) -> str | None:
    """Arma el cart permalink de Shopify a partir de (variant_id, cantidad)."""
    partes = [f"{vid}:{int(qty)}" for vid, qty in items if vid and int(qty) > 0]
    if not partes:
        return None
    return f"{SHOP_BASE_URL}/cart/{','.join(partes)}"


def enlace_cerco(producto_id: str, paneles: int, postes: int) -> str | None:
    """Carrito con los paneles y postes de un cerco. None si falta el mapeo de variantes."""
    info = catalogo.obtener_producto(producto_id)
    if not info:
        return None
    _, _, prod = info
    panel_vid = (prod.get("panel") or {}).get("shopify_variant_id")
    poste_vid = (prod.get("poste") or {}).get("shopify_variant_id")
    if not panel_vid or not poste_vid:
        return None
    return _permalink([(panel_vid, paneles), (poste_vid, postes)])


def enlace_componente(producto_id: str, cantidad: int) -> str | None:
    """Carrito con un componente suelto (panel, poste o accesorio)."""
    info = catalogo.obtener_producto(producto_id)
    if not info:
        return None
    _, _, prod = info
    vid = prod.get("shopify_variant_id")
    if not vid:
        return None
    return _permalink([(vid, cantidad)])
