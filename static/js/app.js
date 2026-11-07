(() => {
  const body = document.body;
  const toggle = document.querySelector("[data-menu-toggle]");
  const overlay = document.querySelector("[data-menu-close]");
  const themeToggle = document.querySelector("[data-theme-toggle]");
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
    themeMeta?.setAttribute("content", theme === "dark" ? "#090c12" : "#f5f7f5");
    if (themeToggle) {
      const dark = theme === "dark";
      themeToggle.setAttribute("aria-label", dark ? "تغییر به پوسته روشن" : "تغییر به پوسته تاریک");
      themeToggle.querySelector(".theme-icon").textContent = dark ? "☀" : "☾";
    }
  };
  applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  themeToggle?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("safetyinspection-theme", next); } catch (_) { /* Theme still applies for this page. */ }
    applyTheme(next);
  });

  // Stagger the first entrance of key dashboard cards and keep the rest of the UI snappy.
  document.querySelectorAll(".metric-card, .visual-chart, .dashboard-content > .panel").forEach((item, index) => {
    item.style.setProperty("--reveal-order", index);
    item.classList.add("motion-in");
  });
  const sheetProfilesNode = document.getElementById("equipment-field-profiles");
  const equipmentTypeSelect = document.getElementById("id_equipment_type");
  if (sheetProfilesNode && equipmentTypeSelect) {
    const profiles = JSON.parse(sheetProfilesNode.textContent);
    const workbookFields = new Set(Object.values(profiles).flat());
    const updateEquipmentFields = () => {
      const visibleFields = new Set(profiles[equipmentTypeSelect.value] || []);
      document.querySelectorAll("[data-field-name]").forEach((field) => {
        if (workbookFields.has(field.dataset.fieldName)) {
          field.hidden = !visibleFields.has(field.dataset.fieldName);
        }
      });
    };
    equipmentTypeSelect.addEventListener("change", updateEquipmentFields);
    updateEquipmentFields();
  }
  document.querySelectorAll('.check-item').forEach((item) => {
    const assignment = item.querySelector('[data-finding-assignment]');
    if (!assignment) return;
    const update = () => {
      const failed = item.querySelector('input[type="radio"]:checked')?.value === 'fail';
      assignment.hidden = !failed;
      assignment.querySelectorAll('input, select').forEach((input) => { input.required = failed; });
    };
    item.querySelectorAll('input[type="radio"]').forEach((radio) => radio.addEventListener('change', update));
    update();
  });
  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('.finding-action-form, .finding-assignment-edit')) return;
    const card = form.closest('[data-finding-id]');
    const submitter = event.submitter;
    if (!card || !submitter) return;
    event.preventDefault();
    const feedback = card.querySelector('.finding-feedback');
    const buttons = card.querySelectorAll('button[type="submit"], button:not([type])');
    const data = new FormData(form);
    if (submitter.name) data.append(submitter.name, submitter.value);
    buttons.forEach((button) => { button.disabled = true; });
    feedback.hidden = true;
    try {
      const actionUrl = form.getAttribute('action');
      if (!actionUrl) throw new Error('missing action');
      const targetUrl = new URL(actionUrl, window.location.href);
      targetUrl.search = window.location.search;
      const response = await fetch(targetUrl.toString(), { method: 'POST', body: data, headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
      if (response.status === 403) throw new Error('forbidden');
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('unexpected response');
      const result = await response.json();
      if (!response.ok || !result.ok) {
        feedback.textContent = result.message || 'ثبت تغییرات انجام نشد.';
        feedback.classList.add('is-error');
        feedback.hidden = false;
      } else if (result.remove) {
        const list = card.parentElement;
        const notice = document.createElement('div');
        notice.className = 'panel finding-feedback';
        notice.setAttribute('role', 'status');
        notice.textContent = result.message;
        card.replaceWith(notice);
        const counter = document.querySelector('[data-finding-count]');
        if (counter && list) counter.textContent = new Intl.NumberFormat('fa-IR').format(list.querySelectorAll('[data-finding-id]').length);
        if (list && !list.querySelector('[data-finding-id]')) {
          const empty = document.createElement('section');
          empty.className = 'panel empty-state';
          const title = document.createElement('strong');
          title.textContent = 'نقصی با این فیلترها پیدا نشد';
          empty.append(title);
          list.append(empty);
        }
      } else {
        const template = document.createElement('template');
        template.innerHTML = result.html.trim();
        const updated = template.content.firstElementChild;
        if (!updated || !updated.matches('[data-finding-id]')) throw new Error('invalid card');
        const updatedFeedback = updated.querySelector('.finding-feedback');
        updatedFeedback.textContent = result.message;
        updatedFeedback.hidden = false;
        card.replaceWith(updated);
      }
    } catch (error) {
      feedback.textContent = error.message === 'forbidden'
        ? 'دسترسی یا نشست شما معتبر نیست؛ صفحه را تازه کنید و دوباره وارد شوید.'
        : 'ارتباط با سرور برقرار نشد یا پاسخ نامعتبر بود؛ دوباره تلاش کنید.';
      feedback.classList.add('is-error');
      feedback.hidden = false;
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  });
  const closeMenu = () => {
    body.classList.remove("menu-open");
    toggle?.setAttribute("aria-expanded", "false");
    if (toggle && body.dataset.menuHadFocus === "true") toggle.focus();
    delete body.dataset.menuHadFocus;
  };
  toggle?.addEventListener("click", () => {
    const open = body.classList.toggle("menu-open");
    toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      body.dataset.menuHadFocus = "true";
      document.querySelector(".main-nav .nav-link")?.focus({ preventScroll: true });
    }
  });
  overlay?.addEventListener("click", closeMenu);
  document.querySelectorAll("[data-dismiss]").forEach((button) =>
    button.addEventListener("click", () => {
      const flash = button.closest(".flash");
      if (!flash) return;
      flash.classList.add("is-dismissing");
      window.setTimeout(() => flash.remove(), 180);
    }),
  );
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form instanceof HTMLFormElement && form.matches("[data-confirm]") && !window.confirm(form.dataset.confirm)) event.preventDefault();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
})();
