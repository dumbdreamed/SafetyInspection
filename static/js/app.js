(() => {
  const body = document.body;
  const toggle = document.querySelector("[data-menu-toggle]");
  const overlay = document.querySelector("[data-menu-close]");
  const closeMenu = () => {
    body.classList.remove("menu-open");
    toggle?.setAttribute("aria-expanded", "false");
  };
  toggle?.addEventListener("click", () => {
    const open = body.classList.toggle("menu-open");
    toggle.setAttribute("aria-expanded", String(open));
  });
  overlay?.addEventListener("click", closeMenu);
  document.querySelectorAll("[data-dismiss]").forEach((button) =>
    button.addEventListener("click", () => button.closest(".flash")?.remove()),
  );
  document.querySelectorAll("[data-confirm]").forEach((form) =>
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    }),
  );
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
})();
