import csv
import io
import json
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import (AssignmentForm, DocumentForm, EquipmentForm, EquipmentTypeForm, FindingCloseForm,
                    InspectionScheduleForm, MaintenanceForm, PersonForm, QualificationForm)
from .models import (Area, Assignment, AuditLog, ChecklistItem, ChecklistTemplate, Department, Document,
                     DocumentCategory, Equipment, EquipmentType, Finding, Inspection, InspectionResponse,
                     MaintenanceRecord, Person, Qualification, QualificationType, add_months)


EDITOR_GROUPS = {"Administrator", "Safety Manager", "Inspector"}
MANAGER_GROUPS = {"Administrator", "Safety Manager"}


def can_edit(user):
    return user.is_superuser or user.groups.filter(name__in=EDITOR_GROUPS).exists()


def can_manage(user):
    return user.is_superuser or user.groups.filter(name__in=MANAGER_GROUPS).exists()


def require_edit(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not can_edit(request.user):
            raise PermissionDenied("دسترسی ویرایش برای نقش شما فعال نیست.")
        return view(request, *args, **kwargs)
    return wrapped


def require_manager(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied("این عملیات به دسترسی مدیر ایمنی نیاز دارد.")
        return view(request, *args, **kwargs)
    return wrapped


def record_event(user, action, obj, details=""):
    AuditLog.objects.create(actor=user, action=action, entity=obj._meta.verbose_name, entity_id=obj.pk, details=details[:1000])


@login_required
def dashboard(request):
    today = timezone.localdate()
    equipment = Equipment.objects.filter(archived=False).select_related("equipment_type", "area", "department")
    people = Person.objects.filter(active=True)
    inspections = Inspection.objects.select_related("equipment", "template", "inspector")
    q = request.GET.get("q", "").strip()
    area_id = request.GET.get("area", "")
    type_id = request.GET.get("type", "")
    if area_id.isdigit():
        equipment = equipment.filter(area_id=area_id)
    if type_id.isdigit():
        equipment = equipment.filter(equipment_type_id=type_id)
    if q:
        equipment = equipment.filter(Q(name__icontains=q) | Q(asset_code__icontains=q) | Q(serial_number__icontains=q))
    ids = equipment.values("id")
    if not (q or area_id or type_id):
        by_type = EquipmentType.objects.filter(active=True).annotate(
            total=Count("equipment", filter=Q(equipment__archived=False))
        ).values("id", "name", "icon", "total").order_by("name")
    else:
        by_type = equipment.values("equipment_type_id", "equipment_type__name", "equipment_type__icon").annotate(
            total=Count("id")
        ).order_by("equipment_type__name")
    scheduled = inspections.filter(equipment_id__in=ids, status=Inspection.Status.SCHEDULED)
    findings = Finding.objects.filter(equipment_id__in=ids).exclude(status=Finding.Status.CLOSED)
    docs = Document.objects.filter(equipment_id__in=ids, superseded_by__isnull=True)
    due_docs = docs.filter(expires_on__isnull=False, expires_on__lte=today + timedelta(days=30))
    qual_docs = Document.objects.filter(qualification__person__in=people, superseded_by__isnull=True, expires_on__isnull=False, expires_on__lte=today + timedelta(days=30))
    qualifications = Qualification.objects.filter(person__in=people, expires_on__isnull=False)
    scoped_people = people
    if area_id.isdigit() or type_id.isdigit():
        scoped_people = people.filter(assignments__equipment_id__in=ids).distinct()
    context = {
        "equipment_total": equipment.count(), "by_type": by_type,
        "available_total": equipment.filter(status=Equipment.Status.ACTIVE).exclude(findings__blocks_operation=True, findings__status__in=[Finding.Status.OPEN, Finding.Status.PROGRESS, Finding.Status.VERIFY]).distinct().count(),
        "stopped_total": equipment.filter(Q(status__in=[Equipment.Status.STOPPED, Equipment.Status.SERVICE]) | Q(findings__blocks_operation=True, findings__status__in=[Finding.Status.OPEN, Finding.Status.PROGRESS, Finding.Status.VERIFY])).distinct().count(),
        "uninspected_total": equipment.exclude(id__in=Inspection.objects.filter(status=Inspection.Status.COMPLETED, outcome__in=[Inspection.Outcome.PASS, Inspection.Outcome.CONDITIONAL]).values("equipment_id")).count(),
        "overdue_total": scheduled.filter(due_date__lt=today).count(),
        "due_week": scheduled.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
        "due_month": scheduled.filter(due_date__gte=today, due_date__lte=today + timedelta(days=30)).count(),
        "critical_total": findings.filter(severity=Finding.Severity.CRITICAL).count(),
        "expired_docs": docs.filter(expires_on__lt=today).count(), "soon_docs": due_docs.filter(expires_on__gte=today).count(),
        "expired_qual_docs": qual_docs.filter(expires_on__lt=today).count() + qualifications.filter(expires_on__lt=today).count(),
        "soon_qual_docs": qual_docs.filter(expires_on__gte=today).count() + qualifications.filter(expires_on__gte=today).count(),
        "active_people": scoped_people.count(),
        "upcoming": scheduled.filter(due_date__gte=today).order_by("due_date")[:8],
        "alerts": list(scheduled.filter(due_date__lt=today).order_by("due_date")[:4]) + list(findings.filter(severity=Finding.Severity.CRITICAL)[:4]),
        "recent": Inspection.objects.filter(status=Inspection.Status.COMPLETED).select_related("equipment", "inspector").order_by("-completed_at")[:6],
        "areas": Area.objects.all(), "types": EquipmentType.objects.filter(active=True), "selected_area": area_id, "selected_type": type_id, "q": q,
        "chart_max": max([item["total"] for item in by_type] or [1]),
    }
    return render(request, "core/dashboard.html", context)


@login_required
def equipment_list(request):
    qs = Equipment.objects.filter(archived=False).select_related("equipment_type", "area", "department")
    q = request.GET.get("q", "").strip()
    type_id, area_id, status = request.GET.get("type", ""), request.GET.get("area", ""), request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(asset_code__icontains=q) | Q(name__icontains=q) | Q(serial_number__icontains=q) | Q(plate__icontains=q))
    if type_id.isdigit(): qs = qs.filter(equipment_type_id=type_id)
    if area_id.isdigit(): qs = qs.filter(area_id=area_id)
    if status in Equipment.Status.values: qs = qs.filter(status=status)
    return render(request, "core/equipment_list.html", {"equipment": qs, "types": EquipmentType.objects.filter(active=True), "areas": Area.objects.all(), "q": q, "selected_type": type_id, "selected_area": area_id, "selected_status": status})


@require_manager
def equipment_edit(request, pk=None):
    obj = get_object_or_404(Equipment, pk=pk, archived=False) if pk else None
    form = EquipmentForm(request.POST or None, request.FILES or None, instance=obj)
    if form.is_valid():
        item = form.save(commit=False)
        if not item.pk: item.created_by = request.user
        item.full_clean()
        item.save()
        record_event(request.user, "ویرایش تجهیز" if obj else "ثبت تجهیز", item)
        messages.success(request, "تجهیز ذخیره شد.")
        return redirect("equipment_detail", pk=item.pk)
    return render(request, "core/form.html", {"form": form, "title": "ویرایش تجهیز" if obj else "ثبت تجهیز", "back_url": "equipment_list", "submit_label": "ذخیره تجهیز"})


@login_required
def equipment_detail(request, pk):
    item = get_object_or_404(Equipment.objects.select_related("equipment_type", "area", "department"), pk=pk)
    active_today = timezone.localdate()
    return render(request, "core/equipment_detail.html", {"item": item, "assignments": item.assignments.filter(Q(ends_on__isnull=True) | Q(ends_on__gte=active_today)).select_related("person"), "documents": item.documents.all(), "inspections": item.inspections.select_related("template", "inspector")[:10], "findings": item.findings.exclude(status=Finding.Status.CLOSED), "maintenance": item.maintenance.all()[:6], "can_edit": can_manage(request.user), "can_manage": can_manage(request.user)})


@require_manager
@require_POST
def equipment_archive(request, pk):
    item = get_object_or_404(Equipment, pk=pk)
    item.archived = True
    item.save(update_fields=["archived", "updated_at"])
    record_event(request.user, "بایگانی تجهیز", item)
    messages.success(request, "تجهیز به بایگانی منتقل شد.")
    return redirect("equipment_list")


@login_required
def people_list(request):
    qs = Person.objects.prefetch_related("qualifications").annotate(active_assignments=Count("assignments", filter=Q(assignments__ends_on__isnull=True) | Q(assignments__ends_on__gte=timezone.localdate()), distinct=True))
    q = request.GET.get("q", "").strip()
    if q: qs = qs.filter(Q(full_name__icontains=q) | Q(employee_code__icontains=q) | Q(employer__icontains=q))
    return render(request, "core/people_list.html", {"people": qs, "q": q, "can_manage": can_manage(request.user)})


@require_manager
def person_edit(request, pk=None):
    obj = get_object_or_404(Person, pk=pk) if pk else None
    form = PersonForm(request.POST or None, request.FILES or None, instance=obj)
    if form.is_valid():
        person = form.save()
        record_event(request.user, "ویرایش شخص" if obj else "ثبت شخص", person)
        messages.success(request, "اطلاعات فرد ذخیره شد.")
        return redirect("person_detail", pk=person.pk)
    return render(request, "core/form.html", {"form": form, "title": "ویرایش مشخصات" if obj else "ثبت راننده / اپراتور", "back_url": "people_list", "submit_label": "ذخیره"})


@login_required
def person_detail(request, pk):
    person = get_object_or_404(Person.objects.prefetch_related("qualifications__documents", "assignments__equipment", "documents"), pk=pk)
    return render(request, "core/person_detail.html", {"person": person, "can_edit": can_manage(request.user), "can_sensitive": can_manage(request.user) or request.user.is_superuser})


@require_manager
def assignment_new(request):
    initial = {}
    if request.GET.get("equipment", "").isdigit(): initial["equipment"] = request.GET["equipment"]
    form = AssignmentForm(request.POST or None, initial=initial)
    if form.is_valid():
        assignment = form.save(commit=False); assignment.full_clean(); assignment.save()
        record_event(request.user, "تخصیص راننده / اپراتور", assignment.equipment, str(assignment.person))
        messages.success(request, "تخصیص اپراتور ثبت شد.")
        return redirect("equipment_detail", pk=assignment.equipment_id)
    return render(request, "core/form.html", {"form": form, "title": "تخصیص راننده / اپراتور", "back_url": "equipment_list", "submit_label": "ثبت تخصیص"})


@require_manager
def qualification_new(request):
    form = QualificationForm(request.POST or None)
    if form.is_valid():
        obj = form.save(); obj.full_clean()
        record_event(request.user, "ثبت صلاحیت", obj.person, obj.qualification_type.name)
        messages.success(request, "صلاحیت ثبت شد.")
        return redirect("person_detail", pk=obj.person_id)
    return render(request, "core/form.html", {"form": form, "title": "ثبت صلاحیت یا گواهی", "back_url": "people_list", "submit_label": "ثبت صلاحیت"})


@require_edit
def document_new(request):
    form = DocumentForm(request.POST or None, request.FILES or None)
    if not can_manage(request.user):
        form.fields["verification"].disabled = True
    if form.is_valid():
        obj = form.save(commit=False)
        if (obj.person_id or obj.qualification_id) and not can_manage(request.user):
            raise PermissionDenied("بارگذاری و مدیریت مدارک شخصی به مدیر ایمنی نیاز دارد.")
        obj.uploaded_by = request.user; obj.full_clean(); obj.save()
        record_event(request.user, "بارگذاری مدرک", obj, obj.title)
        messages.success(request, "مدرک به شکل خصوصی بارگذاری شد.")
        if obj.equipment_id: return redirect("equipment_detail", pk=obj.equipment_id)
        if obj.person_id: return redirect("person_detail", pk=obj.person_id)
        if obj.qualification_id: return redirect("person_detail", pk=obj.qualification.person_id)
        if obj.inspection_id: return redirect("inspection_detail", pk=obj.inspection_id)
        return redirect("finding_list")
    return render(request, "core/form.html", {"form": form, "title": "بارگذاری مدرک خصوصی", "back_url": "dashboard", "submit_label": "بارگذاری امن", "file_upload": True, "help_text": "فقط یک مورد مرتبط را انتخاب کنید. فایل‌ها فقط با ورود مجاز قابل دریافت‌اند."})


@login_required
def document_download(request, pk):
    doc = get_object_or_404(Document.objects.select_related("person", "qualification__person"), pk=pk)
    manager = can_manage(request.user) or request.user.is_superuser
    inspector = request.user.groups.filter(name="Inspector").exists()
    viewer = request.user.groups.filter(name="Viewer").exists()
    if (doc.person_id or doc.qualification_id) and not manager:
        raise PermissionDenied("دریافت مدارک شخصی به نقش مدیر محدود است.")
    if viewer and not manager and not inspector:
        raise PermissionDenied("نقش مشاهده‌گر به فایل‌های پیوست دسترسی ندارد.")
    response = FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.title + doc.file.name[doc.file.name.rfind("."):])
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def inspection_list(request):
    qs = Inspection.objects.select_related("equipment", "template", "inspector")
    if request.user.groups.filter(name="Inspector").exists() and not can_manage(request.user):
        qs = qs.filter(inspector=request.user)
    status = request.GET.get("status", "")
    if status in Inspection.Status.values: qs = qs.filter(status=status)
    if request.GET.get("overdue") == "1": qs = qs.filter(status=Inspection.Status.SCHEDULED, due_date__lt=timezone.localdate())
    return render(request, "core/inspection_list.html", {"inspections": qs, "selected_status": status, "today": timezone.localdate()})


@require_manager
def inspection_new(request):
    form = InspectionScheduleForm(request.POST or None, initial={"inspector": request.user.pk, "due_date": timezone.localdate()})
    if form.is_valid():
        inspection = form.save(commit=False); inspection.full_clean(); inspection.save()
        inspection.template_snapshot = list(inspection.template.items.values("id", "section", "description", "critical"))
        inspection.save(update_fields=["template_snapshot"])
        record_event(request.user, "برنامه‌ریزی بازرسی", inspection, inspection.due_date.isoformat())
        messages.success(request, "بازرسی برنامه‌ریزی شد.")
        return redirect("inspection_detail", pk=inspection.pk)
    return render(request, "core/form.html", {"form": form, "title": "برنامه‌ریزی بازرسی", "back_url": "inspection_list", "submit_label": "ثبت برنامه"})


@login_required
def inspection_detail(request, pk):
    inspection = get_object_or_404(Inspection.objects.select_related("equipment", "template", "inspector"), pk=pk)
    if request.user.groups.filter(name="Inspector").exists() and not can_manage(request.user) and inspection.inspector_id != request.user.pk:
        raise PermissionDenied("بازرسی‌های دیگر بازرس‌ها برای شما در دسترس نیست.")
    items = inspection.template_snapshot or list(inspection.template.items.values("id", "section", "description", "critical"))
    saved = {response.item_id: response for response in inspection.responses.all()}
    for item in items:
        response = saved.get(item.get("id"))
        item["saved_result"] = response.get_result_display() if response else ""
        item["saved_comment"] = response.comment if response else ""
    return render(request, "core/inspection_detail.html", {"inspection": inspection, "items": items, "today": timezone.localdate(), "can_complete": can_edit(request.user) and inspection.status in [Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS] and (can_manage(request.user) or inspection.inspector_id == request.user.pk)})


@require_edit
@require_POST
def inspection_complete(request, pk):
    with transaction.atomic():
        inspection = get_object_or_404(Inspection.objects.select_for_update().select_related("template", "equipment", "inspector"), pk=pk)
        if inspection.status not in [Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS]:
            messages.error(request, "این بازرسی پیش‌تر نهایی شده است."); return redirect("inspection_detail", pk=pk)
        if not can_manage(request.user) and inspection.inspector_id != request.user.pk:
            raise PermissionDenied("فقط بازرس تخصیص‌یافته می‌تواند این بازرسی را ثبت کند.")
        snapshot = inspection.template_snapshot or list(inspection.template.items.values("id", "section", "description", "critical"))
        failures = []
        for item in snapshot:
            response_value = request.POST.get(f"result_{item['id']}")
            if response_value not in ["pass", "fail", "na"]:
                messages.error(request, "برای همه موارد چک‌لیست یک نتیجه انتخاب کنید."); return redirect("inspection_detail", pk=pk)
            comment = request.POST.get(f"comment_{item['id']}", "").strip()
            if response_value == "na" and not comment:
                messages.error(request, "برای موارد غیرقابل‌اعمال توضیح بنویسید."); return redirect("inspection_detail", pk=pk)
            if response_value == "fail" and not comment:
                messages.error(request, "شرح نقص برای موارد مردود الزامی است."); return redirect("inspection_detail", pk=pk)
            InspectionResponse.objects.create(inspection=inspection, item_id=item.get("id"), item_text=item["description"], critical=item.get("critical", False), result=response_value, comment=comment, measurement=request.POST.get(f"measurement_{item['id']}", "")[:80])
            if response_value == "fail": failures.append((item, comment))
        meter = request.POST.get("meter_value", "").strip()
        if meter and (not meter.isdigit() or int(meter) < 0):
            messages.error(request, "عدد کارکرد معتبر وارد کنید."); return redirect("inspection_detail", pk=pk)
        inspection.outcome = (Inspection.Outcome.FAIL if any(item.get("critical") for item, _ in failures)
                              else Inspection.Outcome.CONDITIONAL if failures
                              else Inspection.Outcome.PASS)
        inspection.status = Inspection.Status.COMPLETED
        inspection.completed_at = timezone.now()
        inspection.meter_value = int(meter) if meter else None
        inspection.notes = request.POST.get("notes", "")[:3000]
        inspection.template_snapshot = snapshot
        inspection.save()
        for item, comment in failures:
            Finding.objects.create(equipment=inspection.equipment, inspection=inspection,
                                   description=f"{item['description']}: {comment}",
                                   severity=Finding.Severity.CRITICAL if item.get("critical") else Finding.Severity.MEDIUM,
                                   blocks_operation=bool(item.get("critical")))
        record_event(request.user, "تکمیل بازرسی", inspection, inspection.get_outcome_display())
        if inspection.outcome != Inspection.Outcome.FAIL and inspection.template.interval_months:
            next_date = add_months(timezone.localdate(), inspection.template.interval_months)
            Inspection.objects.create(equipment=inspection.equipment, template=inspection.template, inspector=inspection.inspector, due_date=next_date, notes="بازرسی دوره‌ای بعدی")
        elif inspection.outcome != Inspection.Outcome.FAIL and inspection.template.interval_days:
            next_date = timezone.localdate() + timedelta(days=inspection.template.interval_days)
            Inspection.objects.create(equipment=inspection.equipment, template=inspection.template, inspector=inspection.inspector, due_date=next_date, notes="بازرسی دوره‌ای بعدی")
    messages.success(request, "بازرسی نهایی شد و سابقه آن ثبت شد.")
    return redirect("inspection_detail", pk=pk)


@login_required
def finding_list(request):
    qs = Finding.objects.exclude(status=Finding.Status.CLOSED).select_related("equipment", "inspection")
    return render(request, "core/finding_list.html", {"findings": qs, "can_edit": can_edit(request.user), "can_manage": can_manage(request.user)})


@require_manager
def finding_new(request):
    from .forms import FindingForm
    form = FindingForm(request.POST or None)
    form.fields["equipment"].queryset = Equipment.objects.filter(archived=False)
    if form.is_valid():
        finding = form.save(commit=False)
        if finding.severity == Finding.Severity.CRITICAL:
            finding.blocks_operation = True
        finding.full_clean(); finding.save()
        record_event(request.user, "ثبت نقص دستی", finding, finding.description)
        messages.success(request, "نقص و اقدام اصلاحی ثبت شد.")
        return redirect("finding_list")
    return render(request, "core/form.html", {"form": form, "title": "ثبت نقص و اقدام اصلاحی", "back_url": "finding_list", "submit_label": "ثبت نقص"})


@require_edit
@require_POST
def finding_close(request, pk):
    with transaction.atomic():
        finding = get_object_or_404(Finding.objects.select_for_update().select_related("equipment"), pk=pk)
        action = request.POST.get("action", "")
        resolution = request.POST.get("resolution", "").strip()
        if action not in ["progress", "verify", "close"] or not resolution:
            messages.error(request, "وضعیت و توضیحات اصلاح را وارد کنید."); return redirect("finding_list")
        finding.resolution = resolution
        if action == "progress": finding.status = Finding.Status.PROGRESS
        elif action == "verify": finding.status = Finding.Status.VERIFY
        else:
            if not can_manage(request.user): raise PermissionDenied("بستن نقص و بازگشت به سرویس به تأیید مدیر نیاز دارد.")
            if finding.blocks_operation and not finding.equipment.inspections.filter(status=Inspection.Status.COMPLETED, outcome__in=[Inspection.Outcome.PASS, Inspection.Outcome.CONDITIONAL], completed_at__gt=finding.created_at).exists():
                messages.error(request, "پیش از بازگشت تجهیز بحرانی به سرویس، بازرسی مجدد با نتیجه قبول لازم است."); return redirect("finding_list")
            finding.status = Finding.Status.CLOSED; finding.verified_by = request.user; finding.verified_at = timezone.now()
        finding.save()
    record_event(request.user, "به‌روزرسانی اقدام اصلاحی", finding, finding.get_status_display())
    messages.success(request, "وضعیت اقدام اصلاحی ثبت شد.")
    return redirect("finding_list")


@login_required
def maintenance_list(request):
    items = MaintenanceRecord.objects.select_related("equipment", "created_by", "finding")
    return render(request, "core/maintenance_list.html", {"items": items})


@require_manager
def maintenance_new(request):
    form = MaintenanceForm(request.POST or None)
    form.fields["equipment"].queryset = Equipment.objects.filter(archived=False)
    form.fields["finding"].queryset = Finding.objects.exclude(status=Finding.Status.CLOSED)
    if form.is_valid():
        obj = form.save(commit=False); obj.created_by = request.user; obj.save()
        record_event(request.user, "ثبت سابقه نگهداری", obj.equipment, obj.kind)
        messages.success(request, "سابقه تعمیر ثبت شد.")
        return redirect("maintenance_list")
    return render(request, "core/form.html", {"form": form, "title": "ثبت تعمیر و نگهداری", "back_url": "maintenance_list", "submit_label": "ثبت سابقه"})


@login_required
def reports(request):
    equipment = Equipment.objects.filter(archived=False).select_related("equipment_type", "area", "department")
    inspections = Inspection.objects.select_related("equipment", "template", "inspector")
    findings = Finding.objects.select_related("equipment").exclude(status=Finding.Status.CLOSED)
    if request.GET.get("area", "").isdigit(): equipment = equipment.filter(area_id=request.GET["area"])
    if request.GET.get("type", "").isdigit(): equipment = equipment.filter(equipment_type_id=request.GET["type"])
    if request.GET.get("area", "").isdigit():
        inspections = inspections.filter(equipment__area_id=request.GET["area"])
        findings = findings.filter(equipment__area_id=request.GET["area"])
    if request.GET.get("type", "").isdigit():
        inspections = inspections.filter(equipment__equipment_type_id=request.GET["type"])
        findings = findings.filter(equipment__equipment_type_id=request.GET["type"])
    return render(request, "core/reports.html", {"equipment": equipment, "inspections": inspections[:12], "findings": findings[:12], "types": EquipmentType.objects.filter(active=True), "areas": Area.objects.all(), "selected_type": request.GET.get("type", ""), "selected_area": request.GET.get("area", "")})


@login_required
def equipment_csv(request):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["کد اموال", "نام تجهیز", "نوع", "ناحیه", "واحد", "وضعیت", "سازنده", "شماره سریال"])
    equipment = Equipment.objects.filter(archived=False).select_related("equipment_type", "area", "department")
    if request.GET.get("area", "").isdigit(): equipment = equipment.filter(area_id=request.GET["area"])
    if request.GET.get("type", "").isdigit(): equipment = equipment.filter(equipment_type_id=request.GET["type"])
    for item in equipment:
        row = [item.asset_code, item.name, item.equipment_type.name, str(item.area or ""), str(item.department or ""), item.get_status_display(), item.manufacturer, item.serial_number]
        writer.writerow([("'" + str(cell)) if str(cell).startswith(("=", "+", "-", "@", "\t", "\r")) else cell for cell in row])
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = "attachment; filename=equipment-report.csv"
    return response


@login_required
def settings_page(request):
    return render(request, "core/settings.html", {"types": EquipmentType.objects.all(), "areas": Area.objects.all(), "departments": Department.objects.select_related("area"), "categories": DocumentCategory.objects.all(), "qualification_types": QualificationType.objects.all(), "templates": ChecklistTemplate.objects.prefetch_related("items").all(), "can_manage": can_manage(request.user)})


@require_manager
def type_new(request):
    form = EquipmentTypeForm(request.POST or None)
    if form.is_valid():
        form.save(); messages.success(request, "نوع تجهیز اضافه شد."); return redirect("settings_page")
    return render(request, "core/form.html", {"form": form, "title": "افزودن نوع تجهیز", "back_url": "settings_page", "submit_label": "ذخیره نوع"})


@require_GET
def health(request):
    from django.db import connection
    from django.conf import settings
    try:
        with connection.cursor() as cursor: cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unhealthy"}, status=503)
    if not settings.DEBUG:
        ready = (settings.PERSISTENCE_CONFIRMED
                 and (settings.PERSISTENCE_DIR / ".safetyinspection-initialized").exists()
                 and (settings.PERSISTENCE_DIR / "backups" / "latest.sqlite3").exists())
        if not ready:
            return JsonResponse({"status": "degraded", "persistence": "not-confirmed"}, status=503)
    return JsonResponse({"status": "ok"})
