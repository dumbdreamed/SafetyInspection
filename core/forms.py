from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import (Assignment, ChecklistTemplate, Document, Equipment, EquipmentType,
                     Finding, Inspection, MaintenanceRecord, Person, Qualification)

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
    class Meta:
        model = Equipment
        exclude = ["created_at", "updated_at", "created_by", "archived"]
        widgets = {"commissioned_on": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}


class PersonForm(StyledModelForm):
    class Meta:
        model = Person
        exclude = ["created_at"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


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
        fields = ["equipment", "template", "inspector", "due_date", "notes"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.filter(archived=False)
        self.fields["template"].queryset = ChecklistTemplate.objects.filter(active=True)

    def clean(self):
        cleaned = super().clean()
        equipment, template = cleaned.get("equipment"), cleaned.get("template")
        if equipment and template and template.equipment_type_id and template.equipment_type_id != equipment.equipment_type_id:
            self.add_error("template", "این چک‌لیست برای نوع تجهیز انتخاب‌شده نیست.")
        return cleaned


class FindingForm(StyledModelForm):
    class Meta:
        model = Finding
        fields = ["equipment", "inspection", "description", "severity", "blocks_operation", "assigned_to", "due_date"]
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
