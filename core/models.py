import calendar
import uuid
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class EquipmentType(models.Model):
    name = models.CharField("نام نوع", max_length=100, unique=True)
    icon = models.CharField("نماد", max_length=8, default="▣")
    active = models.BooleanField("فعال", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "نوع تجهیز"
        verbose_name_plural = "انواع تجهیزات"

    def __str__(self):
        return self.name


class Area(models.Model):
    name = models.CharField("نام ناحیه", max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "ناحیه کارخانه"
        verbose_name_plural = "ناحیه‌های کارخانه"

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField("نام واحد", max_length=100)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, verbose_name="ناحیه", related_name="departments")

    class Meta:
        ordering = ["area__name", "name"]
        constraints = [models.UniqueConstraint(fields=["area", "name"], name="unique_department_per_area")]
        verbose_name = "واحد"
        verbose_name_plural = "واحدها"

    def __str__(self):
        return f"{self.area} / {self.name}"


class Equipment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "در حال بهره‌برداری"
        SERVICE = "service", "در حال تعمیر"
        STOPPED = "stopped", "خارج از سرویس"

    asset_code = models.CharField("کد اموال", max_length=40, unique=True)
    name = models.CharField("نام تجهیز", max_length=120)
    equipment_type = models.ForeignKey(EquipmentType, on_delete=models.PROTECT, verbose_name="نوع تجهیز", related_name="equipment")
    machine_subtype = models.CharField("نوع / مدل ماشین", max_length=120, blank=True)
    manufacturer = models.CharField("سازنده", max_length=100, blank=True)
    model_name = models.CharField("مدل", max_length=100, blank=True)
    year = models.PositiveSmallIntegerField("سال ساخت میلادی", null=True, blank=True)
    serial_number = models.CharField("شماره سریال", max_length=100, blank=True, db_index=True)
    engine_number = models.CharField("شماره موتور", max_length=100, blank=True, db_index=True)
    vin = models.CharField("شماره شاسی / VIN", max_length=100, blank=True)
    plate = models.CharField("شماره پلاک", max_length=30, blank=True)
    owner = models.CharField("مالک / پیمانکار", max_length=120, blank=True)
    primary_contractor = models.CharField("پیمانکار اصلی", max_length=120, blank=True)
    subcontractor = models.CharField("پیمانکار فرعی", max_length=120, blank=True)
    position = models.CharField("موقعیت تجهیز", max_length=120, blank=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, null=True, blank=True, verbose_name="ناحیه", related_name="equipment")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True, verbose_name="واحد", related_name="equipment")
    rated_capacity = models.DecimalField("ظرفیت نامی", max_digits=12, decimal_places=2, null=True, blank=True)
    capacity_unit = models.CharField("واحد ظرفیت", max_length=20, blank=True, help_text="مثلاً تن یا کیلوگرم")
    power_type = models.CharField("نوع سوخت / نیرو", max_length=50, blank=True)
    status = models.CharField("وضعیت بهره‌برداری", max_length=12, choices=Status.choices, default=Status.ACTIVE)
    commissioned_on = models.DateField("تاریخ راه‌اندازی", null=True, blank=True)
    entered_on = models.DateField("تاریخ ورود", null=True, blank=True)
    exited_on = models.DateField("تاریخ خروج", null=True, blank=True)
    third_party_insurance_expires_on = models.DateField("تاریخ انقضای بیمه شخص ثالث", null=True, blank=True)
    liability_insurance_expires_on = models.DateField("تاریخ انقضای بیمه مسئولیت مدنی", null=True, blank=True)
    desert_insurance_expires_on = models.DateField("تاریخ انقضای بیمه بیابانی", null=True, blank=True)
    technical_inspection_expires_on = models.DateField("تاریخ انقضای معاینه فنی", null=True, blank=True)
    confirmed_capacity = models.DecimalField("ظرفیت تأییدشده", max_digits=12, decimal_places=2, null=True, blank=True)
    large_hook_capacity = models.DecimalField("ظرفیت قلاب بزرگ (تن)", max_digits=12, decimal_places=2, null=True, blank=True)
    small_hook_capacity = models.DecimalField("ظرفیت قلاب کوچک (تن)", max_digits=12, decimal_places=2, null=True, blank=True)
    certificate_issued_on = models.DateField("تاریخ اخذ گواهی بازرسی", null=True, blank=True)
    certificate_expires_on = models.DateField("تاریخ انقضای گواهی بازرسی", null=True, blank=True)
    notes = models.TextField("یادداشت", blank=True)
    archived = models.BooleanField("بایگانی‌شده", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_equipment")
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        ordering = ["asset_code"]
        indexes = [models.Index(fields=["status", "archived"]), models.Index(fields=["equipment_type", "area"])]
        verbose_name = "تجهیز"
        verbose_name_plural = "تجهیزات"

    def clean(self):
        if self.department_id and self.area_id and self.department.area_id != self.area_id:
            raise ValidationError({"department": "واحد انتخاب‌شده متعلق به ناحیه انتخاب‌شده نیست."})
        if self.rated_capacity is not None and self.rated_capacity < 0:
            raise ValidationError({"rated_capacity": "ظرفیت نمی‌تواند منفی باشد."})

    def __str__(self):
        return f"{self.asset_code} — {self.name}"

    @property
    def open_findings(self):
        return self.findings.exclude(status=Finding.Status.CLOSED)

    @property
    def condition(self):
        if self.status == self.Status.STOPPED or self.open_findings.filter(blocks_operation=True).exists():
            return "خارج از سرویس", "danger"
        latest = self.inspections.filter(
            status=Inspection.Status.COMPLETED,
            review_state=Inspection.ReviewState.APPROVED,
        ).order_by("-completed_at", "-pk").first()
        if latest and latest.outcome == Inspection.Outcome.FAIL:
            return "بازرسی مردود", "danger"
        if self.status == self.Status.SERVICE:
            return "در حال تعمیر", "warning"
        if self.open_findings.exists():
            return "دارای اقدام باز", "warning"
        today = timezone.localdate()
        if self.inspections.filter(status__in=[Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS], due_date__lt=today).exists():
            return "بازرسی معوق", "warning"
        required_categories = DocumentCategory.objects.filter(required_for_equipment_types=self.equipment_type)
        valid_categories = self.documents.filter(superseded_by__isnull=True, verification=Document.Verification.VERIFIED).filter(
            Q(expires_on__isnull=True) | Q(expires_on__gte=today)
        ).values("category_id")
        if required_categories.exclude(id__in=valid_categories).exists():
            return "مدرک الزامی ناقص", "warning"
        if not self.inspections.filter(
            status=Inspection.Status.COMPLETED,
            review_state=Inspection.ReviewState.APPROVED,
            outcome__in=[Inspection.Outcome.PASS, Inspection.Outcome.CONDITIONAL],
        ).exists():
            return "بازرسی‌نشده", "muted"
        return "فعال", "success"


class Person(models.Model):
    employee_code = models.CharField("کد پرسنلی / پیمانکاری", max_length=40, unique=True)
    full_name = models.CharField("نام و نام خانوادگی", max_length=160)
    email = models.EmailField("رایانامه", blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="person_profile", verbose_name="حساب کاربری چک‌لیست")
    photo = models.ImageField("عکس پروفایل", upload_to="person-photos/", blank=True)
    employer = models.CharField("شرکت / پیمانکار", max_length=120, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="واحد")
    phone = models.CharField("شماره تماس", max_length=40, blank=True)
    emergency_contact = models.CharField("تماس اضطراری", max_length=120, blank=True)
    active = models.BooleanField("فعال", default=True)
    notes = models.TextField("یادداشت", blank=True)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "راننده / اپراتور"
        verbose_name_plural = "رانندگان و اپراتورها"

    def __str__(self):
        return f"{self.full_name} ({self.employee_code})"


class OrganizationPosition(models.Model):
    class Level(models.TextChoices):
        TOP = "top", "مدیریت ارشد"
        MIDDLE = "middle", "مدیریت میانی"
        SUPERVISOR = "supervisor", "سرپرست"
        EMPLOYEE = "employee", "کارمند"
        OTHER = "other", "سایر"

    person = models.OneToOneField(Person, on_delete=models.CASCADE, related_name="organization_position", verbose_name="شخص")
    title = models.CharField("عنوان شغلی", max_length=120)
    level = models.CharField("سطح سازمانی", max_length=20, choices=Level.choices, default=Level.EMPLOYEE)
    manager = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reports", verbose_name="مدیر مستقیم")
    order = models.PositiveSmallIntegerField("ترتیب نمایش", default=0)
    chart_visible = models.BooleanField("نمایش در نمودار", default=True)

    class Meta:
        ordering = ["order", "person__full_name", "pk"]
        verbose_name = "جایگاه سازمانی"
        verbose_name_plural = "جایگاه‌های سازمانی"

    def clean(self):
        super().clean()
        managerial_levels = {self.Level.TOP, self.Level.MIDDLE, self.Level.SUPERVISOR}
        if self.manager and self.manager.level not in managerial_levels:
            raise ValidationError({"manager": "مدیر مستقیم باید سطح مدیریتی یا سرپرستی داشته باشد."})
        if self.pk and self.level not in managerial_levels and self.reports.exists():
            raise ValidationError({"level": "پیش از تغییر سطح این مدیر، مدیر مستقیم افراد زیرمجموعه را تغییر دهید."})
        current = self.manager
        seen = set()
        while current:
            if current.pk == self.pk and self.pk is not None:
                raise ValidationError({"manager": "مدیر مستقیم نمی‌تواند خود فرد یا یکی از زیرمجموعه‌های او باشد."})
            if current.pk in seen:
                raise ValidationError({"manager": "چرخه در ساختار مدیران مجاز نیست."})
            seen.add(current.pk)
            current = current.manager

    def __str__(self):
        return f"{self.person.full_name} — {self.title}"


def show_organization_chain(position):
    """Make a reporting line visible without changing its roles or managers."""
    ids, seen = [], set()
    while position and position.pk not in seen:
        seen.add(position.pk)
        ids.append(position.pk)
        position = position.manager
    OrganizationPosition.objects.filter(pk__in=ids).update(chart_visible=True)


class OrganizationCluster(models.Model):
    name = models.CharField("نام گروه", max_length=100, unique=True)
    members = models.ManyToManyField(OrganizationPosition, blank=True, related_name="clusters", verbose_name="اعضای گروه")
    role_labels = models.JSONField("برچسب نقش‌ها", default=dict, blank=True)
    chart_structure = models.JSONField("ساختار چارت", default=list, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "گروه چارت سازمانی"
        verbose_name_plural = "گروه‌های چارت سازمانی"

    def __str__(self):
        return self.name


class QualificationType(models.Model):
    name = models.CharField("عنوان گواهی / صلاحیت", max_length=120, unique=True)
    required_for_assignment = models.BooleanField("الزامی برای تخصیص", default=False)
    equipment_types = models.ManyToManyField(EquipmentType, blank=True, verbose_name="انواع تجهیزات مجاز")

    class Meta:
        ordering = ["name"]
        verbose_name = "نوع صلاحیت"
        verbose_name_plural = "انواع صلاحیت"

    def __str__(self):
        return self.name


class Qualification(models.Model):
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="qualifications", verbose_name="شخص")
    qualification_type = models.ForeignKey(QualificationType, on_delete=models.PROTECT, verbose_name="نوع صلاحیت")
    certificate_number = models.CharField("شماره گواهی", max_length=100, blank=True)
    issuer = models.CharField("مرجع صادرکننده", max_length=120, blank=True)
    issued_on = models.DateField("تاریخ صدور", null=True, blank=True)
    expires_on = models.DateField("تاریخ انقضا", null=True, blank=True)
    verified = models.BooleanField("بررسی‌شده", default=False)
    notes = models.TextField("یادداشت", blank=True)

    class Meta:
        ordering = ["expires_on", "qualification_type__name"]
        verbose_name = "صلاحیت / گواهی"
        verbose_name_plural = "صلاحیت‌ها و گواهی‌ها"
        constraints = [models.UniqueConstraint(fields=["person", "qualification_type", "certificate_number"], name="uq_person_qual_cert")]

    def clean(self):
        if self.issued_on and self.expires_on and self.expires_on < self.issued_on:
            raise ValidationError({"expires_on": "تاریخ انقضا نمی‌تواند پیش از تاریخ صدور باشد."})

    @property
    def is_current(self):
        return not self.expires_on or self.expires_on >= timezone.localdate()

    def __str__(self):
        return f"{self.person} — {self.qualification_type}"


class Assignment(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "primary", "راننده اصلی"
        RELIEF = "relief", "راننده جایگزین"
        OPERATOR = "operator", "اپراتور"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="assignments", verbose_name="راننده / اپراتور")
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="assignments", verbose_name="تجهیز")
    role = models.CharField("نقش", max_length=12, choices=Role.choices, default=Role.OPERATOR)
    starts_on = models.DateField("شروع تخصیص")
    ends_on = models.DateField("پایان تخصیص", null=True, blank=True)
    notes = models.CharField("یادداشت", max_length=240, blank=True)

    class Meta:
        ordering = ["-starts_on"]
        verbose_name = "تخصیص اپراتور"
        verbose_name_plural = "تخصیص اپراتورها"

    def clean(self):
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": "پایان تخصیص نمی‌تواند پیش از شروع آن باشد."})
        if self.person_id and self.equipment_id and (not self.ends_on or self.ends_on >= timezone.localdate()):
            if self.equipment.status != Equipment.Status.ACTIVE:
                raise ValidationError({"equipment": "تخصیص جدید به تجهیز غیرفعال مجاز نیست."})
            if self.equipment.findings.filter(blocks_operation=True).exclude(status=Finding.Status.CLOSED).exists():
                raise ValidationError({"equipment": "تا رفع نقص بحرانی، تخصیص این تجهیز امکان‌پذیر نیست."})
            required = QualificationType.objects.filter(required_for_assignment=True).filter(
                Q(equipment_types__isnull=True) | Q(equipment_types=self.equipment.equipment_type)
            ).distinct()
            current = self.person.qualifications.filter(qualification_type__in=required, verified=True).filter(
                Q(expires_on__isnull=True) | Q(expires_on__gte=timezone.localdate())
            ).values_list("qualification_type_id", flat=True)
            missing = required.exclude(id__in=current)
            if missing.exists():
                raise ValidationError({"person": "صلاحیت معتبر و تأییدشده لازم است: " + "، ".join(missing.values_list("name", flat=True))})


def private_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    owner = instance.equipment_id or instance.person_id or instance.qualification_id or instance.inspection_id or instance.finding_id or "pending"
    return f"documents/{owner}/{uuid.uuid4().hex}{suffix}"


class DocumentCategory(models.Model):
    name = models.CharField("دسته مدرک", max_length=100, unique=True)
    expires = models.BooleanField("دارای تاریخ انقضا", default=False)
    required_for_equipment_types = models.ManyToManyField(EquipmentType, blank=True, verbose_name="الزامی برای انواع تجهیزات")

    class Meta:
        ordering = ["name"]
        verbose_name = "دسته مدرک"
        verbose_name_plural = "دسته‌های مدارک"

    def __str__(self):
        return self.name


class Document(models.Model):
    class Verification(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        VERIFIED = "verified", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    title = models.CharField("عنوان مدرک", max_length=160)
    category = models.ForeignKey(DocumentCategory, on_delete=models.PROTECT, verbose_name="دسته")
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, null=True, blank=True, related_name="documents", verbose_name="تجهیز")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, null=True, blank=True, related_name="documents", verbose_name="شخص")
    qualification = models.ForeignKey(Qualification, on_delete=models.PROTECT, null=True, blank=True, related_name="documents", verbose_name="صلاحیت")
    inspection = models.ForeignKey("Inspection", on_delete=models.PROTECT, null=True, blank=True, related_name="documents", verbose_name="بازرسی")
    finding = models.ForeignKey("Finding", on_delete=models.PROTECT, null=True, blank=True, related_name="documents", verbose_name="اقدام اصلاحی")
    reference_number = models.CharField("شماره مدرک", max_length=100, blank=True)
    issuer = models.CharField("مرجع صادرکننده", max_length=120, blank=True)
    issued_on = models.DateField("تاریخ صدور", null=True, blank=True)
    expires_on = models.DateField("تاریخ انقضا", null=True, blank=True)
    verification = models.CharField("وضعیت بررسی", max_length=12, choices=Verification.choices, default=Verification.PENDING)
    file = models.FileField("فایل", upload_to=private_upload_path)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="بارگذار")
    uploaded_at = models.DateTimeField("زمان بارگذاری", auto_now_add=True)
    notes = models.TextField("یادداشت", blank=True)
    superseded_by = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="supersedes", verbose_name="نسخه جایگزین")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "مدرک"
        verbose_name_plural = "مدارک"

    def clean(self):
        owners = [self.equipment_id, self.person_id, self.qualification_id, self.inspection_id, self.finding_id]
        if sum(owner is not None for owner in owners) != 1:
            raise ValidationError("هر فایل باید دقیقاً به یک تجهیز، شخص، صلاحیت، بازرسی یا اقدام اصلاحی متصل باشد.")
        if self.qualification_id and self.person_id and self.qualification.person_id != self.person_id:
            raise ValidationError("صلاحیت انتخاب‌شده به این شخص تعلق ندارد.")
        if self.issued_on and self.expires_on and self.expires_on < self.issued_on:
            raise ValidationError({"expires_on": "تاریخ انقضا نمی‌تواند پیش از تاریخ صدور باشد."})

    @property
    def validity(self):
        if self.superseded_by_id:
            return "جایگزین‌شده"
        if self.expires_on and self.expires_on < timezone.localdate():
            return "منقضی‌شده"
        if self.expires_on and (self.expires_on - timezone.localdate()).days <= 30:
            return "در آستانه انقضا"
        return "معتبر"


class ChecklistTemplate(models.Model):
    name = models.CharField("عنوان الگوی بازرسی", max_length=140)
    equipment_type = models.ForeignKey(EquipmentType, on_delete=models.CASCADE, null=True, blank=True, verbose_name="نوع تجهیز")
    interval_months = models.PositiveSmallIntegerField("تکرار به ماه", default=0, help_text="صفر: بدون تکرار")
    interval_days = models.PositiveSmallIntegerField("تکرار به روز", default=0, help_text="برای تناوب روزانه یا هفتگی")
    active = models.BooleanField("فعال", default=True)
    rejection_threshold = models.PositiveSmallIntegerField("آستانه رد (درصد وزن مردود)", default=20, validators=[MinValueValidator(1), MaxValueValidator(100)])

    class Meta:
        ordering = ["name"]
        verbose_name = "الگوی بازرسی"
        verbose_name_plural = "الگوهای بازرسی"

    def clean(self):
        if self.interval_days and self.interval_months:
            raise ValidationError("تناوب را فقط بر اساس روز یا ماه تعیین کنید.")

    def __str__(self):
        return self.name


class ChecklistItem(models.Model):
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.CASCADE, related_name="items", verbose_name="الگو")
    section = models.CharField("بخش", max_length=100, blank=True)
    description = models.CharField("مورد بازرسی", max_length=240)
    critical = models.BooleanField("مورد بحرانی", default=False)
    weight = models.PositiveSmallIntegerField("وزن", default=1, validators=[MinValueValidator(1), MaxValueValidator(10)])
    order = models.PositiveSmallIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "مورد چک‌لیست"
        verbose_name_plural = "موارد چک‌لیست"

    def __str__(self):
        return self.description


def add_months(day, months):
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class Inspection(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "برنامه‌ریزی‌شده"
        PROGRESS = "progress", "در حال انجام"
        COMPLETED = "completed", "تکمیل‌شده"
        CANCELLED = "cancelled", "لغوشده"
    class Outcome(models.TextChoices):
        PASS = "pass", "قبول"
        CONDITIONAL = "conditional", "قبول مشروط"
        FAIL = "fail", "مردود"
    class ReviewState(models.TextChoices):
        ASSIGNED = "assigned", "تخصیص‌یافته"
        DRAFT = "draft", "پیش‌نویس"
        SUBMITTED = "submitted", "در انتظار بررسی مدیر"
        APPROVED = "approved", "تأییدشده"
        RETURNED = "returned", "نیازمند اصلاح"
        CANCELLED = "cancelled", "لغوشده"

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="inspections", verbose_name="تجهیز")
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.PROTECT, related_name="inspections", verbose_name="الگو")
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inspections", verbose_name="بازرس")
    due_date = models.DateField("تاریخ برنامه‌ریزی‌شده")
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    review_state = models.CharField("وضعیت بررسی مدیر", max_length=12, choices=ReviewState.choices, default=ReviewState.ASSIGNED)
    outcome = models.CharField("نتیجه", max_length=12, choices=Outcome.choices, blank=True)
    meter_value = models.PositiveIntegerField("کارکرد هنگام بازرسی", null=True, blank=True)
    notes = models.TextField("یادداشت", blank=True)
    instructions = models.TextField("دستورالعمل انجام بازرسی", blank=True)
    completed_at = models.DateTimeField("زمان تکمیل", null=True, blank=True)
    submitted_at = models.DateTimeField("زمان ارسال برای بررسی", null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_inspections", verbose_name="بررسی‌کننده")
    reviewed_at = models.DateTimeField("زمان بررسی مدیر", null=True, blank=True)
    review_note = models.TextField("یادداشت بررسی", blank=True)
    draft_data = models.JSONField("پیش‌نویس پاسخ‌ها", default=dict, blank=True)
    template_snapshot = models.JSONField("نسخه چک‌لیست", default=list, blank=True)
    threshold_snapshot = models.PositiveSmallIntegerField("آستانه رد ثبت‌شده", default=20)
    failed_weight_percent = models.DecimalField("درصد وزن مردود", max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        ordering = ["due_date", "equipment__asset_code"]
        indexes = [models.Index(fields=["status", "due_date"])]
        verbose_name = "بازرسی"
        verbose_name_plural = "بازرسی‌ها"

    def __str__(self):
        return f"{self.equipment} — {self.get_status_display()} — {self.due_date}"


class InspectionResponse(models.Model):
    class Result(models.TextChoices):
        PASS = "pass", "مورد تأیید"
        FAIL = "fail", "نیازمند اقدام"
        NA = "na", "قابل‌اعمال نیست"

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="responses")
    item = models.ForeignKey(ChecklistItem, on_delete=models.PROTECT, null=True, blank=True)
    item_text = models.CharField("مورد بازرسی", max_length=240)
    critical = models.BooleanField("بحرانی", default=False)
    weight = models.PositiveSmallIntegerField("وزن ثبت‌شده", default=1)
    result = models.CharField("نتیجه", max_length=8, choices=Result.choices)
    comment = models.CharField("توضیح", max_length=500, blank=True)
    measurement = models.CharField("اندازه‌گیری", max_length=80, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "پاسخ بازرسی"
        verbose_name_plural = "پاسخ‌های بازرسی"


class Finding(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "کم"
        MEDIUM = "medium", "متوسط"
        HIGH = "high", "زیاد"
        CRITICAL = "critical", "بحرانی"
    class Status(models.TextChoices):
        OPEN = "open", "باز"
        PROGRESS = "progress", "در حال پیگیری"
        VERIFY = "verify", "در انتظار تأیید"
        CLOSED = "closed", "بسته‌شده"

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="findings", verbose_name="تجهیز")
    inspection = models.ForeignKey(Inspection, on_delete=models.PROTECT, null=True, blank=True, related_name="findings", verbose_name="بازرسی مرتبط")
    source_response = models.OneToOneField("InspectionResponse", on_delete=models.SET_NULL, null=True, blank=True, related_name="finding", verbose_name="پاسخ ایجادکننده نقص")
    description = models.TextField("شرح نقص")
    severity = models.CharField("شدت", max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    blocks_operation = models.BooleanField("توقف بهره‌برداری", default=False)
    assigned_to = models.CharField("مسئول پیگیری", max_length=120, blank=True)
    assigned_person = models.ForeignKey(Person, on_delete=models.PROTECT, null=True, blank=True, related_name="assigned_findings", verbose_name="مسئول رفع نقص")
    assigned_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_findings", verbose_name="حساب کاربری مسئول")
    due_date = models.DateField("مهلت اصلاح", null=True, blank=True)
    status = models.CharField("وضعیت اقدام", max_length=10, choices=Status.choices, default=Status.OPEN)
    resolution = models.TextField("شرح رفع نقص", blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="verified_findings", verbose_name="تأییدکننده")
    verified_at = models.DateTimeField("زمان تأیید", null=True, blank=True)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]
        verbose_name = "نقص / اقدام اصلاحی"
        verbose_name_plural = "نقص‌ها و اقدامات اصلاحی"

    def clean(self):
        if self.severity == self.Severity.CRITICAL:
            self.blocks_operation = True
        if self.status == self.Status.CLOSED and (not self.verified_by_id or not self.verified_at):
            raise ValidationError("برای بستن اقدام، تأیید مسئول مجاز الزامی است.")

    def save(self, *args, **kwargs):
        if self.severity == self.Severity.CRITICAL:
            self.blocks_operation = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.equipment.asset_code}: {self.description[:50]}"


class MaintenanceRecord(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="maintenance", verbose_name="تجهیز")
    date = models.DateField("تاریخ")
    kind = models.CharField("نوع تعمیر", max_length=100)
    description = models.TextField("شرح کار")
    provider = models.CharField("مجری", max_length=120, blank=True)
    meter_value = models.PositiveIntegerField("کارکرد", null=True, blank=True)
    cost = models.DecimalField("هزینه", max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField("واحد پول", max_length=12, blank=True, default="IRR")
    finding = models.ForeignKey(Finding, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance", verbose_name="نقص مرتبط")
    next_service = models.DateField("سرویس بعدی", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="ثبت‌کننده")

    class Meta:
        ordering = ["-date"]
        verbose_name = "سابقه تعمیر و نگهداری"
        verbose_name_plural = "سوابق تعمیر و نگهداری"


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="کاربر")
    action = models.CharField("رویداد", max_length=100)
    entity = models.CharField("نوع رکورد", max_length=80)
    entity_id = models.PositiveBigIntegerField("شناسه رکورد")
    details = models.TextField("جزئیات", blank=True)
    created_at = models.DateTimeField("زمان رویداد", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "رویداد سامانه"
        verbose_name_plural = "رویدادهای سامانه"
