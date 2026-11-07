(() => {
  const workspace = document.querySelector('[data-org-workspace]');
  if (!workspace) return;
  const init = (previous = null) => {
    const controller = new AbortController();
    const on = (target, event, fn, options = {}) => target?.addEventListener(event, fn, { ...options, signal: controller.signal });
    const canvas = workspace.querySelector('[data-org-canvas]');
    const world = workspace.querySelector('[data-org-world]');
    const output = workspace.querySelector('[data-org-zoom]');
    const fullButton = workspace.querySelector('[data-org-fullscreen]');
    const zoomIn = workspace.querySelector('[data-org-zoom-in]');
    const zoomOut = workspace.querySelector('[data-org-zoom-out]');
    const fitButton = workspace.querySelector('[data-org-fit]');
    let scale = previous?.scale ?? 1, x = previous?.x ?? 0, y = previous?.y ?? 0, drag = null;
    const render = () => {
      if (!world) return;
      world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
      output.textContent = `${new Intl.NumberFormat('fa-IR').format(Math.round(scale * 100))}٪`;
    };
    const zoom = (factor, px, py) => {
      if (!canvas || !world) return;
      const next = Math.min(2.5, Math.max(.03, scale * factor));
      x = px - (px - x) * next / scale; y = py - (py - y) * next / scale; scale = next; render();
    };
    const fit = () => {
      if (!canvas || !world) return;
      const w = world.offsetWidth, h = world.offsetHeight;
      if (!w || !h) return;
      scale = Math.min(1, Math.max(.03, Math.min((canvas.clientWidth - 30) / w, (canvas.clientHeight - 30) / h)));
      x = (canvas.clientWidth - w * scale) / 2; y = (canvas.clientHeight - h * scale) / 2; render();
    };
    if (canvas && world) {
      on(zoomIn, 'click', () => zoom(1.2, canvas.clientWidth / 2, canvas.clientHeight / 2));
      on(zoomOut, 'click', () => zoom(1 / 1.2, canvas.clientWidth / 2, canvas.clientHeight / 2));
      on(fitButton, 'click', fit);
      on(canvas, 'wheel', (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); zoom(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX - rect.left, event.clientY - rect.top); }, { passive: false });
      on(canvas, 'pointerdown', (event) => {
        if (event.button !== 0 || event.target.closest('a, button, input, select, textarea, form, .organization-card')) return;
        drag = { id: event.pointerId, x: event.clientX, y: event.clientY, originX: x, originY: y };
        canvas.setPointerCapture(event.pointerId); canvas.classList.add('is-panning');
      });
      on(canvas, 'pointermove', (event) => { if (drag && drag.id === event.pointerId) { x = drag.originX + event.clientX - drag.x; y = drag.originY + event.clientY - drag.y; render(); } });
      const endDrag = (event) => { if (drag && drag.id === event.pointerId) { drag = null; canvas.classList.remove('is-panning'); } };
      ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((name) => on(canvas, name, endDrag));
      on(canvas, 'keydown', (event) => {
        if (event.target !== canvas) return;
        if (event.key === 'ArrowLeft') x += 40;
        else if (event.key === 'ArrowRight') x -= 40;
        else if (event.key === 'ArrowUp') y += 40;
        else if (event.key === 'ArrowDown') y -= 40;
        else if (event.key === '+' || event.key === '=') zoom(1.2, canvas.clientWidth / 2, canvas.clientHeight / 2);
        else if (event.key === '-') zoom(1 / 1.2, canvas.clientWidth / 2, canvas.clientHeight / 2);
        else return;
        event.preventDefault(); render();
      });
      on(window, 'resize', () => requestAnimationFrame(fit));
      if (previous) render(); else requestAnimationFrame(() => requestAnimationFrame(fit));
    } else [zoomIn, zoomOut, fitButton].forEach((button) => { if (button) button.disabled = true; });
    const updateFullscreen = (refit = true) => {
      const expanded = document.fullscreenElement === workspace || workspace.classList.contains('is-expanded');
      fullButton?.setAttribute('aria-pressed', String(expanded));
      if (fullButton) fullButton.textContent = expanded ? 'خروج از تمام‌صفحه' : 'تمام‌صفحه';
      if (refit) requestAnimationFrame(fit);
    };
    const fallbackFullscreen = () => { workspace.classList.toggle('is-expanded'); document.body.classList.toggle('organization-expanded', workspace.classList.contains('is-expanded')); updateFullscreen(); };
    on(fullButton, 'click', async () => {
      if (workspace.classList.contains('is-expanded')) { fallbackFullscreen(); return; }
      if (document.fullscreenElement === workspace) { await document.exitFullscreen(); return; }
      try { if (!workspace.requestFullscreen) throw new Error('unsupported'); await workspace.requestFullscreen(); } catch (_) { fallbackFullscreen(); }
    });
    on(document, 'fullscreenchange', () => updateFullscreen());
    on(document, 'keydown', (event) => { if (event.key === 'Escape' && workspace.classList.contains('is-expanded') && !workspace.querySelector('[data-org-dialog]')?.open) fallbackFullscreen(); });
    updateFullscreen(false);
    return { snapshot: () => canvas && world ? { scale, x, y } : null, destroy: () => controller.abort() };
  };
  workspace.organizationCanvas = init();
  window.initOrganizationCanvas = init;
})();
