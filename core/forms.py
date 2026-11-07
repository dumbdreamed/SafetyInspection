import json

from django import forms
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import (Assignment, ChecklistTemplate, Document, Equipment, EquipmentType,
                     Finding, Inspection, MaintenanceRecord, OrganizationCluster, OrganizationPosition, Person, Qualification, show_organization_chain)
from .equipment_sheets import EQUIPMENT_SHEET_PROFILES

INPUT = "field-input"


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {INPUT}".strip()
            field.widget.attrs.setdefault("dir", "auto")
            if field.required:
                field.widget.attrs["required"] = "required"


class EquipmentForm(StyledModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        register_fields = set().union(*EQUIPMENT_SHEET_PROFILES.values())
        allowed_fields = register_fields | {"equipment_type"}
        self.fields = {name: field for name, field in self.fields.items() if name in allowed_fields}
        if "equipment_type" in self.fields:
            self.fields["equipment_type"].queryset = EquipmentType.objects.filter(
                active=True, name__in=EQUIPMENT_SHEET_PROFILES
            )
        # Capacity units are display metadata (the source sheets specify tonnes
        # in their capacity headings) rather than a separate workbook column.
        self.fields.pop("capacity_unit", None)
        selected_type = self.data.get(self.add_prefix("equipment_type"))
        if not selected_type:
            selected_type = self.initial.get("equipment_type") or self.instance.equipment_type_id
        if hasattr(selected_type, "pk"):
            type_name = selected_type.name
        elif str(selected_type).isdigit():
            type_name = EquipmentType.objects.filter(pk=selected_type).values_list("name", flat=True).first()
        else:
            type_name = None
        profile = EQUIPMENT_SHEET_PROFILES.get(type_name)
        if self.is_bound and profile is not None:
            for name in register_fields - profile:
                self.fields.pop(name, None)

    def clean(self):
        cleaned = super().clean()
        equipment_type = cleaned.get("equipment_type")
        asset_code = (cleaned.get("asset_code") or "").strip()
        if equipment_type and asset_code:
            self.instance.name = f"{equipment_type.name} {asset_code}"
            profile = EQUIPMENT_SHEET_PROFILES.get(equipment_type.name, set())
            all_register_fields = set().union(*EQUIPMENT_SHEET_PROFILES.values())
            for name in all_register_fields - profile:
                field = Equipment._meta.get_field(name)
                setattr(self.instance, name, None if field.null else "")

        # These are application metadata fields, not columns in the machinery
        # workbook, so older values are cleared when an asset is saved again.
        for name in ("model_name", "owner", "area", "department", "power_type", "commissioned_on", "notes"):
            field = Equipment._meta.get_field(name)
            setattr(self.instance, name, None if field.null else "")
        return cleaned

    class Meta:
        model = Equipment
        exclude = ["name", "created_at", "updated_at", "created_by", "archived"]
        widgets = {
            "commissioned_on": forms.DateInput(attrs={"type": "date"}),
            "entered_on": forms.DateInput(attrs={"type": "date"}),
            "exited_on": forms.DateInput(attrs={"type": "date"}),
            "third_party_insurance_expires_on": forms.DateInput(attrs={"type": "date"}),
            "liability_insurance_expires_on": forms.DateInput(attrs={"type": "date"}),
            "desert_insurance_expires_on": forms.DateInput(attrs={"type": "date"}),
            "technical_inspection_expires_on": forms.DateInput(attrs={"type": "date"}),
            "certificate_issued_on": forms.DateInput(attrs={"type": "date"}),
            "certificate_expires_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class PersonForm(StyledModelForm):
    org_level = forms.ChoiceField(label="سطح سازمانی", choices=OrganizationPosition.Level.choices, initial=OrganizationPosition.Level.EMPLOYEE)
    org_title = forms.CharField(label="عنوان شغلی", max_length=120, required=False, help_text="در صورت خالی‌بودن، عنوان سطح سازمانی استفاده می‌شود.")
    org_manager = forms.ModelChoiceField(label="مدیر یا سرپرست مستقیم", queryset=OrganizationPosition.objects.none(), required=False, help_text="ابتدا سطح مدیریتی یا سرپرستی مدیر را ثبت کنید؛ با انتخاب او، چارت خودکار به‌روزرسانی می‌شود.")
    account_user = forms.ModelChoiceField(label="حساب ورود چک‌لیست", queryset=get_user_model().objects.none(), required=False, help_text="پیوند حساب کاربری این فرد برای ورود به بخش چک‌لیست‌ها.")
    create_account = forms.BooleanField(label="ساخت حساب ورود برای این فرد", required=False, help_text="حساب با نقش تکمیل‌کننده چک‌لیست ساخته می‌شود؛ فرد پس از دریافت لینک بازیابی گذرواژه می‌تواند آن را تنظیم کند.")
    account_username = forms.CharField(
        label="نام کاربری حساب چک‌لیست", max_length=150, required=False,
        help_text="نام کاربری به‌صورت خودکار از کد پرسنلی ساخته می‌شود.",
        widget=forms.TextInput(attrs={"readonly": "readonly", "data-account-username": ""}),
    )
    account_active = forms.BooleanField(label="حساب ورود فعال باشد", required=False, initial=True, help_text="حساب غیرفعال نمی‌تواند وارد فضای تکمیل چک‌لیست شود.")

    class Meta:
        model = Person
        exclude = ["created_at", "user"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["photo"].help_text = "اختیاری؛ فایل تصویری تا ۵ مگابایت."
        User = get_user_model()
        available_filter = Q(is_superuser=False, person_profile__isnull=True) & ~Q(groups__name__in=["Administrator", "Safety Manager"])
        if self.instance.pk and self.instance.user_id:
            available_filter |= Q(pk=self.instance.user_id)
            self.initial.setdefault("account_user", self.instance.user_id)
        self.fields["account_user"].queryset = User.objects.filter(available_filter).distinct()
        self.fields["account_user"].empty_label = "بدون حساب پیوندشده"
        if self.instance.pk:
            self.initial.setdefault("account_username", self.instance.employee_code.upper())
        self.order_fields(["full_name", "employee_code", "photo", "email", "account_user", "create_account", "account_username", "account_active", "org_level", "org_title", "org_manager", "department", "employer", "phone", "emergency_contact", "active", "notes"])
        if self.instance.pk and self.instance.user_id:
            self.initial.setdefault("account_active", self.instance.user.is_active)
        position = OrganizationPosition.objects.filter(person_id=self.instance.pk).select_related("manager").first() if self.instance.pk else None
        managers = OrganizationPosition.objects.select_related("person")
        managerial_levels = [OrganizationPosition.Level.TOP, OrganizationPosition.Level.MIDDLE, OrganizationPosition.Level.SUPERVISOR]
        if position:
            managers = managers.filter(Q(person__active=True, level__in=managerial_levels) | Q(pk=position.manager_id)).exclude(pk=position.pk)
            self.initial.setdefault("org_level", position.level)
            self.initial.setdefault("org_title", position.title)
            self.initial.setdefault("org_manager", position.manager_id)
        else:
            managers = managers.filter(person__active=True, level__in=managerial_levels)
        self.fields["org_manager"].queryset = managers

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > 5 * 1024 * 1024:
            raise ValidationError("حجم عکس باید کمتر از ۵ مگابایت باشد.")
        return photo

    def clean_employee_code(self):
        return (self.cleaned_data.get("employee_code") or "").strip().upper()

    def clean(self):
        cleaned = super().clean()
        employee_code = (cleaned.get("employee_code") or "").strip().upper()
        cleaned["employee_code"] = employee_code
        cleaned["account_username"] = employee_code
        if cleaned.get("create_account"):
            if cleaned.get("account_user"):
                self.add_error("account_user", "برای ساخت حساب جدید، حساب پیوندشده را خالی بگذارید.")
            if not cleaned.get("email"):
                self.add_error("email", "برای ساخت حساب، رایانامه فرد را وارد کنید.")
        linked_user = cleaned.get("account_user")
        if not linked_user and self.instance.pk:
            linked_user = self.instance.user
        if cleaned.get("create_account") or cleaned.get("account_user") or (self.instance.pk and self.instance.user_id):
            username_matches = get_user_model().objects.filter(username__iexact=employee_code)
            if linked_user:
                username_matches = username_matches.exclude(pk=linked_user.pk)
            if username_matches.exists():
                self.add_error("employee_code", "کد پرسنلی برای نام کاربری حساب دیگری استفاده شده است.")
        level = cleaned.get("org_level")
        if level:
            position = OrganizationPosition.objects.filter(person_id=self.instance.pk).first() if self.instance.pk else None
            position = position or OrganizationPosition(person=self.instance)
            title = (cleaned.get("org_title") or "").strip()
            if position.pk and position.level != level and title == dict(OrganizationPosition.Level.choices).get(position.level):
                title = ""
            position.level = level
            position.title = title or dict(OrganizationPosition.Level.choices)[level]
            cleaned["org_title"] = position.title
            position.manager = cleaned.get("org_manager")
            try:
                position.clean()
            except ValidationError as error:
                for field, errors in error.message_dict.items():
                    self.add_error({"manager": "org_manager", "level": "org_level"}.get(field), ValidationError(errors))
        return cleaned

    def save(self, commit=True):
        person = super().save(commit=False)
        def save_related():
            self._save_m2m()
            position, _ = OrganizationPosition.objects.get_or_create(person=person, defaults={"title": "کارمند", "chart_visible": False})
            position.level = self.cleaned_data["org_level"]
            position.title = (self.cleaned_data.get("org_title") or "").strip() or dict(OrganizationPosition.Level.choices)[position.level]
            position.manager = self.cleaned_data.get("org_manager")
            if position.manager_id or position.level in {OrganizationPosition.Level.TOP, OrganizationPosition.Level.MIDDLE, OrganizationPosition.Level.SUPERVISOR}:
                position.chart_visible = True
            position.full_clean()
            position.save()
            if position.chart_visible:
                show_organization_chain(position)
        if commit:
            with transaction.atomic():
                person.save()
                save_related()
        else:
            self.save_m2m = save_related
        return person


class OrganizationClusterForm(StyledModelForm):
    structure = forms.CharField(
        label="ساختار چارت",
        required=False,
        widget=forms.HiddenInput(attrs={"data-org-structure": ""}),
    )
    role_labels = forms.CharField(
        label="برچسب نقش‌ها",
        required=False,
        widget=forms.HiddenInput(attrs={"data-org-role-labels": ""}),
    )

    DEFAULT_ROLE_LABELS = {
        "top": "مدیر ارشد",
        "middle": "مدیر میانی",
        "supervisor": "سرپرست",
        "employee": "کارمند",
        "other": "سایر نقش‌ها",
    }

    class Meta:
        model = OrganizationCluster
        fields = ["name", "members", "role_labels"]
        widgets = {"members": forms.SelectMultiple(attrs={"data-org-members": ""})}
        help_texts = {"members": ""}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["members"].queryset = OrganizationPosition.objects.select_related("person").order_by("person__full_name")
        self.fields["members"].label_from_instance = lambda position: (
            f"{position.person.full_name} · {position.person.employee_code} — "
            f"{position.title} / {position.get_level_display()}"
        )
        initial_role_labels = {**self.DEFAULT_ROLE_LABELS, **(self.instance.role_labels or {})}
        self.fields["role_labels"].initial = json.dumps(initial_role_labels, ensure_ascii=False)
        self.order_fields(["name", "structure", "role_labels", "members"])

    def clean_role_labels(self):
        raw = self.cleaned_data.get("role_labels")
        if not raw:
            return self.DEFAULT_ROLE_LABELS.copy()
        try:
            submitted = json.loads(raw)
        except (TypeError, ValueError):
            raise ValidationError("برچسب نقش‌ها قابل خواندن نیست؛ نام نقش‌ها را بررسی کنید.")
        if not isinstance(submitted, dict):
            raise ValidationError("برچسب نقش‌ها باید یک فهرست معتبر باشد.")
        labels = self.DEFAULT_ROLE_LABELS.copy()
        for key, value in submitted.items():
            if key not in labels:
                continue
            value = str(value).strip()
            if not value or len(value) > 40:
                raise ValidationError("نام هر نقش باید بین ۱ تا ۴۰ نویسه باشد.")
            labels[key] = value
        return labels

    def clean_structure(self):
        raw = self.cleaned_data.get("structure")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            raise ValidationError("ساختار چارت قابل خواندن نیست؛ دوباره جایگاه‌ها را بررسی کنید.")

    def clean(self):
        cleaned = super().clean()
        nodes = cleaned.get("structure")
        if nodes is None:
            # Keep legacy requests that only submit group membership functional.
            return cleaned
        if not isinstance(nodes, list) or len(nodes) > 500:
            raise ValidationError("ساختار چارت معتبر نیست یا بیش از ۵۰۰ جایگاه دارد.")

        members = cleaned.get("members")
        if members is None:
            return cleaned
        member_ids = {position.pk for position in members}
        normalized, by_key, assigned = [], {}, set()
        for raw in nodes:
            if not isinstance(raw, dict):
                raise ValidationError("یکی از جایگاه‌های چارت معتبر نیست.")
            key = str(raw.get("key", "")).strip()
            level = str(raw.get("level", "")).strip()
            manager = raw.get("manager") or None
            person_id = raw.get("person") or None
            title = str(raw.get("title", "")).strip()
            if not key or len(key) > 60 or key in by_key:
                raise ValidationError("شناسه جایگاه‌ها باید یکتا باشد.")
            if level not in OrganizationPosition.Level.values:
                raise ValidationError("سطح سازمانی یکی از جایگاه‌ها معتبر نیست.")
            if manager is not None:
                manager = str(manager)
                if len(manager) > 60 or manager == key:
                    raise ValidationError("مدیر مستقیم یکی از جایگاه‌ها معتبر نیست.")
            if person_id is not None:
                try:
                    person_id = int(person_id)
                except (TypeError, ValueError):
                    raise ValidationError("فرد انتخاب‌شده برای یکی از جایگاه‌ها معتبر نیست.")
                if person_id not in member_ids or person_id in assigned:
                    raise ValidationError("هر فرد باید فقط در یک جایگاه از همین گروه قرار بگیرد.")
                assigned.add(person_id)
            if len(title) > 120:
                raise ValidationError("عنوان جایگاه حداکثر می‌تواند ۱۲۰ نویسه باشد.")
            item = {"key": key, "person": person_id, "level": level, "title": title, "manager": manager}
            normalized.append(item)
            by_key[key] = item

        if not normalized:
            if member_ids:
                raise ValidationError("افراد گروه را در جایگاه‌های نمودار قرار دهید.")
            cleaned["structure"] = []
            return cleaned
        roots = [item for item in normalized if item["manager"] is None]
        if len(roots) != 1 or roots[0]["level"] != OrganizationPosition.Level.TOP:
            raise ValidationError("چارت باید دقیقاً یک ریشه با نقش مدیر ارشد داشته باشد.")
        if member_ids != assigned:
            raise ValidationError("همه اعضای گروه باید در یکی از جایگاه‌های چارت قرار بگیرند.")

        managerial_levels = {
            OrganizationPosition.Level.TOP,
            OrganizationPosition.Level.MIDDLE,
            OrganizationPosition.Level.SUPERVISOR,
        }
        for item in normalized:
            manager_key = item["manager"]
            if manager_key is None:
                continue
            parent = by_key.get(manager_key)
            if parent is None or parent["level"] not in managerial_levels:
                raise ValidationError("هر فرد باید زیرمجموعه یک جایگاه مدیریتی یا سرپرستی باشد.")
            if item["person"] is not None and parent["person"] is None:
                raise ValidationError("برای هر جایگاهی که زیرمجموعه دارد، یک مدیر را انتخاب کنید.")
            if item["level"] == OrganizationPosition.Level.TOP:
                raise ValidationError("نقش مدیر ارشد فقط برای جایگاه ریشه قابل استفاده است.")

        for item in normalized:
            seen, current = set(), item
            while current["manager"] is not None:
                if current["key"] in seen:
                    raise ValidationError("در ساختار چارت چرخه مدیریتی ایجاد شده است.")
                seen.add(current["key"])
                current = by_key[current["manager"]]
        cleaned["structure"] = normalized
        return cleaned


class OrganizationPositionForm(StyledModelForm):
    class Meta:
        model = OrganizationPosition
        fields = ["person", "title", "level", "manager", "order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = Person.objects.order_by("full_name")
        managers = OrganizationPosition.objects.select_related("person")
        managerial_levels = [OrganizationPosition.Level.TOP, OrganizationPosition.Level.MIDDLE, OrganizationPosition.Level.SUPERVISOR]
        if self.instance.pk:
            self.fields["person"].disabled = True
            managers = managers.filter(Q(person__active=True, level__in=managerial_levels) | Q(pk=self.instance.manager_id)).exclude(pk=self.instance.pk)
        else:
            managers = managers.filter(person__active=True, level__in=managerial_levels)
        self.fields["manager"].queryset = managers
        self.fields["manager"].help_text = "برای بالاترین سطح، این گزینه را خالی بگذارید."


class AssignmentForm(StyledModelForm):
    class Meta:
        model = Assignment
        fields = "__all__"
        widgets = {"starts_on": forms.DateInput(attrs={"type": "date"}), "ends_on": forms.DateInput(attrs={"type": "date"})}


class QualificationForm(StyledModelForm):
    class Meta:
        model = Qualification
        fields = "__all__"
        widgets = {"issued_on": forms.DateInput(attrs={"type": "date"}), "expires_on": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 2})}


class DocumentForm(StyledModelForm):
    class Meta:
        model = Document
        exclude = ["uploaded_by", "uploaded_at", "superseded_by"]
        widgets = {"issued_on": forms.DateInput(attrs={"type": "date"}), "expires_on": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 2}), "file": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"})}

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if not upload:
            return upload
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise ValidationError(f"حجم فایل نباید از {settings.MAX_UPLOAD_MB} مگابایت بیشتر باشد.")
        suffix = upload.name.lower().rsplit(".", 1)[-1] if "." in upload.name else ""
        signatures = {"pdf": b"%PDF-", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n"}
        head = upload.read(16)
        upload.seek(0)
        if suffix not in signatures or not head.startswith(signatures[suffix]):
            raise ValidationError("محتوای فایل با پسوند مجاز (PDF، JPG یا PNG) هم‌خوانی ندارد.")
        return upload


class InspectionScheduleForm(StyledModelForm):
    class Meta:
        model = Inspection
        fields = ["equipment", "template", "inspector", "due_date", "instructions"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}), "instructions": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.filter(archived=False)
        self.fields["template"].queryset = ChecklistTemplate.objects.filter(active=True)
        User = get_user_model()
        inspector_filter = Q(is_active=True, person_profile__active=True, groups__name="Inspector") & ~Q(groups__name__in=["Administrator", "Safety Manager"])
        initial_inspector = self.initial.get("inspector")
        if initial_inspector:
            inspector_filter |= Q(pk=initial_inspector)
        self.fields["inspector"].queryset = User.objects.filter(inspector_filter).distinct()
        def inspector_label(user):
            try:
                person = user.person_profile
            except Person.DoesNotExist:
                person = None
            return f"{person.full_name} · {user.username}" if person else user.get_full_name() or user.username
        self.fields["inspector"].label_from_instance = inspector_label

    def clean(self):
        cleaned = super().clean()
        equipment, template = cleaned.get("equipment"), cleaned.get("template")
        if equipment and template and template.equipment_type_id and template.equipment_type_id != equipment.equipment_type_id:
            self.add_error("template", "این چک‌لیست برای نوع تجهیز انتخاب‌شده نیست.")
        return cleaned


class InspectionReassignmentForm(StyledModelForm):
    class Meta:
        model = Inspection
        fields = ["inspector", "due_date"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        inspector_filter = Q(is_active=True, person_profile__active=True, groups__name="Inspector") & ~Q(groups__name__in=["Administrator", "Safety Manager"])
        if self.instance.pk and self.instance.inspector_id:
            inspector_filter |= Q(pk=self.instance.inspector_id)
        self.fields["inspector"].queryset = User.objects.filter(inspector_filter).distinct()
        self.fields["inspector"].label_from_instance = lambda user: (
            f"{user.person_profile.full_name} · {user.username}"
            if hasattr(user, "person_profile") else user.get_full_name() or user.username
        )


class InspectionDelegationForm(forms.Form):
    inspector = forms.ModelChoiceField(queryset=get_user_model().objects.none(), label="مسئول تکمیل",
                                       widget=forms.Select(attrs={"class": INPUT}))
    due_date = forms.DateField(label="مهلت انجام", widget=forms.DateInput(attrs={"type": "date", "class": INPUT}))
    instructions = forms.CharField(label="دستور ویژه (اختیاری)", required=False, max_length=2000,
                                   widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "دستور یکسان برای چک‌لیست‌های انتخاب‌شده"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        eligible = Q(is_active=True, person_profile__active=True, groups__name="Inspector") & ~Q(groups__name__in=["Administrator", "Safety Manager"])
        self.fields["inspector"].queryset = User.objects.filter(eligible).distinct()
        self.fields["inspector"].label_from_instance = lambda user: (
            f"{user.person_profile.full_name} · {user.username}"
            if hasattr(user, "person_profile") else user.get_full_name() or user.username
        )


class FindingForm(StyledModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_person"].required = True
        self.fields["assigned_person"].queryset = Person.objects.filter(
            active=True, user__is_active=True, user__groups__name="Inspector"
        ).exclude(user__groups__name__in=["Administrator", "Safety Manager"]).distinct()
        self.fields["due_date"].required = True

    def save(self, commit=True):
        finding = super().save(commit=False)
        if finding.assigned_person_id:
            finding.assigned_to = finding.assigned_person.full_name[:120]
        if commit:
            finding.save()
            self.save_m2m()
        return finding

    class Meta:
        model = Finding
        fields = ["equipment", "inspection", "description", "severity", "blocks_operation", "assigned_person", "due_date"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}), "description": forms.Textarea(attrs={"rows": 3})}


class FindingCloseForm(StyledModelForm):
    class Meta:
        model = Finding
        fields = ["status", "resolution"]
        widgets = {"resolution": forms.Textarea(attrs={"rows": 3})}


class MaintenanceForm(StyledModelForm):
    class Meta:
        model = MaintenanceRecord
        exclude = ["created_by"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "next_service": forms.DateInput(attrs={"type": "date"}), "description": forms.Textarea(attrs={"rows": 3})}


class EquipmentTypeForm(StyledModelForm):
    class Meta:
        model = EquipmentType
        fields = ["name", "icon", "active"]
