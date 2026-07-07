"""Acceso al catálogo de productos (fuente de verdad: fichas-tecnicas/catalogo.json).

Toda la información técnica y de precios sale de aquí. El agente NUNCA debe inventar:
si un campo es 'no_especificado', se declara y se deriva a un ejecutivo.

A diferencia de un producto por m², un cerco se vende por COMPONENTES: paneles (de 2,5 m de
ancho) más postes. El cliente indica metros lineales; aquí se traduce a paneles y postes.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGO_PATH = os.path.join(BASE_DIR, "fichas-tecnicas", "catalogo.json")

IVA = 0.19
ANCHO_PANEL_M = 2.5  # cada panel cubre 2,5 m de ancho
FIJACION_ID = "comp-fijacion-doble"  # componente cuyo precio usa la cotización del cerco


def _precio_fijacion() -> int | float | None:
    """Precio neto de la fijación (desde el catálogo), o None si no está disponible."""
    info = obtener_producto(FIJACION_ID)
    if info and isinstance(info[2].get("precio_neto_clp"), (int, float)):
        return info[2]["precio_neto_clp"]
    return None


def paneles_para(metros_lineales: float) -> int:
    """Nº de paneles para cubrir un tramo (redondea hacia arriba; mínimo 1)."""
    return max(1, math.ceil(float(metros_lineales) / ANCHO_PANEL_M))


def postes_para(paneles: int) -> int:
    """Nº de postes para un tramo recto: uno por panel más uno de cierre."""
    return paneles + 1


@lru_cache(maxsize=1)
def _cargar() -> dict[str, Any]:
    with open(CATALOGO_PATH, encoding="utf-8") as f:
        return json.load(f)


def recargar() -> None:
    """Limpia la caché para releer el catálogo (tras actualizar precios/fichas)."""
    _cargar.cache_clear()


def meta() -> dict[str, Any]:
    return _cargar().get("_meta", {})


def categorias() -> list[str]:
    return list(_cargar()["categorias"].keys())


def _iter_productos():
    """Itera (categoria_nombre, categoria_dict, producto_dict)."""
    for cat_nombre, cat in _cargar()["categorias"].items():
        for prod in cat.get("productos", []):
            yield cat_nombre, cat, prod


def obtener_producto(producto_id: str) -> tuple[str, dict, dict] | None:
    for cat_nombre, cat, prod in _iter_productos():
        if prod.get("id") == producto_id:
            return cat_nombre, cat, prod
    return None


def buscar(categoria: str | None = None, texto: str | None = None) -> list[dict]:
    """Devuelve productos (resumen) filtrando por categoría y/o texto libre."""
    texto_l = (texto or "").lower().strip()
    resultados: list[dict] = []
    for cat_nombre, cat, prod in _iter_productos():
        if categoria and cat_nombre != categoria:
            continue
        if texto_l:
            blob = json.dumps(prod, ensure_ascii=False).lower()
            if texto_l not in blob:
                continue
        resultados.append(_resumen(cat_nombre, cat, prod))
    return resultados


def _clp(valor: float) -> str:
    return f"${valor:,.0f}".replace(",", ".")


def _resumen(cat_nombre: str, cat: dict, prod: dict) -> dict:
    out: dict[str, Any] = {
        "id": prod.get("id"),
        "nombre": prod.get("nombre"),
        "categoria": cat_nombre,
        "linea": prod.get("linea"),
    }
    if cat.get("venta_por_unidad"):
        out["tipo"] = "componente (venta por unidad)"
        if isinstance(prod.get("precio_neto_clp"), (int, float)):
            out["precio_unitario"] = f"{_clp(prod['precio_neto_clp'])}/{prod.get('unidad','u')} + IVA"
    else:
        out["tipo"] = "cerco (se cotiza por metro lineal)"
        panel = prod.get("panel", {})
        poste = prod.get("poste", {})
        if isinstance(panel.get("precio_neto_clp"), (int, float)):
            out["precio_panel"] = f"{_clp(panel['precio_neto_clp'])} + IVA (2,5 m de ancho)"
        if isinstance(poste.get("precio_neto_clp"), (int, float)):
            out["precio_poste"] = f"{_clp(poste['precio_neto_clp'])} + IVA"
        if panel.get("alto_m"):
            out["alto_m"] = panel["alto_m"]
        if panel.get("alambre_mm"):
            out["alambre_mm"] = panel["alambre_mm"]
    if prod.get("advertencia"):
        out["advertencia"] = prod["advertencia"]
    return out


def cotizar_cerco(producto_id: str, metros_lineales: float) -> dict:
    """Cotiza un cerco por metros lineales: paneles + postes + IVA.

    El total es del MATERIAL; el despacho lo coordina un ejecutivo aparte.
    """
    info = obtener_producto(producto_id)
    if info is None:
        return {"ok": False, "motivo": f"No existe el producto '{producto_id}'."}
    cat_nombre, cat, prod = info

    if cat.get("venta_por_unidad"):
        return {
            "ok": False,
            "motivo": f"'{producto_id}' es un componente suelto; usa cotizar_componente (por unidad).",
        }

    panel = prod.get("panel", {})
    poste = prod.get("poste", {})
    p_panel = panel.get("precio_neto_clp")
    p_poste = poste.get("precio_neto_clp")
    if not isinstance(p_panel, (int, float)) or not isinstance(p_poste, (int, float)):
        return {"ok": False, "motivo": "Precio no disponible en ficha. Derivar a ejecutivo."}

    metros = float(metros_lineales)
    if metros <= 0:
        return {"ok": False, "motivo": "Los metros lineales deben ser mayores que 0."}

    n_paneles = paneles_para(metros)
    n_postes = postes_para(n_paneles)
    cobertura = round(n_paneles * ANCHO_PANEL_M, 2)

    neto_paneles = p_panel * n_paneles
    neto_postes = p_poste * n_postes
    neto = neto_paneles + neto_postes

    # Fijaciones: van por poste según su altura (fijaciones_por_poste). Se incluyen en el total.
    fpp = poste.get("fijaciones_por_poste")
    p_fij = _precio_fijacion()
    fijaciones_out = None
    if fpp and p_fij:
        n_fij = n_postes * int(fpp)
        neto_fij = p_fij * n_fij
        neto += neto_fij
        fijaciones_out = {
            "cantidad": n_fij,
            "por_poste": int(fpp),
            "precio_neto_unit_clp": p_fij,
            "neto_clp": round(neto_fij),
        }

    iva = round(neto * IVA)
    total = round(neto + iva)

    resultado = {
        "ok": True,
        "producto": prod.get("nombre"),
        "producto_id": producto_id,
        "metros_solicitados": metros,
        "cobertura_m": cobertura,
        "paneles": {"cantidad": n_paneles, "precio_neto_unit_clp": p_panel, "neto_clp": round(neto_paneles)},
        "postes": {"cantidad": n_postes, "precio_neto_unit_clp": p_poste, "neto_clp": round(neto_postes)},
        "neto_clp": round(neto),
        "iva_clp": iva,
        "total_clp": total,
        "moneda": "CLP",
        "nota": ("Incluye paneles + postes + fijaciones (por poste). Postes calculados como "
                 "paneles + 1 (tramo recto). El total es del material; el despacho lo cotiza y "
                 "coordina un ejecutivo."),
    }
    if fijaciones_out:
        resultado["fijaciones"] = fijaciones_out
    return resultado


def cotizar_componente(producto_id: str, cantidad: float) -> dict:
    """Cotiza un componente suelto (panel, poste o accesorio) por cantidad de unidades."""
    info = obtener_producto(producto_id)
    if info is None:
        return {"ok": False, "motivo": f"No existe el producto '{producto_id}'."}
    cat_nombre, cat, prod = info

    precio = prod.get("precio_neto_clp")
    if not isinstance(precio, (int, float)):
        return {"ok": False, "motivo": "Precio no disponible en ficha. Derivar a ejecutivo."}

    n = max(1, int(cantidad))
    neto = precio * n
    iva = round(neto * IVA)
    total = round(neto + iva)
    return {
        "ok": True,
        "producto": prod.get("nombre"),
        "producto_id": producto_id,
        "unidad": prod.get("unidad", "unidad"),
        "cantidad": n,
        "precio_neto_unit_clp": precio,
        "neto_clp": round(neto),
        "iva_clp": iva,
        "total_clp": total,
        "moneda": "CLP",
    }


if __name__ == "__main__":  # smoke test
    print("Categorías:", categorias())
    print("Cercos 3D:", [p["nombre"] for p in buscar("cercos_3d")])
    print("Cotización 20 m del 3D 1,80:", cotizar_cerco("cerco-3d-180", 20))
    print("Cotización 5 postes 3,0 m:", cotizar_componente("comp-poste-30", 5))
