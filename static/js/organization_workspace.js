(() => {
  const workspace = document.querySelector('[data-org-workspace]');
  if (!workspace) return;
  const chartPath = window.location.pathname;
  let refreshNumber = 0;
  const message = (text, error = false) => {
    const box = workspace.querySelector('[data-org-feedback]');
    if (!box) return;
    box.textContent = text; box.classList.toggle('is-error', error); box.hidden = false;
  };
  const refresh = async (url, { preserveView = true, push = false, showMessage = false } = {}) => {
    const sequence = ++refreshNumber;
    const response = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!response.ok || new URL(response.url).pathname !== chartPath) throw new Error('chart unavailable');
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    const replacement = page.querySelector('[data-org-workspace]');
    if (!replacement) throw new Error('chart unavailable');
    if (sequence !== refreshNumber) return;
    const previous = preserveView ? workspace.organizationCanvas?.snapshot() : null;
    const unplacedOpen = workspace.querySelector('.organization-unplaced')?.open;
    workspace.organizationCanvas?.destroy();
    workspace.innerHTML = replacement.innerHTML;
    workspace.organizationCanvas = window.initOrganizationCanvas(previous);
    if (unplacedOpen && workspace.querySelector('.organization-unplaced')) workspace.querySelector('.organization-unplaced').open = true;
    if (push) history.pushState({}, '', new URL(response.url).pathname + new URL(response.url).search);
    if (showMessage) message('تغییرات ذخیره شد.');
  };
  const modalError = (dialog, text) => {
    const box = dialog.querySelector('[data-org-dialog-message]');
    box.textContent = text; box.hidden = false;
  };
  const displayForm = (dialog, page, url, isGroup) => {
    const form = page.querySelector('.form-panel form');
    if (!form) throw new Error('form unavailable');
    form.dataset.orgModalForm = '';
    form.dataset.orgAction = url;
    form.dataset.orgGroupForm = isGroup ? '1' : '0';
    dialog.querySelector('[data-org-dialog-title]').textContent = page.querySelector('.form-heading h1')?.textContent || 'ویرایش';
    dialog.querySelector('[data-org-dialog-message]').hidden = true;
    dialog.querySelector('[data-org-dialog-content]').replaceChildren(form);
    if (isGroup) window.initOrganizationBuilder?.(form);
  };
  document.addEventListener('click', async (event) => {
    const close = event.target.closest('[data-org-dialog-close]');
    if (close) { close.closest('dialog')?.close(); return; }
    const cancel = event.target.closest('[data-org-dialog] .form-actions a');
    if (cancel) { event.preventDefault(); cancel.closest('dialog')?.close(); return; }
    const link = event.target.closest('[data-org-modal-link]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const dialog = workspace.querySelector('[data-org-dialog]');
    if (!dialog || typeof dialog.showModal !== 'function') return;
    event.preventDefault();
    dialog.querySelector('[data-org-dialog-title]').textContent = 'در حال دریافت…';
    dialog.querySelector('[data-org-dialog-content]').replaceChildren();
    dialog.querySelector('[data-org-dialog-message]').hidden = true;
    dialog.showModal();
    try {
      const response = await fetch(link.href, { credentials: 'same-origin' });
      if (!response.ok || new URL(response.url).pathname === '/login/') throw new Error('form unavailable');
      displayForm(dialog, new DOMParser().parseFromString(await response.text(), 'text/html'), link.href, link.hasAttribute('data-org-group-form'));
      dialog.querySelector('input:not([type=hidden]), select, textarea')?.focus();
    } catch (_) { modalError(dialog, 'دریافت فرم انجام نشد. اتصال یا دسترسی خود را بررسی کنید.'); }
  });
  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    if (form.matches('.organization-filter')) {
      event.preventDefault();
      const url = new URL(chartPath, window.location.href); url.search = new URLSearchParams(new FormData(form)).toString();
      try { await refresh(url, { preserveView: false, push: true }); } catch (_) { message('نمایش گروه انجام نشد.', true); }
      return;
    }
    const modalForm = form.hasAttribute('data-org-modal-form');
    if (!modalForm && !form.hasAttribute('data-org-async')) return;
    event.preventDefault();
    const dialog = modalForm ? form.closest('dialog') : null;
    const button = event.submitter || form.querySelector('button[type=submit]');
    const target = modalForm ? form.dataset.orgAction : form.getAttribute('action');
    const data = new FormData(form);
    if (button?.name) data.append(button.name, button.value);
    if (button) button.disabled = true;
    try {
      const response = await fetch(target, { method: 'POST', body: data, credentials: 'same-origin' });
      if (!response.ok) throw new Error(response.status >= 500 ? 'خطای سرور هنگام ذخیره چارت رخ داد.' : `ذخیره انجام نشد (کد ${response.status}).`);
      if (response.redirected && new URL(response.url).pathname === chartPath) {
        const groupChange = modalForm && form.dataset.orgGroupForm === '1';
        const deletedGroup = form.hasAttribute('data-org-delete-group');
        const next = groupChange || deletedGroup ? response.url : window.location.href;
        const nextUrl = new URL(next, window.location.href);
        const currentUrl = new URL(window.location.href);
        const sameGroup = nextUrl.searchParams.get('cluster') === currentUrl.searchParams.get('cluster');
        const locationChanged = nextUrl.pathname + nextUrl.search !== currentUrl.pathname + currentUrl.search;
        if (dialog?.open) dialog.close();
        await refresh(next, { preserveView: !deletedGroup && (!groupChange || sameGroup), push: locationChanged, showMessage: true });
      } else if (modalForm && !response.redirected) {
        displayForm(dialog, new DOMParser().parseFromString(await response.text(), 'text/html'), target, form.dataset.orgGroupForm === '1');
        dialog.querySelector('.field-error, .form-errors')?.scrollIntoView({ block: 'nearest' });
      } else throw new Error('save failed');
    } catch (error) {
      const details = error.message && error.message !== 'save failed' ? error.message : 'ذخیره انجام نشد. اتصال خود را بررسی کنید.';
      if (dialog) modalError(dialog, details);
      else message(details, true);
    } finally { if (button) button.disabled = false; }
  });
  window.addEventListener('popstate', () => { refresh(window.location.href, { preserveView: false }).catch(() => message('نمایش گروه انجام نشد.', true)); });
})();
