from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import (ChecklistItem, ChecklistTemplate, DocumentCategory,
                         EquipmentType, QualificationType)


TYPES = [
    "کامیون", "جرثقیل متحرک", "جرثقیل سقفی", "لیفتراک", "لودر", "تریلی",
    "بیل مکانیکی", "بیل بکهو", "تانکر آبپاش", "تراکتور", "تراک میکسر",
    "پمپ بتن", "گریدر", "بابکت", "بولدوزر", "جرثقیل", "غلطک", "فینیشر", "حفار",
]
TYPE_ICONS = {
    "کامیون": "🚚",
    "جرثقیل متحرک": "🏗️",
    "جرثقیل سقفی": "🏭",
    "لیفتراک": "📦",
    "لودر": "🪣",
    "تریلی": "🚛",
    "بیل مکانیکی": "⛏️",
    "بیل بکهو": "🛠️",
    "تانکر آبپاش": "💧",
    "تراکتور": "🚜",
    "تراک میکسر": "🌀",
    "پمپ بتن": "🧱",
    "گریدر": "🛣️",
    "بابکت": "🧰",
    "بولدوزر": "🚧",
    "جرثقیل": "🪝",
    "غلطک": "🛞",
    "فینیشر": "🛤️",
    "حفار": "🕳️",
}
DOCS = ["مجوز تردد", "بیمه‌نامه", "بیمه شخص ثالث", "بیمه مسئولیت مدنی", "گواهی معاینه فنی", "گواهی آزمون بار جرثقیل", "گواهی تعمیر و نگهداری", "گواهی‌نامه رانندگی", "گواهی آموزش", "گواهی سلامت شغلی", "مجوز اپراتوری"]
QUALS = ["گواهی‌نامه پایه مرتبط", "مجوز اپراتوری لیفتراک", "گواهی اپراتوری جرثقیل", "گواهی ریگر / علامت‌دهنده", "گواهی سلامت شغلی"]
CHECKLISTS = {
    "کامیون": ("بازرسی ایمنی کامیون", 0, ["ترمزها", "لاستیک‌ها", "فرمان", "چراغ‌ها و آینه‌ها", "بوق و کمربند ایمنی", "نشتی سیالات", "کپسول آتش‌نشانی و تجهیزات اضطراری"]),
    "جرثقیل متحرک": ("بازرسی ایمنی جرثقیل متحرک", 1, ["سیم‌بکسل‌ها و زنجیرها", "قلاب و ضامن ایمنی", "محدودکننده‌های حرکت", "ترمزها", "کنترل‌ها و توقف اضطراری", "نمایشگر ظرفیت بار", "گواهی آزمون بار"]),
    "جرثقیل سقفی": ("بازرسی ایمنی جرثقیل سقفی", 1, ["سیم‌بکسل و زنجیر", "قلاب و ضامن ایمنی", "کلیدهای حدی", "ترمز بالابر", "کنترل‌ها و توقف اضطراری", "نمایشگر ظرفیت بار"]),
    "لیفتراک": ("بازرسی ایمنی لیفتراک", 0, ["شاخک‌ها و دکل", "سامانه هیدرولیک", "لاستیک‌ها", "ترمزها و فرمان", "بوق و چراغ‌ها", "کمربند یا سامانه مهار", "نشتی و وضعیت باتری / سوخت"]),
}
CRITICAL = {"ترمزها", "ترمزها و فرمان", "کنترل‌ها و توقف اضطراری", "قلاب و ضامن ایمنی", "شاخک‌ها و دکل", "کمربند یا سامانه مهار"}


class Command(BaseCommand):
    help = "افزودن انواع و دسته‌های نمونه فارسی سامانه (قابل اجرا به دفعات)."

    @transaction.atomic
    def handle(self, *args, **options):
        from django.core.management import call_command
        for name in TYPES:
            EquipmentType.objects.update_or_create(name=name, defaults={"icon": TYPE_ICONS[name]})
        for name in DOCS:
            DocumentCategory.objects.get_or_create(name=name, defaults={"expires": True})
        QualificationType.objects.get_or_create(name=QUALS[0], defaults={"required_for_assignment": True})
        for name in QUALS[1:]: QualificationType.objects.get_or_create(name=name)
        call_command("setup_roles", verbosity=0)
        for type_name, (title, interval, descriptions) in CHECKLISTS.items():
            equipment_type = EquipmentType.objects.get(name=type_name)
            template, _ = ChecklistTemplate.objects.get_or_create(name=title, equipment_type=equipment_type, defaults={"interval_months": interval, "interval_days": 1 if type_name in ["کامیون", "لیفتراک"] else 0})
            if not template.items.exists():
                for order, description in enumerate(descriptions, 1):
                    ChecklistItem.objects.create(template=template, section="بازرسی عمومی", description=description, critical=description in CRITICAL, order=order)
        call_command("seed_safety_checklists", verbosity=0)
        self.stdout.write(self.style.SUCCESS("دسته‌های اولیه فارسی ثبت شدند."))
