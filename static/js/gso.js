/* GSO — utilidades de interfaz */
window.GSO = (() => {
  // Colores categóricos tomados de la paleta del documento (orden fijo)
  const c = ['#0064AA', '#F08C41', '#0AA5BE', '#EB5F28', '#14324B', '#1991B4'];
  const fmt = new Intl.NumberFormat('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const fmtN = new Intl.NumberFormat('es-AR');
  const pesos = v => '$ ' + fmt.format(+v || 0);
  const n = v => fmtN.format(+v || 0);
  const corto = v => { v = +v || 0; const a = Math.abs(v);
    return a >= 1e9 ? '$ ' + (v/1e9).toFixed(1).replace('.', ',') + ' mil M' : a >= 1e6 ? '$ ' + (v/1e6).toFixed(1).replace('.', ',') + ' M'
         : a >= 1e3 ? '$ ' + Math.round(v/1e3) + ' mil' : '$ ' + Math.round(v); };
  const charts = {};

  function chart(id, cfg){
    if (!window.Chart) return;
    Chart.defaults.font.family = 'Poppins, "Segoe UI", sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = 'rgb(85,98,112)';
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.labels.boxHeight = 12;
    Chart.defaults.plugins.legend.labels.useBorderRadius = true;
    Chart.defaults.plugins.legend.labels.borderRadius = 3;
    Chart.defaults.plugins.tooltip.backgroundColor = 'rgb(20,50,75)';
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 6;
    Chart.defaults.maintainAspectRatio = false;
    if (charts[id]) charts[id].destroy();
    const el = document.getElementById(id);
    if (!el) return;
    charts[id] = new Chart(el, cfg);
    return charts[id];
  }

  function contadores(){
    document.querySelectorAll('[data-contar]').forEach(el => {
      const fin = +el.dataset.contar, moneda = el.hasAttribute('data-moneda'), t0 = performance.now(), dur = 700;
      const paso = t => { const p = Math.min(1, (t - t0) / dur), v = fin * (1 - Math.pow(1 - p, 3));
        el.textContent = moneda ? pesos(v) : n(Math.round(v)); if (p < 1) requestAnimationFrame(paso); };
      requestAnimationFrame(paso);
    });
  }

  // Filtro instantáneo de tablas: <input data-filtrar="#contenedor">
  document.addEventListener('input', e => {
    const sel = e.target.dataset && e.target.dataset.filtrar; if (!sel) return;
    const q = e.target.value.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    document.querySelectorAll(sel + ' tbody tr').forEach(tr => {
      const t = tr.textContent.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
      tr.style.display = t.includes(q) ? '' : 'none';
    });
  });
  // Evitar que el filtro instantáneo envíe el formulario con Enter vacío
  // Orden de tablas: <table data-ordenable> + <th class="ord">
  document.addEventListener('click', e => {
    const th = e.target.closest('table[data-ordenable] th.ord'); if (!th) return;
    const tabla = th.closest('table'), idx = [...th.parentNode.children].indexOf(th), tb = tabla.tBodies[0];
    const asc = th.dataset.dir !== 'asc'; tabla.querySelectorAll('th').forEach(x => delete x.dataset.dir); th.dataset.dir = asc ? 'asc' : 'desc';
    const val = tr => { const td = tr.children[idx]; if (!td) return ''; const v = td.dataset.v ?? td.textContent.trim();
      const num = parseFloat(String(v).replace(/[$\s.]/g, '').replace(',', '.')); return td.dataset.v && !isNaN(+td.dataset.v) ? +td.dataset.v : (/^[\d$\s.,-]+$/.test(v) && !isNaN(num) ? num : v.toLowerCase()); };
    [...tb.rows].filter(r => !r.querySelector('.vacio')).sort((a, b) => { const x = val(a), y = val(b); return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1); })
      .forEach(r => tb.appendChild(r));
  });

  // Evitar el doble envío: al enviar un formulario, sus botones se desactivan.
  // (El servidor además ignora un formulario que llegue dos veces.)
  document.addEventListener('submit', e => {
    const f = e.target;
    if (e.defaultPrevented || (f.method || '').toLowerCase() !== 'post') return;
    setTimeout(() => f.querySelectorAll('button:not([type=button])').forEach(b => { b.disabled = true; b.dataset.enviando = '1'; }), 0);
  });
  // Al volver con «Atrás», reactivar los botones.
  window.addEventListener('pageshow', () => document.querySelectorAll('button[data-enviando]').forEach(b => { b.disabled = false; delete b.dataset.enviando; }));

  // Buscador con autocompletado: muestra todos los elementos al hacer clic y filtra al escribir.
  // items: [{id, descripcion, grupo, especialidad, stock_actual}], alElegir(item), actual: id marcado.
  function buscador(caja, items, alElegir, actual){
    if (!caja) return;
    const inp = caja.querySelector('input'), lista = document.createElement('ul');
    lista.className = 'buscador-lista'; lista.setAttribute('role', 'listbox'); lista.hidden = true; caja.appendChild(lista);
    const norm = t => String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const resaltar = (txt, q) => { if (!q) return esc(txt); const i = norm(txt).indexOf(q);
      return i < 0 ? esc(txt) : esc(txt.slice(0, i)) + '<mark>' + esc(txt.slice(i, i + q.length)) + '</mark>' + esc(txt.slice(i + q.length)); };
    let vis = [], pos = -1;
    const pintar = () => {
      const q = norm(inp.value.trim()), palabras = q.split(/\s+/).filter(Boolean);
      vis = items.filter(e => { const t = norm(e.descripcion + ' ' + e.especialidad + ' ' + e.grupo); return palabras.every(p => t.includes(p)); });
      vis.sort((a, b) => (a.grupo === 'Insumo' ? 0 : 1) - (b.grupo === 'Insumo' ? 0 : 1) || (norm(a.descripcion).startsWith(q) ? 0 : 1) - (norm(b.descripcion).startsWith(q) ? 0 : 1) || a.descripcion.localeCompare(b.descripcion));
      let html = '', grupo = null;
      vis.forEach((e, i) => {
        if (e.grupo !== grupo) { grupo = e.grupo; html += `<li class="bl-grupo" role="presentation">${grupo === 'Insumo' ? 'Insumos' : 'Instrumental'} · ${vis.filter(x => x.grupo === grupo).length}</li>`; }
        html += `<li class="bl-item ${i === pos ? 'on' : ''} ${e.id == actual ? 'actual' : ''}" role="option" data-i="${i}">
          <span class="bl-nom">${resaltar(e.descripcion, palabras[0] || '')}</span>
          <span class="bl-meta">${esc(e.especialidad)} · stock ${n(e.stock_actual)}${e.id == actual ? ' · actual' : ''}</span></li>`;
      });
      lista.innerHTML = html || '<li class="bl-vacio">No hay elementos que coincidan.</li>';
      lista.hidden = false;
      const on = lista.querySelector('.on'); if (on) on.scrollIntoView({block: 'nearest'});
    };
    inp.addEventListener('focus', () => { pos = -1; pintar(); });
    inp.addEventListener('click', () => { if (lista.hidden) pintar(); });
    inp.addEventListener('input', () => { pos = 0; pintar(); });
    inp.addEventListener('keydown', ev => {
      if (ev.key === 'ArrowDown') { ev.preventDefault(); pos = Math.min(vis.length - 1, pos + 1); pintar(); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); pos = Math.max(0, pos - 1); pintar(); }
      else if (ev.key === 'Enter') { ev.preventDefault(); if (vis[pos]) alElegir(vis[pos]); else if (vis.length === 1) alElegir(vis[0]); }
      else if (ev.key === 'Escape') { lista.hidden = true; }
    });
    lista.addEventListener('mousedown', ev => { const li = ev.target.closest('.bl-item'); if (li) { ev.preventDefault(); alElegir(vis[+li.dataset.i]); } });
    document.addEventListener('click', ev => { if (!caja.contains(ev.target)) lista.hidden = true; });
  }

  return {c, pesos, n, corto, chart, charts, contadores, buscador};
})();
