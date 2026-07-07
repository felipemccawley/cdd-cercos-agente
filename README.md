# Agente Comercial IA — CDS - Cercos de Seguridad

Vendedor consultivo de cercos perimetrales de alta seguridad, construido sobre la **API de
Claude**. Descubre el proyecto del cliente, recomienda la línea correcta (3D o 358) con **datos
reales del catálogo** (nunca inventa), cotiza por **metro lineal** (paneles + postes con IVA),
genera el enlace de compra al carrito de cercosdeseguridad.cl (Shopify) o deriva el lead al CRM
Kommo.

Réplica de la arquitectura del agente de ChilePastos (ver `PLAYBOOK-NUEVOS-AGENTES.md` en la
carpeta padre `Claude/`).

## Estructura

```
CDS-Cercos/
├── agente/
│   ├── agente.py               # Bucle conversacional (CLI) — punto de entrada
│   ├── catalogo.py             # Catálogo + cotización por metro lineal (paneles + postes)
│   ├── herramientas.py         # Tools (buscar/ficha/cotizar cerco/cotizar componente/link/lead)
│   ├── system_prompt.md        # Persona del vendedor + reglas
│   ├── empresa.md              # Datos duros de la empresa
│   └── integraciones/
│       ├── kommo.py            # CRM Kommo (real con credenciales; simulado sin ellas)
│       ├── tienda.py           # Enlaces de carrito Shopify (/cart/<variant>:<qty>)
│       ├── whatsapp.py         # WhatsApp Cloud API (enviar/descargar media)
│       └── documentos.py       # Lectura de PDF/Word que envía el cliente (licitaciones)
├── fichas-tecnicas/
│   └── catalogo.json           # FUENTE DE VERDAD de specs y precios
├── casos.md                    # Bitácora de decisiones de entrenamiento
├── servidor_whatsapp.py        # Webhook de WhatsApp + vigilante de seguimiento
├── requirements.txt
├── render.yaml                 # Blueprint de despliegue (Render)
└── .env.example
```

## Puesta en marcha

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env            # y completa ANTHROPIC_API_KEY
python3 -m agente.agente        # inicia el chat en la terminal
```

Sin credenciales de Kommo, los leads se registran en **modo SIMULADO** (`leads_simulados.jsonl`),
para probar el flujo completo de inmediato. El enlace de compra ya funciona: usa los IDs de
variante reales del sitio Shopify.

- **Modelo:** por defecto `claude-sonnet-4-6` (cámbialo con `AGENTE_MODELO` en `.env`).
- **Fotos (visión):** el agente acepta imágenes del cliente (terreno, cierre actual, portón). En la
  CLI envía una con `/foto <ruta-imagen> <mensaje>`.

## Cómo se cotiza

El cerco se vende por **componentes**, no por m²:

- El cliente da los **metros lineales**.
- `cotizar_cerco` calcula **paneles = techo(metros ÷ 2,5)** y **postes = paneles + 1** (tramo
  recto), y el total con **IVA (19%)** sobre los precios netos del catálogo.
- `generar_link_compra` arma el carrito de Shopify con esos paneles y postes.
- Piezas sueltas (repuestos, brazos anti-escalada): `cotizar_componente`.

## Cómo se mantiene actualizado

El agente lee **siempre** de `fichas-tecnicas/catalogo.json`. Para actualizar un precio o agregar
un producto, edita ese JSON (los precios van en **neto**; el `shopify_variant_id` se obtiene del
endpoint `/products/<handle>.js` del sitio). El agente toma el cambio en la siguiente conversación.

## Pendientes antes de lanzar

Ver `casos.md` → sección "Pendientes por confirmar" (IVA del checkout, postes por panel, credenciales
de Kommo y WhatsApp, etc.).
