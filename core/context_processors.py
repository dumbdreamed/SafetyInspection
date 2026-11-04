def navigation(request):
    user = request.user
    manager = user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["Administrator", "Safety Manager"]).exists())
    editor = manager or (user.is_authenticated and user.groups.filter(name="Inspector").exists())
    return {"nav_items": [
        ("داشبورد", "dashboard", "⌂"), ("تجهیزات", "equipment_list", "▣"),
        ("رانندگان و اپراتورها", "people_list", "♙"), ("بازرسی‌ها", "inspection_list", "✓"),
        ("اقدامات اصلاحی", "finding_list", "⚠"), ("مدارک", "document_new", "▤"),
        ("تعمیر و نگهداری", "maintenance_list", "⚙"), ("گزارش‌ها", "reports", "▥"),
        ("تنظیمات", "settings_page", "☷"),
    ], "can_manage": manager, "can_edit": editor}
