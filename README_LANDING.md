# Landing page · Llama Borracha

Landing page responsiva para el e-commerce de **Llama la Juerga**, juego de cartas para tomar
(retos, preguntas, reglas y brindis). La estética es nocturna y fiestera, con efecto de cerveza
(degradado ámbar, burbujas que suben, borde de espuma) y motivos andinos/cusqueños: grecas
escalonadas, chakana, silueta de los Apus y cielo estrellado.

> Este trabajo está aislado en la rama `feature/landing-juego` y no toca el bot de Forex
> (`src/`, `config/`, `tests/`).

## Archivos

| Archivo | Contenido |
|---|---|
| `index.html` | Estructura y estilos (Tailwind CSS por CDN + CSS propio para los efectos). |
| `app.js` | Carrito dinámico, catálogo, cartas que se voltean, burbujas, menú móvil y toast. |
| `assets/landing/` | Logo, mascota, polo, llama juerguera y banners de categoría (recortados del banner original). |

## Secciones

1. **Header fijo**: logo, navegación y botón de carrito con contador.
2. **Hero**: título "Llama la Juerga", CTA **COMPRAR**, datos clave y la mascota dentro de un "vaso" de cerveza con burbujas.
3. **Beneficios**: cuatro tarjetas con iconos SVG en línea.
4. **Cómo se juega**: cuatro cartas interactivas (Reto, Pregunta, Regla, Brindis) que se voltean al tocarlas.
5. **Tienda**: producto destacado con selector de edición y cantidad, más una grilla (merch, pack y otros productos).
6. **Carrito**: panel lateral con cantidades, eliminación, barra de progreso para envío gratis, subtotal y total. Se cierra con Esc, con la X o tocando fuera.
7. **Testimonios**: tres reseñas de ejemplo.
8. **Footer**: enlaces, insignias de medios de pago (Visa, Mastercard, Yape, Plin, PagoEfectivo), sello de pago seguro y aviso +18.

## Cómo verla

No necesita build. Abre `index.html` en el navegador o sírvela localmente:

```bash
python3 -m http.server 8000
```

Luego entra a `http://localhost:8000/index.html`.

## Personalización

- **Precios y productos**: objeto `PRODUCTOS` y arreglo `GRID` al inicio de `app.js` (los precios en soles son de ejemplo).
- **Envío gratis**: constantes `ENVIO_GRATIS` (S/ 120) y `COSTO_ENVIO` (S/ 10) en `app.js`.
- **Textos de las cartas demo**: arreglo `CARTAS` en `app.js`.
- **Colores**: `tailwind.config` dentro de `index.html` (`noche`, `chela`, `espuma`, `inca`, `oro`, `andino`).

## Pendiente antes de publicar

- **Checkout**: el botón "Ir a pagar" es simulado. Hay que integrar la pasarela real (Culqi, Niubiz, Izipay, Mercado Pago, etc.) en un backend; nunca cobres desde el frontend.
- **Testimonios**: los actuales son de ejemplo y deben reemplazarse por reseñas reales.
- **Tailwind en producción**: el CDN (`cdn.tailwindcss.com`) está pensado para prototipos. Para producción conviene compilar el CSS con `tailwindcss` CLI y servir el archivo estático.
- **Insignias de pago**: son versiones simplificadas en texto. Si se usan los logos oficiales, hay que respetar el manual de marca de cada proveedor.
- **Legal (Perú)**: enlazar el Libro de Reclamaciones real, los términos, la política de privacidad y una verificación de edad +18.

## Verificación realizada

- Renderizada en Chromium (Playwright) a 1366 px y 390 px, sin errores de JavaScript y sin scroll horizontal.
- Flujo del carrito probado: agregar el destacado y un producto de la grilla, contador = 2, total S/ 119.80 (incluye S/ 10 de envío) y cierre con Esc.
- El entorno de prueba no tenía acceso al CDN de Tailwind, así que para la verificación se compiló el mismo Tailwind 3.4.16 localmente con la misma configuración.
