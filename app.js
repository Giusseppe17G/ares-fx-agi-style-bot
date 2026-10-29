/* Llama Borracha · landing page
 * Carrito dinámico (panel lateral), catálogo, cartas de demo y efectos de cerveza.
 * Sin dependencias: solo JavaScript del navegador.
 */
(() => {
  'use strict';

  // ---------- Catálogo ----------
  // Precios de ejemplo en soles (PEN). Ajustar antes de publicar.
  const PRODUCTOS = {
    'juego-clasico': { nombre: 'Llama la Juerga · Clásica', precio: 59.9, img: 'assets/landing/cat-juerga.jpg' },
    'juego-picante': { nombre: 'Llama la Juerga · Picante +18', precio: 74.9, img: 'assets/landing/cat-juerga.jpg' },
    'polo-llama': { nombre: 'Polo oficial Llama Borracha', precio: 49.9, img: 'assets/landing/polo.png' },
    'pack-juerga': { nombre: 'Pack Juerga (juego + polo)', precio: 99.9, img: 'assets/landing/cat-merch.jpg' },
    'kit-chupitos': { nombre: 'Kit taza + baraja de bolsillo', precio: 39.9, img: 'assets/landing/cat-otros.jpg' },
  };

  const GRID = [
    { id: 'polo-llama', titulo: 'Merch oficial', desc: 'Polo negro 100% algodón con la llama más famosa del Cusco.', img: 'assets/landing/cat-merch.jpg' },
    { id: 'pack-juerga', titulo: 'Pack Juerga', desc: 'El juego clásico + polo oficial. Ahorra S/ 9.90.', img: 'assets/landing/polo.png', etiqueta: 'Ahorra' },
    { id: 'kit-chupitos', titulo: 'Otros productos', desc: 'Taza cervecera y baraja de bolsillo para la previa.', img: 'assets/landing/cat-otros.jpg' },
  ];

  const CARTAS = [
    { tipo: 'Reto', color: 'from-inca-500 to-inca-600', icono: '🔥', texto: 'Baila un huayno de 10 segundos o toma dos sorbos.' },
    { tipo: 'Pregunta', color: 'from-andino to-teal-800', icono: '❓', texto: '¿Cuál fue tu peor resaca? Si no respondes, al seco.' },
    { tipo: 'Regla', color: 'from-noche-600 to-noche-800', icono: '📜', texto: 'Hasta nuevo aviso, quien diga "causa" toma.' },
    { tipo: 'Brindis', color: 'from-chela-500 to-chela-700', icono: '🍺', texto: '¡Por la Pachamama! Todos derraman un poquito y toman.' },
  ];

  const ENVIO_GRATIS = 120;
  const COSTO_ENVIO = 10;
  const CLAVE = 'llama-borracha-carrito';

  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const soles = (n) => 'S/ ' + n.toFixed(2);
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- Estado del carrito ----------
  // { [id]: cantidad }. Se guarda en localStorage solo como comodidad del visitante.
  let carrito = {};
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE) || '{}');
    for (const [id, cant] of Object.entries(guardado)) {
      if (PRODUCTOS[id] && Number.isInteger(cant) && cant > 0) carrito[id] = Math.min(cant, 99);
    }
  } catch { carrito = {}; }

  const guardar = () => {
    try { localStorage.setItem(CLAVE, JSON.stringify(carrito)); } catch { /* sin almacenamiento */ }
  };

  const agregar = (id, cant = 1) => {
    if (!PRODUCTOS[id]) return;
    carrito[id] = Math.min((carrito[id] || 0) + cant, 99);
    guardar();
    render();
    toast(`🍺 ${PRODUCTOS[id].nombre} agregado`);
    pulsoContador();
  };

  const cambiar = (id, delta) => {
    if (!carrito[id]) return;
    carrito[id] += delta;
    if (carrito[id] <= 0) delete carrito[id];
    guardar();
    render();
  };

  const quitar = (id) => { delete carrito[id]; guardar(); render(); };

  // ---------- Render del carrito ----------
  const lista = $('#carrito-items');
  const vacio = $('#carrito-vacio');

  function render() {
    const ids = Object.keys(carrito);
    const unidades = ids.reduce((s, id) => s + carrito[id], 0);
    const subtotal = ids.reduce((s, id) => s + PRODUCTOS[id].precio * carrito[id], 0);
    const envio = subtotal === 0 || subtotal >= ENVIO_GRATIS ? 0 : COSTO_ENVIO;

    const contador = $('#carrito-count');
    contador.textContent = unidades;
    contador.classList.toggle('scale-0', unidades === 0);
    contador.classList.toggle('scale-100', unidades > 0);

    lista.innerHTML = '';
    for (const id of ids) {
      const p = PRODUCTOS[id];
      const li = document.createElement('li');
      li.className = 'flex gap-4 rounded-2xl bg-noche-700/70 p-3 ring-1 ring-white/5';
      li.innerHTML = `
        <img src="${p.img}" alt="" class="h-20 w-20 shrink-0 rounded-xl object-cover bg-noche-900">
        <div class="flex-1 min-w-0">
          <div class="flex justify-between gap-2">
            <p class="font-semibold leading-tight"></p>
            <button type="button" data-accion="quitar" data-id="${id}" class="text-espuma/40 hover:text-inca-500" aria-label="Quitar ${p.nombre}">
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>
            </button>
          </div>
          <p class="text-sm text-espuma/60">${soles(p.precio)} c/u</p>
          <div class="mt-2 flex items-center justify-between">
            <div class="inline-flex items-center rounded-full border border-white/15">
              <button type="button" data-accion="menos" data-id="${id}" class="h-8 w-8 font-bold hover:text-chela-400" aria-label="Quitar uno">−</button>
              <span class="w-7 text-center text-sm font-bold">${carrito[id]}</span>
              <button type="button" data-accion="mas" data-id="${id}" class="h-8 w-8 font-bold hover:text-chela-400" aria-label="Agregar uno">+</button>
            </div>
            <span class="font-bold text-chela-400">${soles(p.precio * carrito[id])}</span>
          </div>
        </div>`;
      li.querySelector('p').textContent = p.nombre;
      lista.appendChild(li);
    }

    lista.classList.toggle('hidden', ids.length === 0);
    vacio.classList.toggle('hidden', ids.length > 0);
    vacio.classList.toggle('flex', ids.length === 0);

    $('#carrito-subtotal').textContent = soles(subtotal);
    $('#carrito-envio').textContent = subtotal === 0 ? '—' : envio === 0 ? '¡Gratis!' : soles(envio);
    $('#carrito-total').textContent = soles(subtotal + envio);
    $('#btn-pagar').disabled = ids.length === 0;

    const falta = ENVIO_GRATIS - subtotal;
    $('#envio-barra').style.width = Math.min(100, (subtotal / ENVIO_GRATIS) * 100) + '%';
    $('#envio-msg').innerHTML = falta > 0
      ? `Te faltan <strong class="text-chela-400">${soles(falta)}</strong> para el envío gratis 🚚`
      : '🎉 ¡Tienes <strong class="text-chela-400">envío gratis</strong>!';
  }

  lista.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-accion]');
    if (!btn) return;
    const { accion, id } = btn.dataset;
    if (accion === 'mas') cambiar(id, 1);
    if (accion === 'menos') cambiar(id, -1);
    if (accion === 'quitar') quitar(id);
  });

  // ---------- Panel lateral ----------
  const panel = $('#carrito');
  const overlay = $('#overlay');
  const btnCarrito = $('#btn-carrito');
  let ultimoFoco = null;

  function abrir() {
    ultimoFoco = document.activeElement;
    panel.removeAttribute('inert');
    panel.setAttribute('aria-hidden', 'false');
    panel.classList.remove('translate-x-full');
    overlay.classList.remove('opacity-0', 'pointer-events-none');
    btnCarrito.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
    $('#cerrar-carrito').focus();
  }

  function cerrar() {
    panel.setAttribute('inert', '');
    panel.setAttribute('aria-hidden', 'true');
    panel.classList.add('translate-x-full');
    overlay.classList.add('opacity-0', 'pointer-events-none');
    btnCarrito.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    if (ultimoFoco) ultimoFoco.focus();
  }

  btnCarrito.addEventListener('click', abrir);
  $('#cerrar-carrito').addEventListener('click', cerrar);
  overlay.addEventListener('click', cerrar);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.getAttribute('aria-hidden') === 'false') cerrar();
  });

  $('#btn-pagar').addEventListener('click', () => {
    // Checkout simulado: aquí se integraría la pasarela de pago real.
    toast('✅ ¡Pedido simulado! Integra tu pasarela de pago aquí.');
    carrito = {};
    guardar();
    render();
    setTimeout(cerrar, 900);
  });

  // ---------- Producto destacado ----------
  let cantidad = 1;
  const salidaCant = $('#cant-valor');
  $('#cant-menos').addEventListener('click', () => { cantidad = Math.max(1, cantidad - 1); salidaCant.textContent = cantidad; });
  $('#cant-mas').addEventListener('click', () => { cantidad = Math.min(20, cantidad + 1); salidaCant.textContent = cantidad; });
  $('#agregar-destacado').addEventListener('click', () => {
    const edicion = document.querySelector('input[name="edicion"]:checked').value;
    agregar(edicion, cantidad);
    cantidad = 1;
    salidaCant.textContent = cantidad;
  });

  // ---------- Grid de productos ----------
  const grid = $('#grid-productos');
  for (const item of GRID) {
    const p = PRODUCTOS[item.id];
    const card = document.createElement('article');
    card.className = 'group flex flex-col overflow-hidden rounded-3xl border border-oro/15 bg-noche-700/60 hover:border-chela-500/60 hover:-translate-y-1 transition';
    card.innerHTML = `
      <div class="relative aspect-[495/277] overflow-hidden ${item.img.endsWith('.png') ? 'cerveza' : 'bg-noche-900'}">
        <img src="${item.img}" alt="" class="h-full w-full ${item.img.endsWith('.png') ? 'object-contain p-3' : 'object-cover'} group-hover:scale-105 transition duration-500">
        ${item.etiqueta ? `<span class="absolute top-3 left-3 rounded-full bg-inca-500 px-3 py-1 text-xs font-bold uppercase ring-2 ring-oro">${item.etiqueta}</span>` : ''}
      </div>
      <div class="flex flex-1 flex-col p-6">
        <h3 class="font-display text-2xl tracking-wide">${item.titulo}</h3>
        <p class="mt-2 flex-1 text-espuma/70">${item.desc}</p>
        <div class="mt-5 flex items-center justify-between">
          <span class="font-display text-2xl text-chela-400">${soles(p.precio)}</span>
          <button type="button" data-agregar="${item.id}" class="rounded-full bg-chela-500 px-5 py-2.5 font-bold text-noche-900 hover:bg-chela-400 active:scale-95 transition">
            Agregar
          </button>
        </div>
      </div>`;
    grid.appendChild(card);
  }
  grid.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-agregar]');
    if (btn) agregar(btn.dataset.agregar);
  });

  // ---------- Cartas de demo (se voltean) ----------
  const contCartas = $('#cartas-demo');
  for (const c of CARTAS) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'carta block aspect-[5/7] w-full text-left focus:outline-none focus-visible:ring-4 focus-visible:ring-espuma rounded-3xl';
    el.setAttribute('aria-label', `Carta de ${c.tipo}: toca para voltear`);
    el.innerHTML = `
      <div class="carta-inner relative h-full w-full">
        <div class="carta-cara absolute inset-0 rounded-3xl bg-noche-800 ring-4 ring-oro shadow-2xl overflow-hidden grid place-items-center">
          <img src="assets/landing/mascota.jpg" alt="" class="absolute inset-0 h-full w-full object-cover opacity-90">
          <div class="absolute inset-x-0 bottom-0 greca"></div>
          <span class="relative mt-auto mb-8 rounded-full bg-noche-900/80 px-4 py-1 font-display tracking-wider text-chela-300">${c.tipo.toUpperCase()}</span>
        </div>
        <div class="carta-cara carta-dorso absolute inset-0 rounded-3xl bg-gradient-to-br ${c.color} ring-4 ring-oro shadow-2xl p-4 sm:p-6 flex flex-col text-espuma">
          <span class="text-3xl sm:text-4xl">${c.icono}</span>
          <span class="mt-2 font-display text-xl sm:text-2xl tracking-wider">${c.tipo}</span>
          <p class="mt-3 text-sm sm:text-base font-medium leading-snug">${c.texto}</p>
          <span class="mt-auto self-end font-display text-oro">✦ LB ✦</span>
        </div>
      </div>`;
    el.addEventListener('click', () => el.classList.toggle('volteada'));
    contCartas.appendChild(el);
  }

  // ---------- Efecto burbujas de cerveza ----------
  function burbujas(contenedor, cantidad, tamMax) {
    if (!contenedor || reduceMotion) return;
    for (let i = 0; i < cantidad; i++) {
      const b = document.createElement('span');
      const t = 4 + Math.random() * tamMax;
      b.className = 'burbuja';
      b.style.width = b.style.height = t + 'px';
      b.style.left = Math.random() * 100 + '%';
      b.style.animationDuration = 5 + Math.random() * 7 + 's';
      b.style.animationDelay = -Math.random() * 12 + 's';
      contenedor.appendChild(b);
    }
  }
  burbujas($('#burbujas-hero'), 26, 14);
  burbujas($('#burbujas-vaso'), 18, 10);
  burbujas($('#burbujas-juego'), 30, 16);

  // ---------- Utilidades ----------
  let toastTimer;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.remove('translate-y-24', 'opacity-0');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('translate-y-24', 'opacity-0'), 2400);
  }

  function pulsoContador() {
    const c = $('#carrito-count');
    if (reduceMotion || !c.animate) return;
    c.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.5)' }, { transform: 'scale(1)' }], { duration: 400 });
  }

  // Menú móvil
  const btnMenu = $('#btn-menu');
  const menu = $('#menu-movil');
  btnMenu.addEventListener('click', () => {
    const abierto = menu.classList.toggle('hidden') === false;
    btnMenu.setAttribute('aria-expanded', String(abierto));
  });
  menu.addEventListener('click', (e) => {
    if (e.target.closest('a')) { menu.classList.add('hidden'); btnMenu.setAttribute('aria-expanded', 'false'); }
  });

  $('#anio').textContent = new Date().getFullYear();
  render();
})();
