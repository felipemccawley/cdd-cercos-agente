# Casos y decisiones de entrenamiento — Agente CDS - Cercos de Seguridad

Registro de las decisiones de comportamiento del agente, con su porqué. Cada una está reflejada
en `agente/system_prompt.md`, `agente/empresa.md` o el catálogo. Sirve como libro de jugadas y
para no perder contexto entre sesiones. Este agente se construyó replicando la arquitectura de
ChilePastos (ver `PLAYBOOK-NUEVOS-AGENTES.md` en la carpeta padre `Claude/`).

Última actualización: 2026-07-06 (scaffolding inicial desde el cuestionario de descubrimiento).

## Reglas de comportamiento decididas (base)

| # | Regla | Por qué | Dónde |
|---|---|---|---|
| 1 | **Saludo dirigido**: pedir metros lineales, altura y línea (3D vs 358) desde el primer mensaje. | Cotizar dirigido convierte más que "¿en qué te ayudo?". | system_prompt → Apertura |
| 2 | **Sin emojis**; tono cercano-profesional, español de Chile. | Definición de marca en el cuestionario. | system_prompt → Estilo + servidor_whatsapp (_FORMATO_WA) |
| 3 | **Cotización por metro lineal**: paneles = techo(metros/2,5); postes = paneles + 1. El total es material; el despacho va aparte. | El cerco se vende por componentes, no por m². | catalogo.py + system_prompt → Cómo se cotiza |
| 4 | **Precios NETO + IVA 19%**; los calcula la tool, no el modelo. Precios son públicos. | Los precios del sitio son netos. | catalogo.py + system_prompt → Precios |
| 5 | **Todo se cierra en línea** (checkout Shopify); solo el despacho y la factura requieren ejecutivo. | Modelo de negocio del cuestionario. | system_prompt → Venta en línea vs. ejecutivo |
| 6 | **Enlace de compra = carrito Shopify** (/cart/<variant>:<qty>) con paneles + postes ya cargados. | El sitio ya cobra; cero infra nueva (patrón del playbook). | integraciones/tienda.py + catalogo.json (shopify_variant_id) |
| 7 | **Despacho no tarifado**: no inventar; lo cotiza un ejecutivo. No bloquea la venta del material. | El despacho se cotiza caso a caso. | system_prompt → Despacho |
| 8 | **No instalan**: se entrega contacto de instaladores recomendados vía ejecutivo. | Modelo de negocio. | system_prompt → Instalación + empresa.md |
| 9 | **No usar garantía como argumento** de venta. | Definición de marca. | system_prompt → Sobre CDS / empresa.md |
| 10 | **Lead mínimo: nombre + ciudad**. Por WhatsApp no pedir teléfono. | La ciudad es clave para el despacho. | system_prompt → Datos a recolectar |
| 11 | **Número central 100% bot**; los ejecutivos contactan desde sus números directos. Handoff de emergencia disponible. | Acuerdo aceptado en el cuestionario; evita respuestas dobles. | system_prompt → Cierre + servidor_whatsapp |
| 12 | **Kommo**: embudo "CDS Agente de IA", etapa "Lead entrante", 5 ejecutivos round robin. | CRM de la marca. | .env / render.yaml (IDs por confirmar) |
| 13 | **Diferenciador de cierre = stock en Chile** (sin esperas de importación) + 8 años + 20.000 ml instalados en el sur. | Gancho real de la marca. | system_prompt → Cierre / Sobre CDS |
| 14 | **Licitaciones**: pedir bases/especificaciones y adjuntarlas al lead (nivel ALTA). | El ejecutivo necesita las bases para cotizar. | system_prompt → Licitaciones |
| 15 | **Brazo anti-escalada** = accesorio opcional (1 por panel); se ofrece, no se fuerza ni se incluye por defecto. | Es complemento, no parte del cerco base. | catalogo.json + system_prompt |
| 16 | **No se cortan paneles**: se venden completos (2,5 m). Si el tramo no es múltiplo de 2,5, se redondea al panel superior y el cliente ajusta el sobrante en terreno. | Decisión del cliente (2026-07-06): CDS no corta a medida. | system_prompt → Cómo se cotiza |
| 17 | **Precio por metro = solo referencia**: se puede dar una cifra por metro lineal, pero NO se vende 1 metro suelto; la unidad mínima es un panel de 2,5 m. Reencauzar pidiendo los metros totales. | Decisión del cliente (2026-07-06). | system_prompt → Cómo se cotiza |
| 18 | **FASE DE LANZAMIENTO — sin checkout, derivar a humano**: el agente NO entrega enlace de compra ni deriva al sitio; cotiza/orienta y deriva la conversación a una persona vía Kommo (`registrar_lead_kommo`). Un humano monitorea Kommo para aprender qué piden los clientes. La tool `generar_link_compra` queda desactivada (código listo para fase 2). | Decisión del cliente (2026-07-06): aprender necesidades reales antes de automatizar el cierre. | system_prompt → Modelo de esta fase + Cierre; herramientas.py; servidor_whatsapp.py |
| 19 | **El contacto llega desde OTRO número**: al derivar, el agente avisa que una persona del equipo lo contactará desde su número directo (nunca "te escribo por aquí"). El número central es solo el canal inicial del bot. | Decisión del cliente (2026-07-06): mismo modelo de operación que ChilePastos. | system_prompt → Cierre |
| 20 | **Fijaciones incluidas automáticamente en la cotización del cerco**: van POR POSTE según altura — 4 por poste de 2,3 m, 5 por poste de 2,6 m o más. `cotizar_cerco` las suma al total (paneles + postes + fijaciones). Fijación doble + tornillo antirrobo = $500 neto c/u. | Decisión del cliente (2026-07-06): dato de fijaciones por poste confirmado. | catalogo.py + catalogo.json + system_prompt |
| 21 | **Cotización SIEMPRE desglosada por ítem**: mostrar valor unitario y total por línea de mallas (paneles), postes y fijaciones; el total de cada línea es neto y se escribe con "+ IVA". Luego neto total, IVA y total final con IVA. Tomar los números de la herramienta (no calcular a mano). | Decisión del cliente (2026-07-07): transparencia en la cotización. | system_prompt → Cómo se cotiza |

## Datos de empresa confirmados (cuestionario 2026-07-06)

- **Sucursal:** Ernesto Pinto Lagarrigue 580, San Pedro de la Paz, Concepción, Biobío. Presencial, retiro y despacho.
- **Cobertura:** todo Chile.
- **Horario:** Lun–Vie 9:00–18:30, Sáb 9:00–14:00.
- **Pagos:** checkout del sitio, Webpay, transferencia, tarjeta en sala de ventas. Factura vía ejecutivo.
- **Contacto/postventa:** Ventas@cercosdeseguridad.cl. Teléfono de llamadas: por confirmar.
- **Respaldo:** 8 años en el rubro, +20.000 metros lineales instalados en el sur de Chile.

## Catálogo (precios netos, extraídos del sitio Shopify 2026-07-06)

| Producto | Neto | Variant Shopify |
|---|---|---|
| Panel 3D 1,80 × 2,5 m (4,2 mm) | $21.420 | 48750433042675 |
| Panel 3D 2,08 × 2,5 m (4,2 mm) | $23.402 | 48750433075443 |
| Panel 358 2,40 × 2,5 m (4 mm) | $110.900 | 48750635155699 |
| Poste 2,3 m (60×60×1,5) | $14.698 | 48750600716531 |
| Poste 2,6 m (60×60×1,5) | $15.958 | 48750600749299 |
| Poste 3,0 m (60×60×2) | $18.490 | 48750600782067 |
| Brazo anti-escalada | $6.200 | 48750604517619 |
| Fijación doble + tornillo antirrobo | $500 | 49838994587891 |

## Pendientes por confirmar (críticos antes de lanzar)

1. **IVA en el checkout de Shopify**: ¿el sitio agrega el 19% automáticamente o el cliente paga el neto publicado? El total que dice el agente debe coincidir con lo cobrado.
2. **Postes por panel**: ¿la fórmula paneles + 1 es correcta para el negocio? ¿Y para esquinas/portones?
3. **Poste del 358**: confirmar sección y compatibilidad exacta con el panel de 2,40 m.
4. **Kommo**: subdominio, token, `KOMMO_PIPELINE_ID` y `KOMMO_STATUS_ID` reales del embudo "CDS Agente de IA".
5. **WhatsApp**: número, token permanente y verify token (Meta Cloud API).
6. **Teléfono de llamadas** y **redes sociales** (para empresa.md).
7. **¿Se venden mallas de cierre, portones, hormigón u otros accesorios?** El cuestionario no los menciona; hoy no están en el catálogo. (Surgió en prueba 2026-07-06: un cliente pidió un portón dentro del trazado.)
8. **¿Existe descuento por volumen?** ¿Hay una política que el agente deba conocer/aplicar, o siempre lo negocia un ejecutivo? Hoy el agente asume que lo ve un ejecutivo y no ofrece descuento. (Surgió en prueba 2026-07-06.)
9. ~~¿Cuántas fijaciones por panel?~~ **RESUELTO (2026-07-06):** van por poste — 4 (poste 2,3 m) / 5 (poste 2,6 m o más). Ya se incluyen automáticamente en `cotizar_cerco` (ver regla 20).

## Señales de mercado a observar en el lanzamiento (fase 1)

Cosas que pidieron clientes reales en las pruebas y que hoy NO ofrecemos; definir postura:
- **Polines/postes de madera** (prueba 2026-07-07): hoy solo poste de acero. ¿Se evalúa algún montaje sobre madera o siempre acero? El agente hoy responde honesto (solo acero) y ofrece derivar.
- **Curvas redondeadas (arcos):** el panel es rígido, no se curva; el agente lo deriva a una persona. Confirmar si hay solución para tramos curvos.
