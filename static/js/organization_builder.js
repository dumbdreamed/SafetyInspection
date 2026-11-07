(() => {
  const defaultRoleLabels = {
    top: 'مدیر ارشد', middle: 'مدیر میانی', supervisor: 'سرپرست',
    employee: 'کارمند', other: 'سایر نقش‌ها',
  };
  const managerial = new Set(['top', 'middle', 'supervisor']);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);

  const initialize = (form) => {
    const builder = form?.querySelector('[data-org-builder]');
    if (!builder || builder.dataset.initialized) return;
    builder.dataset.initialized = 'true';
    const membersField = form.querySelector('[name="members"]');
    const structureField = form.querySelector('[name="structure"]');
    const roleLabelsField = form.querySelector('[name="role_labels"]');
    const roster = builder.querySelector('[data-org-roster]');
    const world = builder.querySelector('[data-org-builder-world]');
    const stage = builder.querySelector('[data-org-builder-stage]');
    const search = builder.querySelector('[data-org-builder-search]');
    const feedback = builder.querySelector('[data-org-builder-feedback]');
    const zoomOutput = builder.querySelector('[data-org-zoom]');
    const zoomInButton = builder.querySelector('[data-org-zoom-in]');
    const zoomOutButton = builder.querySelector('[data-org-zoom-out]');
    const fitCanvasButton = builder.querySelector('[data-org-builder-fit]');
    let canvasScale = 1, canvasX = 0, canvasY = 0, canvasDrag = null;
    let roleLabels;
    try { roleLabels = JSON.parse(roleLabelsField?.value || '{}'); } catch (_) { roleLabels = {}; }
    roleLabels = { ...defaultRoleLabels, ...(roleLabels && typeof roleLabels === 'object' && !Array.isArray(roleLabels) ? roleLabels : {}) };
    Object.keys(defaultRoleLabels).forEach((level) => {
      roleLabels[level] = String(roleLabels[level] || defaultRoleLabels[level]).trim().slice(0, 40) || defaultRoleLabels[level];
      const input = builder.querySelector(`[data-org-role-label-input="${level}"]`);
      if (input) input.value = roleLabels[level];
    });
    const people = [...(membersField?.options || [])].map((option) => ({ id: option.value, label: option.textContent.trim() }));
    const personById = new Map(people.map((person) => [person.id, person]));
    const makeRoot = () => ({ key: `slot-${crypto.randomUUID()}`, person: null, level: 'top', title: 'مدیر ارشد کارخانه', manager: null });
    let slots;
    try { slots = JSON.parse(structureField?.value || '[]'); } catch (_) { slots = []; }
    if (!Array.isArray(slots) || !slots.length) slots = [makeRoot()];
    slots = slots.map((item) => ({
      key: String(item.key || `slot-${crypto.randomUUID()}`),
      person: item.person == null ? null : String(item.person),
      level: defaultRoleLabels[item.level] ? item.level : 'employee',
      title: String(item.title || roleLabels[item.level] || roleLabels.employee),
      manager: item.manager == null ? null : String(item.manager),
    }));
    let focusedSlot = slots[0]?.key;
    const selectedPeople = new Set();

    const tell = (text, isError = false) => {
      if (!feedback) return;
      feedback.textContent = text;
      feedback.classList.toggle('is-error', isError);
    };
    const renderCanvas = () => {
      if (!world) return;
      world.style.transform = `translate(${canvasX}px, ${canvasY}px) scale(${canvasScale})`;
      if (zoomOutput) zoomOutput.textContent = `${new Intl.NumberFormat('fa-IR').format(Math.round(canvasScale * 100))}٪`;
    };
    const zoomCanvas = (factor, x = stage?.clientWidth / 2, y = stage?.clientHeight / 2) => {
      if (!stage || !world) return;
      const next = Math.min(2.5, Math.max(.03, canvasScale * factor));
      canvasX = x - (x - canvasX) * next / canvasScale;
      canvasY = y - (y - canvasY) * next / canvasScale;
      canvasScale = next;
      renderCanvas();
    };
    const fitCanvas = () => {
      if (!stage || !world || !stage.clientWidth || !stage.clientHeight) return;
      const width = world.offsetWidth, height = world.offsetHeight;
      if (!width || !height) return;
      canvasScale = Math.max(.03, Math.min(1, (stage.clientWidth - 32) / width, (stage.clientHeight - 32) / height));
      canvasX = (stage.clientWidth - width * canvasScale) / 2;
      canvasY = (stage.clientHeight - height * canvasScale) / 2;
      renderCanvas();
    };
    const childrenOf = (key) => slots.filter((item) => item.manager === key);
    const syncMembers = () => {
      if (!membersField) return;
      const assigned = new Set(slots.filter((item) => item.person).map((item) => item.person));
      [...membersField.options].forEach((option) => { option.selected = assigned.has(option.value); });
    };
    const syncStructure = () => {
      if (structureField) structureField.value = JSON.stringify(slots);
      syncMembers();
    };
    const syncRoleLabels = () => {
      if (roleLabelsField) roleLabelsField.value = JSON.stringify(roleLabels);
    };
    const refreshRoleLabel = (level) => {
      const label = roleLabels[level] || defaultRoleLabels[level];
      world?.querySelectorAll(`[data-org-role-badge="${level}"]`).forEach((element) => { element.textContent = label; });
      world?.querySelectorAll(`[data-org-slot-level] option[value="${level}"]`).forEach((element) => { element.textContent = label; });
      world?.querySelectorAll(`[data-org-add-child="${level}"]`).forEach((element) => { element.textContent = `＋ ${label}`; });
    };
    const assign = (key, personId) => {
      const slot = slots.find((item) => item.key === key);
      if (!slot) return;
      if (personId == null || String(personId) === '') {
        slot.person = null;
        focusedSlot = key;
        tell('فرد از جایگاه برداشته شد.');
        render();
        return;
      }
      if (!personById.has(String(personId))) return;
      const id = String(personId);
      const previousSlot = slots.find((item) => item.key !== key && item.person === id);
      if (previousSlot) {
        previousSlot.person = null;
        const hasReports = slots.some((item) => item.manager === previousSlot.key);
        if (!hasReports && previousSlot.manager !== null) slots = slots.filter((item) => item.key !== previousSlot.key);
      }
      selectedPeople.delete(id);
      slot.person = id;
      focusedSlot = key;
      tell('فرد در جایگاه انتخاب‌شده قرار گرفت.');
      render();
    };
    const managerFor = (key) => {
      let current = slots.find((item) => item.key === key);
      const seen = new Set();
      while (current && !seen.has(current.key)) {
        if (managerial.has(current.level)) return current;
        seen.add(current.key);
        current = slots.find((item) => item.key === current.manager);
      }
      return slots.find((item) => item.manager == null && managerial.has(item.level)) || null;
    };
    const addSlot = (parentKey, level, personId = null) => {
      const parent = slots.find((item) => item.key === parentKey);
      if (!parent || !managerial.has(parent.level)) return;
      if (!['middle', 'supervisor', 'employee', 'other'].includes(level)) return;
      const slot = {
        key: `slot-${crypto.randomUUID()}`, person: personId ? String(personId) : null,
        level, title: roleLabels[level], manager: parentKey,
      };
      slots.push(slot);
      focusedSlot = managerial.has(level) ? slot.key : parentKey;
      tell('جایگاه جدید به نمودار اضافه شد.');
      render();
    };
    const addPeopleUnder = (parentKey, personIds, level) => {
      const parent = slots.find((item) => item.key === parentKey);
      if (!parent || !managerial.has(parent.level)) return false;
      const assigned = new Set(slots.filter((item) => item.person).map((item) => item.person));
      const selected = [...new Set(personIds.map(String))].filter((id) => personById.has(id) && !assigned.has(id));
      if (!selected.length) return false;
      if (!['middle', 'supervisor', 'employee'].includes(level)) level = 'employee';
      selected.forEach((personId) => slots.push({
        key: `slot-${crypto.randomUUID()}`, person: personId,
        level, title: roleLabels[level], manager: parent.key,
      }));
      selected.forEach((id) => selectedPeople.delete(id));
      focusedSlot = parent.key;
      tell(`${new Intl.NumberFormat('fa-IR').format(selected.length)} نفر به زیرمجموعه این مدیر اضافه شدند.`);
      render();
      return true;
    };
    const addPaletteRole = (level, targetKey = focusedSlot) => {
      if (level === 'top') {
        const root = slots.find((item) => item.manager == null);
        if (root) {
          focusedSlot = root.key;
          render();
          tell('جایگاه مدیر ارشد، ریشه چارت است. افراد را روی همین کارت قرار دهید.');
        }
        return;
      }
      const parent = managerFor(targetKey);
      if (!parent) { tell('ابتدا یک جایگاه مدیریتی در قالب ایجاد کنید.', true); return; }
      addSlot(parent.key, level);
    };
    const removeSlot = (key) => {
      const slot = slots.find((item) => item.key === key);
      if (!slot || slot.manager == null) return;
      const removeKeys = new Set([key]);
      let added = true;
      while (added) {
        added = false;
        slots.forEach((item) => {
          if (removeKeys.has(item.manager) && !removeKeys.has(item.key)) { removeKeys.add(item.key); added = true; }
        });
      }
      if (removeKeys.size > 1 && !window.confirm('این جایگاه و همه زیرمجموعه‌های آن حذف شوند؟ افراد دوباره به فهرست پرسنل برمی‌گردند.')) return;
      slots = slots.filter((item) => !removeKeys.has(item.key));
      focusedSlot = slots[0]?.key;
      tell('جایگاه حذف شد؛ افراد آن به فهرست پرسنل برگشتند.');
      render();
    };

    const renderRoster = () => {
      if (!roster) return;
      const query = (search?.value || '').trim().toLocaleLowerCase();
      const assigned = new Set(slots.filter((item) => item.person).map((item) => item.person));
      const available = people.filter((person) => !assigned.has(person.id) && person.label.toLocaleLowerCase().includes(query));
      selectedPeople.forEach((id) => { if (assigned.has(id)) selectedPeople.delete(id); });
      builder.querySelector('[data-org-roster-count]').textContent = `${new Intl.NumberFormat('fa-IR').format(available.length)} نفر در دسترس`;
      roster.innerHTML = available.length ? available.map((person) => `
        <div class="org-builder-person" role="group" tabindex="0" draggable="true" data-org-person="${escapeHtml(person.id)}" aria-label="${escapeHtml(person.label)}">
          <input type="checkbox" class="org-builder-person-check" data-org-select-person="${escapeHtml(person.id)}" aria-label="انتخاب ${escapeHtml(person.label)}" ${selectedPeople.has(person.id) ? 'checked' : ''}>
          <span class="org-builder-person-copy"><strong>${escapeHtml(person.label.split('—')[0].trim())}</strong><small>${escapeHtml(person.label.includes('—') ? person.label.split('—').slice(1).join('—').trim() : 'پرسنل')}</small></span>
          <button type="button" class="org-builder-person-add" data-org-add-person="${escapeHtml(person.id)}" aria-label="افزودن ${escapeHtml(person.label)}">＋</button>
        </div>`).join('') : '<p class="org-builder-roster-empty">فردی با این جست‌وجو در دسترس نیست.</p>';
      const managerSelect = builder.querySelector('[data-org-bulk-manager]');
      const previousManager = managerSelect?.value;
      const managers = slots.filter((item) => managerial.has(item.level));
      if (managerSelect) {
        managerSelect.innerHTML = managers.map((item) => {
          const person = item.person ? personById.get(item.person) : null;
          return `<option value="${escapeHtml(item.key)}">${escapeHtml(item.title || roleLabels[item.level])} · ${escapeHtml(person?.label || 'جایگاه خالی')}</option>`;
        }).join('');
        const preferred = managers.find((item) => item.key === previousManager)
          || managers.find((item) => item.key === focusedSlot) || managers[0];
        managerSelect.value = preferred?.key || '';
      }
      const count = selectedPeople.size;
      const countLabel = builder.querySelector('[data-org-selected-count]');
      if (countLabel) countLabel.textContent = `${new Intl.NumberFormat('fa-IR').format(count)} نفر انتخاب شده`;
      const clearSelectionButton = builder.querySelector('[data-org-clear-selection]');
      if (clearSelectionButton) clearSelectionButton.disabled = count === 0;
      const selectedList = builder.querySelector('[data-org-selected-list]');
      if (selectedList) {
        const selected = [...selectedPeople].map((id) => personById.get(id)).filter(Boolean);
        selectedList.innerHTML = selected.length
          ? selected.map((person) => `<span class="org-builder-selected-chip"><span>${escapeHtml(person.label)}</span><button type="button" data-org-deselect-person="${escapeHtml(person.id)}" aria-label="لغو انتخاب ${escapeHtml(person.label)}" title="لغو انتخاب">×</button></span>`).join('')
          : '<span class="org-builder-no-selection">هنوز فردی انتخاب نشده است.</span>';
      }
      const selectVisible = builder.querySelector('[data-org-select-visible]');
      if (selectVisible) {
        const visibleIds = available.map((person) => person.id);
        const selectedVisible = visibleIds.filter((id) => selectedPeople.has(id)).length;
        selectVisible.checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
        selectVisible.indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;
      }
      const addSelectedButton = builder.querySelector('[data-org-add-selected]');
      if (addSelectedButton) addSelectedButton.disabled = count === 0 || managers.length === 0;
    };

    const renderSlot = (slot, depth = 0) => {
      const person = slot.person ? personById.get(slot.person) : null;
      const roleOptions = (depth === 0 ? ['top'] : ['middle', 'supervisor', 'employee', 'other']).map((level) =>
        `<option value="${level}" ${slot.level === level ? 'selected' : ''}>${escapeHtml(roleLabels[level])}</option>`).join('');
      const personOptions = ['<option value="">انتخاب فرد برای این جایگاه…</option>', ...people.map((entry) => {
        return `<option value="${escapeHtml(entry.id)}" ${slot.person === entry.id ? 'selected' : ''}>${escapeHtml(entry.label)}</option>`;
      })].join('');
      const children = slots.filter((item) => item.manager === slot.key);
      const actions = managerial.has(slot.level) ? `
        <div class="org-builder-slot-actions">
          <button type="button" data-org-add-child="middle" data-org-parent="${escapeHtml(slot.key)}">＋ ${escapeHtml(roleLabels.middle)}</button>
          <button type="button" data-org-add-child="supervisor" data-org-parent="${escapeHtml(slot.key)}">＋ ${escapeHtml(roleLabels.supervisor)}</button>
          <button type="button" data-org-add-child="employee" data-org-parent="${escapeHtml(slot.key)}">＋ ${escapeHtml(roleLabels.employee)}</button>
        </div>` : '';
      const childMarkup = children.length ? `<ul class="org-builder-children">${children.map((child) => renderSlot(child, depth + 1)).join('')}</ul>` : '';
      return `<li class="org-builder-branch">
        <article class="org-builder-slot ${focusedSlot === slot.key ? 'is-focused' : ''}" data-org-slot="${escapeHtml(slot.key)}" data-org-dropzone="${escapeHtml(slot.key)}">
          <div class="org-builder-slot-heading"><span class="org-builder-role role-${slot.level}" data-org-role-badge="${slot.level}">${escapeHtml(roleLabels[slot.level])}</span>${depth ? `<button type="button" class="org-builder-slot-remove" data-org-remove-slot="${escapeHtml(slot.key)}" aria-label="حذف جایگاه">×</button>` : ''}</div>
          <div class="org-builder-slot-person ${person ? 'has-person' : ''}" data-org-slot-focus="${escapeHtml(slot.key)}">
            <span class="org-builder-slot-avatar" aria-hidden="true">${person ? escapeHtml(person.label.trim().slice(0, 1)) : '＋'}</span>
            <strong>${person ? escapeHtml(person.label.split('—')[0].trim()) : 'فردی را اینجا رها کنید'}</strong>
            <small>${person ? escapeHtml(person.label.includes('—') ? person.label.split('—').slice(1).join('—').trim() : '') : 'یا از فهرست پایین انتخاب کنید'}</small>
          </div>
          <label class="org-builder-control">فرد<select data-org-slot-person="${escapeHtml(slot.key)}">${personOptions}</select></label>
          <label class="org-builder-control">نقش<select data-org-slot-level="${escapeHtml(slot.key)}" ${depth === 0 ? 'disabled' : ''}>${roleOptions}</select></label>
          <label class="org-builder-control">عنوان<input type="text" maxlength="120" data-org-slot-title="${escapeHtml(slot.key)}" value="${escapeHtml(slot.title)}"></label>
          ${actions}
        </article>${childMarkup}
      </li>`;
    };

    function render() {
      if (!world) return;
      const roots = slots.filter((item) => item.manager == null);
      roots.sort((a, b) => a.key.localeCompare(b.key));
      world.innerHTML = roots.length
        ? `<ul class="org-builder-tree">${roots.map((item) => renderSlot(item)).join('')}</ul>`
        : '<div class="org-builder-invalid">قالب چارت ریشه ندارد. یک جایگاه مدیر ارشد اضافه کنید.</div>';
      renderCanvas();
      renderRoster();
      syncStructure();
    }

    search?.addEventListener('input', renderRoster);
    builder.querySelector('[data-org-role-palette]')?.addEventListener('input', (event) => {
      const input = event.target.closest('[data-org-role-label-input]');
      if (!input) return;
      const level = input.dataset.orgRoleLabelInput;
      roleLabels[level] = input.value.trim() || defaultRoleLabels[level];
      syncRoleLabels();
      refreshRoleLabel(level);
    });
    builder.querySelector('[data-org-role-palette]')?.addEventListener('change', (event) => {
      const input = event.target.closest('[data-org-role-label-input]');
      if (!input) return;
      input.value = input.value.trim() || defaultRoleLabels[input.dataset.orgRoleLabelInput];
      roleLabels[input.dataset.orgRoleLabelInput] = input.value;
      syncRoleLabels();
      refreshRoleLabel(input.dataset.orgRoleLabelInput);
    });
    roster?.addEventListener('dragstart', (event) => {
      const person = event.target.closest('[data-org-person]');
      if (!person) return;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', person.dataset.orgPerson);
      event.dataTransfer.setData('application/x-org-person', person.dataset.orgPerson);
    });
    roster?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-org-add-person]');
      if (!button) return;
      const id = button.dataset.orgAddPerson;
      let target = slots.find((item) => item.key === focusedSlot);
      if (target?.person && !managerial.has(target.level)) target = slots.find((item) => item.key === 'slot-root') || slots.find((item) => item.level === 'top');
      if (!target) target = slots.find((item) => item.manager == null);
      if (target && !target.person) assign(target.key, id);
      else if (target && managerial.has(target.level)) addSlot(target.key, 'employee', id);
      else tell('ابتدا جایگاه مدیر ارشد یا یک مدیر مستقیم ایجاد کنید.', true);
    });
    roster?.addEventListener('change', (event) => {
      const checkbox = event.target.closest('[data-org-select-person]');
      if (!checkbox) return;
      if (checkbox.checked) selectedPeople.add(checkbox.dataset.orgSelectPerson);
      else selectedPeople.delete(checkbox.dataset.orgSelectPerson);
      renderRoster();
    });
    roster?.addEventListener('keydown', (event) => {
      if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('[data-org-person]')) {
        event.preventDefault();
        const id = event.target.dataset.orgPerson;
        const target = slots.find((item) => item.key === focusedSlot);
        if (target && !target.person) assign(target.key, id);
        else tell('یک جایگاه خالی را در قالب انتخاب کنید.', true);
      }
    });
    builder.querySelector('[data-org-select-visible]')?.addEventListener('change', (event) => {
      const visibleIds = [...roster.querySelectorAll('[data-org-select-person]')].map((input) => input.dataset.orgSelectPerson);
      visibleIds.forEach((id) => event.target.checked ? selectedPeople.add(id) : selectedPeople.delete(id));
      renderRoster();
    });
    builder.querySelector('[data-org-clear-selection]')?.addEventListener('click', () => {
      selectedPeople.clear();
      renderRoster();
    });
    builder.querySelector('[data-org-selected-list]')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-org-deselect-person]');
      if (!button) return;
      selectedPeople.delete(button.dataset.orgDeselectPerson);
      renderRoster();
    });
    builder.querySelector('[data-org-add-selected]')?.addEventListener('click', () => {
      const managerKey = builder.querySelector('[data-org-bulk-manager]')?.value;
      const level = builder.querySelector('[data-org-bulk-level]')?.value || 'employee';
      const parent = slots.find((item) => item.key === managerKey);
      if (!parent || !managerial.has(parent.level)) {
        tell('برای افزودن چند نفر، جایگاه مدیر مستقیم را انتخاب کنید.', true);
        return;
      }
      if (!selectedPeople.size) { tell('ابتدا افراد موردنظر را انتخاب کنید.', true); return; }
      addPeopleUnder(parent.key, [...selectedPeople], level);
    });
    builder.addEventListener('dragstart', (event) => {
      const tool = event.target.closest('[data-org-add-role][draggable="true"]');
      if (!tool) return;
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData('application/x-org-role', tool.dataset.orgAddRole);
      event.dataTransfer.setData('text/plain', `role:${tool.dataset.orgAddRole}`);
    });
    stage?.addEventListener('dragover', (event) => {
      const isPerson = event.dataTransfer.types.includes('application/x-org-person');
      const isRole = event.dataTransfer.types.includes('application/x-org-role');
      if (!isPerson && !isRole) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = isRole ? 'copy' : 'move';
      event.target.closest('[data-org-dropzone]')?.classList.add('is-drop-target');
    });
    stage?.addEventListener('dragleave', (event) => {
      const zone = event.target.closest('[data-org-dropzone]');
      if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-drop-target');
    });
    stage?.addEventListener('drop', (event) => {
      const zone = event.target.closest('[data-org-dropzone]');
      const role = event.dataTransfer.getData('application/x-org-role');
      const id = event.dataTransfer.getData('application/x-org-person');
      if (!zone && !role) return;
      event.preventDefault();
      zone?.classList.remove('is-drop-target');
      if (role) {
        const parent = managerFor(zone?.dataset.orgDropzone || focusedSlot);
        if (parent) addSlot(parent.key, role);
        else tell('ابتدا یک جایگاه مدیریتی اضافه کنید.', true);
        return;
      }
      if (!id || !zone) return;
      const target = slots.find((item) => item.key === zone.dataset.orgDropzone);
      const bulkLevel = builder.querySelector('[data-org-bulk-level]')?.value || 'employee';
      if (target && selectedPeople.size > 1 && selectedPeople.has(id)) {
        const parent = managerFor(target.key);
        if (parent) addPeopleUnder(parent.key, [...selectedPeople], bulkLevel);
        else tell('جایگاه مناسبی برای گزارش مستقیم این افراد پیدا نشد.', true);
      } else assign(zone.dataset.orgDropzone, id);
    });
    zoomInButton?.addEventListener('click', () => zoomCanvas(1.2));
    zoomOutButton?.addEventListener('click', () => zoomCanvas(1 / 1.2));
    fitCanvasButton?.addEventListener('click', fitCanvas);
    stage?.addEventListener('wheel', (event) => {
      event.preventDefault();
      const rect = stage.getBoundingClientRect();
      zoomCanvas(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX - rect.left - stage.clientLeft, event.clientY - rect.top - stage.clientTop);
    }, { passive: false });
    stage?.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || event.target.closest('button,input,select,textarea,a,[draggable="true"],.org-builder-slot')) return;
      canvasDrag = { id: event.pointerId, x: event.clientX, y: event.clientY, originX: canvasX, originY: canvasY };
      stage.setPointerCapture(event.pointerId);
      stage.classList.add('is-panning');
    });
    stage?.addEventListener('pointermove', (event) => {
      if (!canvasDrag || canvasDrag.id !== event.pointerId) return;
      canvasX = canvasDrag.originX + event.clientX - canvasDrag.x;
      canvasY = canvasDrag.originY + event.clientY - canvasDrag.y;
      renderCanvas();
    });
    const endCanvasDrag = (event) => {
      if (!canvasDrag || canvasDrag.id !== event.pointerId) return;
      canvasDrag = null;
      stage.classList.remove('is-panning');
    };
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((name) => stage?.addEventListener(name, endCanvasDrag));
    stage?.addEventListener('keydown', (event) => {
      if (event.target !== stage) return;
      if (event.key === 'ArrowLeft') canvasX += 40;
      else if (event.key === 'ArrowRight') canvasX -= 40;
      else if (event.key === 'ArrowUp') canvasY += 40;
      else if (event.key === 'ArrowDown') canvasY -= 40;
      else if (event.key === '+' || event.key === '=') { zoomCanvas(1.2); event.preventDefault(); return; }
      else if (event.key === '-') { zoomCanvas(1 / 1.2); event.preventDefault(); return; }
      else return;
      event.preventDefault();
      renderCanvas();
    });
    builder.querySelector('[data-org-role-palette]')?.addEventListener('click', (event) => {
      const tool = event.target.closest('[data-org-add-role]');
      if (tool) addPaletteRole(tool.dataset.orgAddRole);
    });
    world?.addEventListener('click', (event) => {
      const add = event.target.closest('[data-org-add-child]');
      if (add) { addSlot(add.dataset.orgParent, add.dataset.orgAddChild); return; }
      const remove = event.target.closest('[data-org-remove-slot]');
      if (remove) { removeSlot(remove.dataset.orgRemoveSlot); return; }
      const focus = event.target.closest('[data-org-slot-focus]');
      if (focus) {
        focusedSlot = focus.dataset.orgSlotFocus;
        world.querySelectorAll('.org-builder-slot.is-focused').forEach((item) => item.classList.remove('is-focused'));
        focus.closest('.org-builder-slot')?.classList.add('is-focused');
        return;
      }
      const card = event.target.closest('[data-org-slot]');
      if (card) {
        focusedSlot = card.dataset.orgSlot;
        world.querySelectorAll('.org-builder-slot.is-focused').forEach((item) => item.classList.remove('is-focused'));
        card.classList.add('is-focused');
      }
    });
    world?.addEventListener('change', (event) => {
      const personControl = event.target.closest('[data-org-slot-person]');
      if (personControl) { assign(personControl.dataset.orgSlotPerson, personControl.value); return; }
      const levelControl = event.target.closest('[data-org-slot-level]');
      if (levelControl) {
        const slot = slots.find((item) => item.key === levelControl.dataset.orgSlotLevel);
        const hasChildren = slot && slots.some((item) => item.manager === slot.key);
        if (!slot) return;
        if (hasChildren && !managerial.has(levelControl.value)) {
          tell('برای جایگاهی که زیرمجموعه دارد، نقش مدیر یا سرپرست انتخاب کنید.', true);
          levelControl.value = slot.level;
          return;
        }
        slot.level = levelControl.value;
        if (!slot.title || Object.values(defaultRoleLabels).includes(slot.title) || Object.values(roleLabels).includes(slot.title)) slot.title = roleLabels[slot.level];
        focusedSlot = slot.key;
        render();
        return;
      }
      const titleControl = event.target.closest('[data-org-slot-title]');
      if (titleControl) {
        const slot = slots.find((item) => item.key === titleControl.dataset.orgSlotTitle);
        if (slot) { slot.title = titleControl.value.trim(); syncStructure(); }
      }
    });
    world?.addEventListener('input', (event) => {
      const titleControl = event.target.closest('[data-org-slot-title]');
      if (titleControl) {
        const slot = slots.find((item) => item.key === titleControl.dataset.orgSlotTitle);
        if (slot) { slot.title = titleControl.value; syncStructure(); }
      }
    });
    form.addEventListener('submit', syncStructure);
    form.addEventListener('submit', syncRoleLabels);
    syncRoleLabels();
    render();
    requestAnimationFrame(() => requestAnimationFrame(fitCanvas));
  };

  window.initOrganizationBuilder = initialize;
  document.querySelectorAll('[data-org-cluster-form]').forEach(initialize);
})();
