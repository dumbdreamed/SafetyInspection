from django.conf import settings


def navigation(request):
    user = request.user
    manager = user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["Administrator", "Safety Manager"]).exists())
    editor = manager or (user.is_authenticated and user.groups.filter(name="Inspector").exists())
    return {"nav_items": [
        ("داشبورد", "dashboard", "layout-dashboard"), ("تجهیزات", "equipment_list", "truck"),
        ("مدیریت پرسنل", "people_list", "users-round"), ("بازرسی‌ها", "inspection_list", "clipboard-check"),
        ("اقدامات اصلاحی", "finding_list", "clipboard-list"), ("مدارک", "document_new", "files"),
        ("تعمیر و نگهداری", "maintenance_list", "wrench"), ("گزارش‌ها", "reports", "chart-column"),
        ("تنظیمات", "settings_page", "settings-2"),
    ], "can_manage": manager, "can_edit": editor,
        "storage_is_ephemeral": not settings.DEBUG and not settings.PERSISTENCE_CONFIRMED}
