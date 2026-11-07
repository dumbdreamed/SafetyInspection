from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.equipment_sheets import EQUIPMENT_SHEET_PROFILES
from core.demo_organization import seed_demo_organization
from core.models import (
    Area,
    Assignment,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Document,
    DocumentCategory,
    Equipment,
    EquipmentType,
    Finding,
    Inspection,
    InspectionResponse,
    MaintenanceRecord,
    Person,
    Qualification,
    QualificationType,
)


TYPE_DEMOS = {
    "کامیون": {"prefix": "TRK", "name": "کامیون آزمایشی", "capacity": "18.00", "unit": "تن", "power": "دیزل", "role": Assignment.Role.PRIMARY},
    "جرثقیل متحرک": {"prefix": "MCR", "name": "جرثقیل متحرک آزمایشی", "capacity": "25.00", "unit": "تن", "power": "دیزل", "role": Assignment.Role.OPERATOR},
    "جرثقیل سقفی": {"prefix": "OHC", "name": "جرثقیل سقفی آزمایشی", "capacity": "10.00", "unit": "تن", "power": "برق", "role": Assignment.Role.OPERATOR},
    "لیفتراک": {"prefix": "FLT", "name": "لیفتراک آزمایشی", "capacity": "2500.00", "unit": "کیلوگرم", "power": "برق", "role": Assignment.Role.OPERATOR},
    "لودر": {"prefix": "LDR", "name": "لودر آزمایشی", "capacity": "3.50", "unit": "متر مکعب", "power": "دیزل", "role": Assignment.Role.OPERATOR},
    "تریلی": {"prefix": "TRL", "name": "تریلی آزمایشی", "capacity": "32.00", "unit": "تن", "power": "بدون موتور", "role": Assignment.Role.PRIMARY},
}

CHECKLIST_DEMOS = {
    "کامیون": [
        ("ترمزها و فرمان", True), ("وضعیت لاستیک‌ها", False), ("چراغ‌ها و آینه‌ها", False),
        ("کمربند ایمنی و بوق", True), ("نشتی سیالات", False),
    ],
    "جرثقیل متحرک": [
        ("سیم‌بکسل و زنجیرها", True), ("قلاب و ضامن ایمنی", True), ("محدودکننده بار", True),
        ("ترمزها", True), ("توقف اضطراری", True),
    ],
    "جرثقیل سقفی": [
        ("سیم‌بکسل و زنجیر بالابر", True), ("قلاب و ضامن ایمنی", True), ("کلیدهای حدی", True),
        ("ترمز بالابر", True), ("توقف اضطراری", True),
    ],
    "لیفتراک": [
        ("شاخک‌ها و دکل", True), ("ترمز و فرمان", True), ("لاستیک‌ها", False),
        ("بوق و چراغ هشدار", False), ("کمربند یا مهار اپراتور", True),
    ],
    "لودر": [
        ("جام و اتصالات", True), ("سامانه هیدرولیک", True), ("ترمز و فرمان", True),
        ("لاستیک یا زنجیر", False), ("توقف اضطراری و هشدارها", True),
    ],
    "تریلی": [
        ("اتصال کشنده و قفل‌ها", True), ("سامانه ترمز", True), ("لاستیک‌ها", False),
        ("چراغ‌ها و بازتابنده‌ها", False), ("مهار بار و بدنه", True),
    ],
}

AREA_DEMOS = [
    ("ناحیه تولید — نمونه", "خط مونتاژ — نمونه"),
    ("ناحیه انبار — نمونه", "بارگیری — نمونه"),
    ("ناحیه تعمیرات — نمونه", "کارگاه مکانیک — نمونه"),
]

SUBTYPE_TYPES = {"کامیون", "بیل مکانیکی", "بیل بکهو", "تانکر آبپاش", "جرثقیل"}
DESERT_INSURANCE_TYPES = {"کامیون", "تراکتور", "تانکر آبپاش", "تراک میکسر", "پمپ بتن"}
TECHNICAL_INSPECTION_TYPES = {"کامیون", "تانکر آبپاش", "تراک میکسر", "پمپ بتن", "جرثقیل"}
CRANE_TYPES = {"جرثقیل", "جرثقیل متحرک", "جرثقیل سقفی"}
CERTIFICATE_TYPES = CRANE_TYPES | {"لیفتراک"}


def demo_pdf(label):
    """Return a small, valid PDF marked as synthetic test material."""
    text = f"DEMO SAMPLE ONLY - {label}".encode("ascii", "replace")
    stream = b"BT /F1 12 Tf 50 740 Td (" + text.replace(b"(", b"\\(").replace(b")", b"\\)") + b") Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    parts = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(sum(map(len, parts)))
        parts.append(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(map(len, parts))
    xref = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    parts.extend(xref)
    parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return b"".join(parts)


class Command(BaseCommand):
    help = "ساخت داده‌های کاملاً ساختگی برای نمایش محلی؛ هرگز روی داده‌های واقعی اجرا نکنید."

    def add_arguments(self, parser):
        parser.add_argument("--per-type", type=int, default=50, help="تعداد تجهیزات نمونه برای هر نوع فعال (پیش‌فرض: ۵۰).")

    @transaction.atomic
    def handle(self, *args, **options):
        per_type = options["per_type"]
        if per_type < 1 or per_type > 500:
            raise CommandError("تعداد نمونه برای هر نوع باید بین ۱ و ۵۰۰ باشد.")

        call_command("seed_reference_data", verbosity=0)
        User = get_user_model()
        actor = User.objects.filter(is_active=True, is_superuser=True).first() or User.objects.filter(is_active=True).first()
        if not actor:
            raise CommandError("ابتدا در محیط محلی یک کاربر مدیر بسازید.")

        today = timezone.localdate()
        types = list(EquipmentType.objects.filter(active=True).order_by("name"))
        if not types:
            raise CommandError("هیچ نوع تجهیز فعالی برای ساخت نمونه وجود ندارد.")

        base_qualification, _ = QualificationType.objects.get_or_create(
            name="گواهی‌نامه پایه مرتبط", defaults={"required_for_assignment": True}
        )
        insurance_category = DocumentCategory.objects.get(name="بیمه‌نامه")
        third_party_category = DocumentCategory.objects.get(name="بیمه شخص ثالث")
        liability_category = DocumentCategory.objects.get(name="بیمه مسئولیت مدنی")
        license_category = DocumentCategory.objects.get(name="گواهی‌نامه رانندگی")
        load_test_category = DocumentCategory.objects.get(name="گواهی آزمون بار جرثقیل")

        departments = []
        for area_name, department_name in AREA_DEMOS:
            area, _ = Area.objects.get_or_create(name=area_name)
            department, _ = Department.objects.get_or_create(name=department_name, area=area)
            departments.append((area, department))

        created = {"equipment": 0, "people": 0, "assignments": 0, "inspections": 0,
                   "findings": 0, "maintenance": 0, "documents": 0}

        for type_index, equipment_type in enumerate(types):
            sheet_fields = EQUIPMENT_SHEET_PROFILES.get(equipment_type.name, set())
            meta = TYPE_DEMOS.get(equipment_type.name, {
                "prefix": f"EQ{type_index + 1:02d}", "name": f"{equipment_type.name} آزمایشی",
                "capacity": "5.00", "unit": "واحد نمونه", "power": "نمونه", "role": Assignment.Role.OPERATOR,
            })
            prefix = meta["prefix"]
            template, _ = ChecklistTemplate.objects.get_or_create(
                name=f"چک‌لیست نمایشی {equipment_type.name}", equipment_type=equipment_type,
                defaults={"interval_months": 1, "active": True},
            )
            if not template.items.exists():
                descriptions = CHECKLIST_DEMOS.get(equipment_type.name, [
                    ("بازرسی عمومی", True), ("ترمز و توقف اضطراری", True), ("سامانه هشدار", False),
                    ("وضعیت سازه و اتصالات", True), ("نشتی یا آسیب ظاهری", False),
                ])
                ChecklistItem.objects.bulk_create([
                    ChecklistItem(template=template, section="بازرسی نمایشی", description=description,
                                  critical=critical, order=order)
                    for order, (description, critical) in enumerate(descriptions, 1)
                ])
            items = list(template.items.all())
            snapshot = [{"id": item.pk, "description": item.description, "critical": item.critical} for item in items]

            for number in range(1, per_type + 1):
                asset_code = f"DEMO-{prefix}-{number:03d}"
                area, department = departments[(number + type_index) % len(departments)]
                commissioned = date(today.year - (number % 18 + 1), (number % 12) + 1, 15)
                insurance_expiration_days = -30 if number % 17 == 0 else (14 if number % 13 == 0 else 365)
                initial_status = Equipment.Status.STOPPED if number % 29 == 0 else (
                    Equipment.Status.SERVICE if number % 11 == 0 else Equipment.Status.ACTIVE
                )
                equipment, equipment_created = Equipment.objects.get_or_create(
                    asset_code=asset_code,
                    defaults={
                        "name": f"{meta['name']} {number:03d}", "equipment_type": equipment_type,
                        "machine_subtype": f"{equipment_type.name} نمونه" if equipment_type.name in SUBTYPE_TYPES else "",
                        "manufacturer": "سازنده نمونه", "model_name": f"مدل DEMO-{prefix}",
                        "year": commissioned.year, "serial_number": f"DEMO-SN-{prefix}-{number:03d}",
                        "engine_number": f"DEMO-EN-{prefix}-{number:03d}",
                        "vin": f"DEMO-VIN-{prefix}-{number:03d}", "plate": f"DEMO-{prefix}-{number:03d}",
                        "owner": "کارخانه نمونه" if number % 3 else "پیمانکار نمونه",
                        "primary_contractor": "پیمانکار اصلی نمونه",
                        "subcontractor": "پیمانکار فرعی نمونه" if number % 2 else "",
                        "position": "سالن نمونه" if equipment_type.name == "جرثقیل سقفی" else "",
                        "area": area, "department": department, "rated_capacity": meta["capacity"],
                        "confirmed_capacity": meta["capacity"] if equipment_type.name == "لیفتراک" else None,
                        "large_hook_capacity": meta["capacity"] if equipment_type.name in CRANE_TYPES else None,
                        "small_hook_capacity": "5.00" if equipment_type.name in CRANE_TYPES else None,
                        "capacity_unit": meta["unit"], "power_type": meta["power"],
                        "status": initial_status, "commissioned_on": commissioned,
                        "entered_on": commissioned,
                        "third_party_insurance_expires_on": today + timedelta(days=insurance_expiration_days),
                        "liability_insurance_expires_on": today + timedelta(days=insurance_expiration_days + 120),
                        "desert_insurance_expires_on": today + timedelta(days=insurance_expiration_days) if equipment_type.name in DESERT_INSURANCE_TYPES else None,
                        "technical_inspection_expires_on": today + timedelta(days=insurance_expiration_days) if equipment_type.name in TECHNICAL_INSPECTION_TYPES else None,
                        "certificate_issued_on": today - timedelta(days=365) if equipment_type.name in CERTIFICATE_TYPES else None,
                        "certificate_expires_on": today + timedelta(days=365) if equipment_type.name in CERTIFICATE_TYPES else None,
                        "notes": "نمونه ساختگی برای آزمایش عملکرد سامانه؛ داده واقعی نیست.", "created_by": actor,
                    },
                )
                created["equipment"] += int(equipment_created)
                equipment.engine_number = f"DEMO-EN-{prefix}-{number:03d}" if "engine_number" in sheet_fields else ""
                equipment.serial_number = f"DEMO-SN-{prefix}-{number:03d}" if "serial_number" in sheet_fields else ""
                equipment.vin = f"DEMO-VIN-{prefix}-{number:03d}" if "vin" in sheet_fields else ""
                equipment.plate = f"DEMO-{prefix}-{number:03d}" if "plate" in sheet_fields else ""
                equipment.manufacturer = "سازنده نمونه" if "manufacturer" in sheet_fields else ""
                equipment.machine_subtype = f"{equipment_type.name} نمونه" if "machine_subtype" in sheet_fields else ""
                equipment.rated_capacity = meta["capacity"] if "rated_capacity" in sheet_fields else None
                equipment.capacity_unit = meta["unit"] if "capacity_unit" in sheet_fields else ""
                equipment.primary_contractor = "پیمانکار اصلی نمونه"
                equipment.subcontractor = "پیمانکار فرعی نمونه" if number % 2 else ""
                equipment.entered_on = commissioned
                equipment.position = "سالن نمونه" if "position" in sheet_fields else ""
                equipment.confirmed_capacity = meta["capacity"] if "confirmed_capacity" in sheet_fields else None
                equipment.large_hook_capacity = meta["capacity"] if "large_hook_capacity" in sheet_fields else None
                equipment.small_hook_capacity = "5.00" if "small_hook_capacity" in sheet_fields else None
                equipment.third_party_insurance_expires_on = today + timedelta(days=insurance_expiration_days) if "third_party_insurance_expires_on" in sheet_fields else None
                equipment.liability_insurance_expires_on = today + timedelta(days=insurance_expiration_days + 120) if "liability_insurance_expires_on" in sheet_fields else None
                equipment.desert_insurance_expires_on = today + timedelta(days=insurance_expiration_days) if "desert_insurance_expires_on" in sheet_fields else None
                equipment.technical_inspection_expires_on = today + timedelta(days=insurance_expiration_days) if "technical_inspection_expires_on" in sheet_fields else None
                equipment.certificate_issued_on = today - timedelta(days=365) if "certificate_issued_on" in sheet_fields else None
                equipment.certificate_expires_on = today + timedelta(days=365) if "certificate_expires_on" in sheet_fields else None
                equipment.save(update_fields=[
                    "engine_number", "serial_number", "vin", "plate", "manufacturer", "machine_subtype", "rated_capacity", "capacity_unit",
                    "primary_contractor", "subcontractor", "entered_on", "position",
                    "confirmed_capacity", "large_hook_capacity", "small_hook_capacity", "third_party_insurance_expires_on",
                    "liability_insurance_expires_on", "desert_insurance_expires_on", "technical_inspection_expires_on",
                    "certificate_issued_on", "certificate_expires_on", "updated_at",
                ])

                person_code = f"DEMO-OP-{prefix}-{number:03d}"
                person, person_created = Person.objects.get_or_create(
                    employee_code=person_code,
                    defaults={
                        "full_name": f"اپراتور آزمایشی {prefix} {number:03d}",
                        "employer": "پیمانکار نمونه", "department": department,
                        "active": number % 37 != 0,
                        "notes": "هویت کاملاً ساختگی؛ فقط برای آزمایش سامانه.",
                    },
                )
                created["people"] += int(person_created)

                qualification, qualification_created = Qualification.objects.get_or_create(
                    person=person, qualification_type=base_qualification,
                    certificate_number=f"DEMO-CERT-{prefix}-{number:03d}",
                    defaults={
                        "issuer": "مرجع آزمایشی", "issued_on": today - timedelta(days=365),
                        "expires_on": today + timedelta(days=365 + number % 180), "verified": True,
                        "notes": "گواهی ساختگی برای تست تخصیص اپراتور.",
                    },
                )

                # Keep some assets intentionally unassigned to exercise filters and status handling.
                if equipment.status == Equipment.Status.ACTIVE and person.active and number % 10 != 4:
                    _, assignment_created = Assignment.objects.get_or_create(
                        person=person, equipment=equipment, starts_on=today - timedelta(days=30),
                        defaults={"role": meta["role"], "notes": "تخصیص آزمایشی DEMO"},
                    )
                    created["assignments"] += int(assignment_created)

                inspection_case = number % 5
                if inspection_case == 0:
                    status, outcome, due_days = Inspection.Status.SCHEDULED, "", -3
                elif inspection_case == 1:
                    status, outcome, due_days = Inspection.Status.SCHEDULED, "", 4
                elif inspection_case == 2:
                    status, outcome, due_days = Inspection.Status.PROGRESS, "", 0
                elif inspection_case == 3:
                    status = Inspection.Status.COMPLETED
                    outcome = Inspection.Outcome.CONDITIONAL if number % 10 == 3 else Inspection.Outcome.PASS
                    due_days = -20
                else:
                    status, outcome, due_days = Inspection.Status.COMPLETED, Inspection.Outcome.FAIL, -45

                inspection_note = f"DEMO:{asset_code}: inspection scenario"
                inspection = Inspection.objects.filter(equipment=equipment, notes=inspection_note).first()
                inspection_created = inspection is None
                if inspection_created:
                    completed_at = timezone.now() - timedelta(days=20 if inspection_case == 3 else 45) if status == Inspection.Status.COMPLETED else None
                    inspection = Inspection.objects.create(
                        equipment=equipment, template=template, inspector=actor,
                        due_date=today + timedelta(days=due_days), status=status, outcome=outcome,
                        meter_value=1000 + number * 125, notes=inspection_note,
                        completed_at=completed_at, template_snapshot=snapshot,
                    )
                    created["inspections"] += 1
                    if status == Inspection.Status.COMPLETED:
                        critical_failure = inspection_case == 4 and number % 10 == 4
                        failing_item = None
                        if outcome in {Inspection.Outcome.FAIL, Inspection.Outcome.CONDITIONAL}:
                            if critical_failure:
                                failing_item = next((item for item in items if item.critical), items[0])
                            else:
                                failing_item = next((item for item in items if not item.critical), items[0])
                        InspectionResponse.objects.bulk_create([
                            InspectionResponse(
                                inspection=inspection, item=item, item_text=item.description, critical=item.critical,
                                result=(InspectionResponse.Result.FAIL if item == failing_item else InspectionResponse.Result.PASS),
                                comment=("نمونه ساختگی: نیاز به پیگیری" if item == failing_item else "نمونه ساختگی: مورد تأیید"),
                                measurement="مقدار نمایشی",
                            ) for item in items
                        ])
                        if failing_item:
                            severity = Finding.Severity.CRITICAL if critical_failure and failing_item.critical else (
                                Finding.Severity.LOW if outcome == Inspection.Outcome.CONDITIONAL else Finding.Severity.HIGH
                            )
                            finding_note = f"نقص آزمایشی DEMO: {failing_item.description}"
                            finding, finding_created = Finding.objects.get_or_create(
                                equipment=equipment, description=finding_note,
                                defaults={
                                    "inspection": inspection, "severity": severity,
                                    "blocks_operation": severity == Finding.Severity.CRITICAL,
                                    "assigned_person": person, "assigned_to": person.full_name[:120], "due_date": today + timedelta(days=7),
                                    "status": Finding.Status.OPEN,
                                },
                            )
                            created["findings"] += int(finding_created)
                            if finding.severity == Finding.Severity.CRITICAL and equipment.status != Equipment.Status.STOPPED:
                                equipment.status = Equipment.Status.STOPPED
                                equipment.save(update_fields=["status", "updated_at"])

                # Add a few unrelated open actions so the findings screens show varied records.
                if number % 17 == 0:
                    finding_note = f"نقص نمایشی DEMO: بازبینی عمومی {asset_code}"
                    _, finding_created = Finding.objects.get_or_create(
                        equipment=equipment, description=finding_note,
                        defaults={
                            "severity": Finding.Severity.MEDIUM, "blocks_operation": False,
                            "assigned_person": person, "assigned_to": person.full_name[:120], "due_date": today - timedelta(days=2 if number % 34 == 0 else -8),
                            "status": Finding.Status.PROGRESS if number % 34 == 0 else Finding.Status.OPEN,
                        },
                    )
                    created["findings"] += int(finding_created)

                # Seed one synthetic valid-PDF document for the asset and one for its operator.
                expiration_days = insurance_expiration_days
                created["documents"] += self.ensure_document(
                    title=f"بیمه‌نامه آزمایشی {asset_code}", category=insurance_category,
                    owner_field="equipment", owner=equipment, code=f"{asset_code}-INS",
                    expires_on=today + timedelta(days=expiration_days), uploaded_by=actor,
                    verification=Document.Verification.PENDING if number % 11 == 0 else Document.Verification.VERIFIED,
                )
                created["documents"] += self.ensure_document(
                    title=f"بیمه شخص ثالث آزمایشی {asset_code}", category=third_party_category,
                    owner_field="equipment", owner=equipment, code=f"{asset_code}-TPL",
                    expires_on=today + timedelta(days=expiration_days), uploaded_by=actor,
                    verification=Document.Verification.VERIFIED,
                )
                created["documents"] += self.ensure_document(
                    title=f"بیمه مسئولیت مدنی آزمایشی {asset_code}", category=liability_category,
                    owner_field="equipment", owner=equipment, code=f"{asset_code}-LIAB",
                    expires_on=today + timedelta(days=expiration_days + 120), uploaded_by=actor,
                    verification=Document.Verification.VERIFIED,
                )
                created["documents"] += self.ensure_document(
                    title=f"گواهی‌نامه رانندگی آزمایشی {person_code}", category=license_category,
                    owner_field="person", owner=person, code=f"{person_code}-LIC",
                    expires_on=today + timedelta(days=expiration_days), uploaded_by=actor,
                    verification=Document.Verification.VERIFIED,
                )
                if equipment_type.name in {"جرثقیل متحرک", "جرثقیل سقفی"}:
                    created["documents"] += self.ensure_document(
                        title=f"گواهی آزمون بار آزمایشی {asset_code}", category=load_test_category,
                        owner_field="equipment", owner=equipment, code=f"{asset_code}-LOAD",
                        expires_on=today + timedelta(days=180), uploaded_by=actor,
                        verification=Document.Verification.VERIFIED,
                    )

                if number % 3 == 0:
                    maintenance_note = f"سابقه آزمایشی DEMO برای {asset_code}"
                    maintenance, maintenance_created = MaintenanceRecord.objects.get_or_create(
                        equipment=equipment, date=today - timedelta(days=30 + number), kind="سرویس دوره‌ای نمونه",
                        description=maintenance_note,
                        defaults={
                            "provider": "کارگاه نمونه", "meter_value": 900 + number * 100,
                            "cost": "1250000.00", "currency": "IRR",
                            "finding": Finding.objects.filter(equipment=equipment, description__startswith="نقص آزمایشی DEMO").first(),
                            "next_service": today + timedelta(days=30 if number % 2 else -4),
                            "created_by": actor,
                        },
                    )
                    created["maintenance"] += int(maintenance_created)

            self.stdout.write(f"{equipment_type.name}: {per_type} رکورد هدف")

        organization = seed_demo_organization()
        totals = {
            "equipment": Equipment.objects.filter(asset_code__startswith="DEMO-").count(),
            "people": Person.objects.filter(employee_code__startswith="DEMO-").count(),
        }
        self.stdout.write(self.style.SUCCESS(
            "نمونه‌های ساختگی آماده‌اند؛ هیچ داده واقعی وارد نشد. "
            f"تجهیزات DEMO: {totals['equipment']}، افراد DEMO: {totals['people']}؛ "
            + "، ".join(f"{name} ایجادشده: {count}" for name, count in created.items())
        ))
        self.stdout.write(
            f"DEMO organization chart prepared: {organization['people']} staff, "
            f"{organization['clusters']} new department groups."
        )

    @staticmethod
    def ensure_document(*, title, category, owner_field, owner, code, expires_on, uploaded_by, verification):
        filters = {"title": title, owner_field: owner}
        if Document.objects.filter(**filters).exists():
            return 0
        document = Document(
            title=title, category=category, **{owner_field: owner},
            reference_number=f"DEMO-{code}", issuer="مرجع آزمایشی",
            issued_on=expires_on - timedelta(days=365), expires_on=expires_on,
            verification=verification, uploaded_by=uploaded_by,
            notes="PDF ساختگی با برچسب DEMO؛ مدرک رسمی نیست.",
        )
        document.file.save(f"{code}.pdf", ContentFile(demo_pdf(code)), save=False)
        document.save()
        return 1
