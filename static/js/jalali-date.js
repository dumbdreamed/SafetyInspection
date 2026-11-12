(() => {
  let calendarSequence = 0;
  const latinDigits = (value) => String(value).replace(/[۰-۹٠-٩]/g, (digit) => {
    const code = digit.charCodeAt(0);
    return String(code >= 0x06f0 ? code - 0x06f0 : code - 0x0660);
  });
  const persianDigits = (value) => String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
  const monthNames = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
  const weekDays = [
    ["شنبه", "ش"], ["یکشنبه", "ی"], ["دوشنبه", "د"], ["سه‌شنبه", "س"],
    ["چهارشنبه", "چ"], ["پنجشنبه", "پ"], ["جمعه", "ج"],
  ];

  const gregorianToJalali = (date) => {
    let year = date.getUTCFullYear() - 1600;
    const month = date.getUTCMonth();
    const day = date.getUTCDate() - 1;
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let days = 365 * year + Math.floor((year + 3) / 4) - Math.floor((year + 99) / 100) + Math.floor((year + 399) / 400);
    for (let index = 0; index < month; index += 1) days += monthDays[index];
    if (month > 1 && (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0))) days += 1;
    days += day - 79;

    const cycles = Math.floor(days / 12053);
    days %= 12053;
    let jalaliYear = 979 + 33 * cycles + 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days >= 366) {
      jalaliYear += Math.floor((days - 1) / 365);
      days = (days - 1) % 365;
    }
    if (days < 186) return { year: jalaliYear, month: 1 + Math.floor(days / 31), day: 1 + (days % 31) };
    return { year: jalaliYear, month: 7 + Math.floor((days - 186) / 30), day: 1 + ((days - 186) % 30) };
  };

  const isoFromDate = (date) => `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
  const dateFromIso = (value) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return isoFromDate(date) === value ? date : null;
  };
  const findGregorian = (year, month, day) => {
    const start = new Date(Date.UTC(year + 621, 2, 18));
    for (let offset = 0; offset <= 370; offset += 1) {
      const candidate = new Date(start.getTime() + offset * 86400000);
      const parts = gregorianToJalali(candidate);
      if (parts.year === year && parts.month === month && parts.day === day) return candidate;
    }
    return null;
  };
  const parseDisplayDate = (value) => {
    const normalized = latinDigits(value.trim()).replace(/[٫،.\s]/g, "/");
    const parts = /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/.exec(normalized);
    if (!parts) return null;
    const year = Number(parts[1]);
    const month = Number(parts[2]);
    const day = Number(parts[3]);
    if (year >= 1700) {
      const date = new Date(Date.UTC(year, month - 1, day));
      if (date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day) return isoFromDate(date);
      return null;
    }
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    const date = findGregorian(year, month, day);
    return date ? isoFromDate(date) : null;
  };
  const displayFromIso = (value) => {
    const date = dateFromIso(value);
    if (!date) return "";
    const parts = gregorianToJalali(date);
    return persianDigits(`${parts.year}/${String(parts.month).padStart(2, "0")}/${String(parts.day).padStart(2, "0")}`);
  };

  window.PersianCalendar = {
    displayFromIso,
    parseDisplayDate,
  };

  const todayIso = () => {
    const parts = new Intl.DateTimeFormat("en-US-u-ca-gregory-nu-latn", {
      timeZone: "Asia/Tehran", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    return `${values.year}-${values.month}-${values.day}`;
  };
  const makeButton = (className, label, text) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.setAttribute("aria-label", label);
    button.textContent = text;
    return button;
  };
  const formatYear = (year) => persianDigits(year);

  const initializeDateInput = (source) => {
    if (source.dataset.jalaliReady === "true") return;
    source.dataset.jalaliReady = "true";
    const originalId = source.id;
    const wrapper = document.createElement("span");
    wrapper.className = "jalali-date-picker";
    wrapper.dir = "rtl";
    const control = document.createElement("span");
    control.className = "jalali-date-control";
    const display = document.createElement("input");
    display.type = "text";
    display.className = `${source.className || ""} jalali-date-display`.trim();
    display.id = originalId;
    display.placeholder = "۱۴۰۵/۰۸/۲۱";
    display.autocomplete = "off";
    display.inputMode = "numeric";
    display.setAttribute("aria-haspopup", "dialog");
    display.setAttribute("aria-expanded", "false");
    display.setAttribute("aria-label", source.getAttribute("aria-label") || source.closest("label")?.childNodes[0]?.textContent?.trim() || "انتخاب تاریخ شمسی");
    if (source.getAttribute("aria-describedby")) display.setAttribute("aria-describedby", source.getAttribute("aria-describedby"));
    if (source.required) display.required = true;
    if (source.disabled) display.disabled = true;
    if (source.readOnly) display.readOnly = true;
    display.setAttribute("data-jalali-display", "");

    const toggle = makeButton("jalali-calendar-toggle", "نمایش تقویم شمسی", "");
    toggle.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="16" rx="2.5"></rect><path d="M7.5 3.5v3M16.5 3.5v3M3.5 9.5h17"></path></svg>';
    toggle.disabled = source.disabled || source.readOnly;
    toggle.setAttribute("aria-haspopup", "dialog");
    const calendar = document.createElement("section");
    calendar.className = "jalali-date-calendar";
    calendar.id = originalId ? `${originalId}-jalali-calendar` : `jalali-calendar-${++calendarSequence}`;
    calendar.hidden = true;
    calendar.setAttribute("role", "dialog");
    calendar.setAttribute("aria-label", "تقویم هجری شمسی");
    calendar.dir = "rtl";
    display.setAttribute("aria-controls", calendar.id);
    toggle.setAttribute("aria-controls", calendar.id);
    toggle.setAttribute("aria-expanded", "false");
    const header = document.createElement("div");
    header.className = "jalali-calendar-header";
    const previous = makeButton("jalali-calendar-nav", "ماه قبل", "‹");
    const title = document.createElement("strong");
    title.className = "jalali-calendar-title";
    const monthTitle = makeButton("jalali-calendar-month", "انتخاب ماه", "");
    const yearTitle = makeButton("jalali-calendar-year", "انتخاب سال", "");
    title.append(monthTitle, yearTitle);
    const next = makeButton("jalali-calendar-nav", "ماه بعد", "›");
    header.append(previous, title, next);
    const weekdays = document.createElement("div");
    weekdays.className = "jalali-calendar-weekdays";
    weekdays.setAttribute("role", "row");
    weekDays.forEach(([dayName, abbreviation]) => {
      const day = document.createElement("span");
      day.setAttribute("role", "columnheader");
      day.setAttribute("aria-label", dayName);
      day.textContent = abbreviation;
      weekdays.append(day);
    });
    const grid = document.createElement("div");
    grid.className = "jalali-calendar-days";
    grid.setAttribute("role", "grid");
    calendar.append(header, weekdays, grid);
    control.append(display, toggle);
    wrapper.append(control, calendar);

    const fieldName = source.name || "date";
    const minIso = source.min;
    const maxIso = source.max;
    source.before(wrapper);
    source.id = originalId ? `${originalId}-gregorian` : "";
    source.type = "hidden";
    source.removeAttribute("required");
    source.removeAttribute("min");
    source.removeAttribute("max");
    source.setAttribute("aria-hidden", "true");
    source.tabIndex = -1;
    source.classList.add("jalali-date-source");
    source.value = dateFromIso(source.value) ? isoFromDate(dateFromIso(source.value)) : "";
    display.value = displayFromIso(source.value);
    display.dataset.fieldName = fieldName;

    const todayParts = gregorianToJalali(dateFromIso(todayIso()));
    const selectedParts = source.value ? gregorianToJalali(dateFromIso(source.value)) : todayParts;
    let shownYear = selectedParts.year;
    let shownMonth = selectedParts.month;
    let selectedIso = source.value;
    let view = "days";
    let yearPage = Math.floor(shownYear / 12) * 12;
    const periodAllowed = (year, month = null) => {
      const start = findGregorian(year, month || 1, 1);
      const end = month === 12 || month === null
        ? findGregorian(year + 1, 1, 1)
        : findGregorian(year, month + 1, 1);
      return start && end && (!minIso || isoFromDate(new Date(end.getTime() - 86400000)) >= minIso)
        && (!maxIso || isoFromDate(start) <= maxIso);
    };

    const close = (returnFocus = false) => {
      calendar.hidden = true;
      display.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-expanded", "false");
      if (returnFocus) display.focus();
    };
    const updateValue = (iso, updateMonth = true) => {
      selectedIso = iso;
      source.value = iso;
      display.value = displayFromIso(iso);
      display.setCustomValidity("");
      display.removeAttribute("aria-invalid");
      if (updateMonth) {
        const selected = gregorianToJalali(dateFromIso(iso));
        shownYear = selected.year;
        shownMonth = selected.month;
      }
      source.dispatchEvent(new Event("input", { bubbles: true }));
      source.dispatchEvent(new Event("change", { bubbles: true }));
      renderCalendar();
    };
    const renderCalendar = () => {
      monthTitle.textContent = monthNames[shownMonth - 1];
      yearTitle.textContent = formatYear(shownYear);
      weekdays.hidden = view !== "days";
      grid.classList.toggle("is-period-view", view !== "days");
      grid.setAttribute("aria-label", view === "years" ? "انتخاب سال شمسی" : view === "months" ? "انتخاب ماه شمسی" : "انتخاب روز شمسی");
      previous.setAttribute("aria-label", view === "years" ? "دوازده سال قبل" : view === "months" ? "سال قبل" : "ماه قبل");
      next.setAttribute("aria-label", view === "years" ? "دوازده سال بعد" : view === "months" ? "سال بعد" : "ماه بعد");
      yearTitle.textContent = view === "years" ? `${formatYear(yearPage)}–${formatYear(yearPage + 11)}` : formatYear(shownYear);
      grid.replaceChildren();
      if (view !== "days") {
        const selectingYear = view === "years";
        for (let index = 0; index < 12; index += 1) {
          const value = selectingYear ? yearPage + index : index + 1;
          const label = selectingYear ? formatYear(value) : monthNames[index];
          const button = makeButton("jalali-calendar-day jalali-calendar-period", label, label);
          const active = selectingYear ? value === shownYear : value === shownMonth;
          button.setAttribute("aria-pressed", String(active));
          if (active) button.classList.add("is-selected");
          button.disabled = !periodAllowed(selectingYear ? value : shownYear, selectingYear ? null : value);
          button.addEventListener("click", () => {
            if (selectingYear) { shownYear = value; view = "months"; }
            else { shownMonth = value; view = "days"; }
            renderCalendar();
            (view === "days" ? grid.querySelector(".is-selected, :not(.is-outside-month):not(:disabled)") : grid.querySelector(".is-selected, :not(:disabled)"))?.focus();
          });
          grid.append(button);
        }
        return;
      }
      const firstDay = findGregorian(shownYear, shownMonth, 1);
      if (!firstDay) return;
      const today = todayIso();
      const emptySlots = (firstDay.getUTCDay() + 1) % 7;
      const firstVisibleDate = new Date(firstDay.getTime() - emptySlots * 86400000);
      for (let offset = 0; offset < 42; offset += 1) {
        const date = new Date(firstVisibleDate.getTime() + offset * 86400000);
        const parts = gregorianToJalali(date);
        const iso = isoFromDate(date);
        const isCurrentMonth = parts.year === shownYear && parts.month === shownMonth;
        const dayButton = makeButton(
          `jalali-calendar-day${isCurrentMonth ? "" : " is-outside-month"}`,
          `روز ${persianDigits(parts.day)} ${monthNames[parts.month - 1]} ${persianDigits(parts.year)}`,
          persianDigits(parts.day),
        );
        dayButton.setAttribute("role", "gridcell");
        dayButton.setAttribute("aria-pressed", String(iso === selectedIso));
        if (iso === selectedIso) dayButton.classList.add("is-selected");
        if (iso === today) dayButton.classList.add("is-today");
        if (minIso && iso < minIso || maxIso && iso > maxIso) dayButton.disabled = true;
        dayButton.addEventListener("click", () => { updateValue(iso); close(); });
        grid.append(dayButton);
      }
    };
    const shiftMonth = (amount) => {
      if (view === "years") { yearPage += amount * 12; renderCalendar(); return; }
      if (view === "months") { shownYear += amount; renderCalendar(); return; }
      shownMonth += amount;
      if (shownMonth < 1) { shownMonth = 12; shownYear -= 1; }
      if (shownMonth > 12) { shownMonth = 1; shownYear += 1; }
      renderCalendar();
    };
    const open = () => {
      if (display.disabled || display.readOnly) return;
      const rect = wrapper.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      calendar.classList.toggle("opens-above", spaceBelow < 370 && spaceAbove > spaceBelow);
      calendar.hidden = false;
      display.setAttribute("aria-expanded", "true");
      toggle.setAttribute("aria-expanded", "true");
      renderCalendar();
    };
    const validateTypedDate = () => {
      const typed = display.value.trim();
      if (!typed) {
        source.value = "";
        display.setCustomValidity(display.required ? "لطفاً تاریخ را به تقویم شمسی وارد کنید." : "");
        if (display.required) display.setAttribute("aria-invalid", "true");
        else display.removeAttribute("aria-invalid");
        return;
      }
      const iso = parseDisplayDate(typed);
      const withinBounds = iso && (!minIso || iso >= minIso) && (!maxIso || iso <= maxIso);
      if (!withinBounds) {
        source.value = "";
        display.setCustomValidity("تاریخ شمسی معتبر نیست یا خارج از محدوده مجاز است.");
        display.setAttribute("aria-invalid", "true");
        return;
      }
      updateValue(iso, false);
    };
    previous.addEventListener("click", () => shiftMonth(-1));
    next.addEventListener("click", () => shiftMonth(1));
    monthTitle.addEventListener("click", () => { view = view === "months" ? "days" : "months"; renderCalendar(); });
    yearTitle.addEventListener("click", () => {
      view = view === "years" ? "days" : "years";
      yearPage = Math.floor(shownYear / 12) * 12;
      renderCalendar();
    });
    toggle.addEventListener("click", () => calendar.hidden ? open() : close());
    display.addEventListener("focus", open);
    display.addEventListener("input", validateTypedDate);
    display.addEventListener("change", validateTypedDate);
    document.addEventListener("pointerdown", (event) => {
      if (!calendar.hidden && !wrapper.contains(event.target)) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !calendar.hidden) close(true);
    });
    window.addEventListener("resize", () => { if (!calendar.hidden) open(); });
    window.addEventListener("scroll", () => { if (!calendar.hidden) open(); }, true);
    source.form?.addEventListener("submit", (event) => {
      validateTypedDate();
      if (!display.checkValidity()) {
        event.preventDefault();
        display.reportValidity();
      }
    });
    renderCalendar();
  };

  const enhance = (root = document) => {
    if (root.matches?.('input[type="date"]')) initializeDateInput(root);
    root.querySelectorAll?.('input[type="date"]').forEach(initializeDateInput);
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => enhance());
  else enhance();
  new MutationObserver((mutations) => mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
    if (node instanceof Element) enhance(node);
  }))).observe(document.documentElement, { childList: true, subtree: true });
})();
