from django.core.management.base import BaseCommand
from django.db import transaction

from core.inspection_catalog import SPECIFIC, checklist_for
from core.models import ChecklistItem, ChecklistTemplate, EquipmentType


class Command(BaseCommand):
    help = "Add the researched starter checklist for each equipment type."

    @transaction.atomic
    def handle(self, *args, **options):
        for name in SPECIFIC:
            equipment_type = EquipmentType.objects.filter(name=name).first()
            if not equipment_type:
                continue
            template, created = ChecklistTemplate.objects.get_or_create(
                equipment_type=equipment_type, name=f"چک‌لیست ایمنی پیشنهادی {name}",
                defaults={"rejection_threshold": 20, "active": True},
            )
            if created:
                ChecklistItem.objects.bulk_create([
                    ChecklistItem(template=template, section="بازرسی ایمنی", description=description,
                                  weight=weight, critical=critical, order=index)
                    for index, (description, weight, critical) in enumerate(checklist_for(name), 1)
                ])
        self.stdout.write(self.style.SUCCESS("چک‌لیست‌های پیشنهادی آماده‌اند."))
