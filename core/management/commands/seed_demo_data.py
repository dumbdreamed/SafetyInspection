from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.models import (Assignment, ChecklistTemplate, Equipment, EquipmentType,
                         Inspection, Person)


class Command(BaseCommand):
    help = "داده‌های کاملاً ساختگی را برای نمایشی محلی می‌سازد. هرگز برای داده زنده اجرا نکنید."

    def handle(self, *args, **options):
        User = get_user_model()
        inspector = User.objects.filter(is_active=True).first()
        if not inspector: raise CommandError("ابتدا یک کاربر مدیریتی بسازید.")
        truck_type = EquipmentType.objects.filter(name="کامیون").first()
        template = ChecklistTemplate.objects.filter(equipment_type=truck_type).first() if truck_type else None
        if not truck_type or not template: raise CommandError("ابتدا seed_reference_data را اجرا کنید.")
        person, _ = Person.objects.get_or_create(employee_code="DEMO-OP-01", defaults={"full_name": "نمونه — داده آزمایشی", "employer": "پیمانکار نمونه"})
        equipment, _ = Equipment.objects.get_or_create(asset_code="DEMO-TR-001", defaults={"name": "کامیون نمونه نمایشی", "equipment_type": truck_type, "manufacturer": "ساخت نمونه", "status": Equipment.Status.ACTIVE})
        Assignment.objects.get_or_create(person=person, equipment=equipment, starts_on=timezone.localdate(), defaults={"role": Assignment.Role.PRIMARY})
        Inspection.objects.get_or_create(equipment=equipment, template=template, due_date=timezone.localdate() + timedelta(days=2), status=Inspection.Status.SCHEDULED, defaults={"inspector": inspector, "notes": "داده آزمایشی ساختگی"})
        self.stdout.write(self.style.SUCCESS("داده‌های نمایشی ساختگی ثبت شدند (کدهای DEMO)."))
