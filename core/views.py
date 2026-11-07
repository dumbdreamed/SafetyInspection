import csv
import io
import json
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, Exists, OuterRef
from django.db.models.functions import TruncMonth
from django.http import Http404, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from .forms import (AssignmentForm, DocumentForm, EquipmentForm, EquipmentTypeForm, FindingCloseForm,
                    InspectionScheduleForm, MaintenanceForm, OrganizationClusterForm, OrganizationPositionForm, PersonForm, QualificationForm)
from .equipment_sheets import EQUIPMENT_SHEET_PROFILES
from .models import (Area, Assignment, AuditLog, ChecklistItem, ChecklistTemplate, Department, Document,
                     DocumentCategory, Equipment, EquipmentType, Finding, Inspection, InspectionResponse,
                     MaintenanceRecord, OrganizationCluster, OrganizationPosition, Person, Qualification, QualificationType, add_months, show_organization_chain)


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
    scoped_inspections = Inspection.objects.filter(equipment_id__in=ids)
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

    def build_chart_rows(choices, counts):
        total = sum(counts.values())
        return {
            "total": total,
            "rows": [
                {"key": key, "label": label, "total": counts.get(key, 0),
                 "percent": round(counts.get(key, 0) * 100 / total) if total else 0}
                for key, label in choices
            ],
        }

    equipment_status_counts = dict(
        equipment.values("status").annotate(total=Count("id")).values_list("status", "total")
    )
    outcome_counts = dict(
        scoped_inspections.filter(
            status=Inspection.Status.COMPLETED,
            outcome__in=[key for key, _ in Inspection.Outcome.choices],
        )
        .values("outcome").annotate(total=Count("id")).values_list("outcome", "total")
    )
    open_finding_counts = dict(
        findings.values("severity").annotate(total=Count("id")).values_list("severity", "total")
    )

    month_starts = [today.replace(day=1)]
    for _ in range(5):
        month_starts.append((month_starts[-1] - timedelta(days=1)).replace(day=1))
    month_starts.reverse()
    trend_counts = {
        (row["month"].year, row["month"].month): row["total"]
        for row in scoped_inspections.filter(
            status=Inspection.Status.COMPLETED,
            completed_at__date__gte=month_starts[0],
            completed_at__date__lte=today,
        ).annotate(month=TruncMonth("completed_at")).values("month").annotate(total=Count("id"))
    }
    inspection_trend = [
        {"label": f"{month:%m}/{month:%Y}", "total": trend_counts.get((month.year, month.month), 0)}
        for month in month_starts
    ]
    trend_max = max((row["total"] for row in inspection_trend), default=0) or 1
    for row in inspection_trend:
        row["height"] = max(4, round(row["total"] * 100 / trend_max)) if row["total"] else 2

    status_chart = build_chart_rows(Equipment.Status.choices, equipment_status_counts)
    if status_chart["total"]:
        active_share = equipment_status_counts.get(Equipment.Status.ACTIVE, 0) * 100 / status_chart["total"]
        service_share = active_share + equipment_status_counts.get(Equipment.Status.SERVICE, 0) * 100 / status_chart["total"]
        status_chart["gradient"] = (
            f"conic-gradient(#3f9b78 0% {active_share:.2f}%, "
            f"#e4ad4e {active_share:.2f}% {service_share:.2f}%, "
            f"#d36d63 {service_share:.2f}% 100%)"
        )
    outcome_chart = build_chart_rows(Inspection.Outcome.choices, outcome_counts)
    severity_chart = build_chart_rows(
        [(key, label) for key, label in reversed(Finding.Severity.choices)], open_finding_counts
    )
    finding_status_counts = dict(
        Finding.objects.filter(equipment_id__in=ids)
        .values("status").annotate(total=Count("id")).values_list("status", "total")
    )
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
        "status_chart": status_chart,
        "outcome_chart": outcome_chart,
        "severity_chart": severity_chart,
        "inspection_trend": inspection_trend,
        "inspection_trend_has_data": any(row["total"] for row in inspection_trend),
        "finding_workflow": [
            {"key": key, "label": label, "total": finding_status_counts.get(key, 0)}
            for key, label in Finding.Status.choices
        ],
    }
    return render(request, "core/dashboard.html", context)


@login_required
def equipment_list(request):
    qs = Equipment.objects.filter(archived=False).select_related("equipment_type")
    q = request.GET.get("q", "").strip()
    type_id, status = request.GET.get("type", ""), request.GET.get("status", "")
    if q:
        qs = qs.filter(
            Q(asset_code__icontains=q) | Q(machine_subtype__icontains=q) | Q(manufacturer__icontains=q)
            | Q(plate__icontains=q) | Q(serial_number__icontains=q) | Q(vin__icontains=q)
            | Q(engine_number__icontains=q) | Q(position__icontains=q)
        )
    if type_id.isdigit(): qs = qs.filter(equipment_type_id=type_id)
    if status in Equipment.Status.values: qs = qs.filter(status=status)
    equipment = list(qs)
    for item in equipment:
        item.sheet_fields = EQUIPMENT_SHEET_PROFILES.get(item.equipment_type.name, set())
    return render(request, "core/equipment_list.html", {
        "equipment": equipment,
        "types": EquipmentType.objects.filter(active=True, name__in=EQUIPMENT_SHEET_PROFILES),
        "equipment_statuses": Equipment.Status.choices,
        "q": q,
        "selected_type": type_id,
        "selected_status": status,
    })


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
    profiles = {str(item.pk): sorted(EQUIPMENT_SHEET_PROFILES[item.name]) for item in EquipmentType.objects.filter(active=True, name__in=EQUIPMENT_SHEET_PROFILES)}
    return render(request, "core/form.html", {"form": form, "title": "ویرایش تجهیز" if obj else "ثبت تجهیز", "back_url": "equipment_list", "submit_label": "ذخیره تجهیز", "equipment_field_profiles": profiles})


@login_required
def equipment_detail(request, pk):
    item = get_object_or_404(Equipment.objects.select_related("equipment_type", "area", "department"), pk=pk)
    active_today = timezone.localdate()
    documents = item.documents.select_related("category").filter(superseded_by__isnull=True)
    sheet_fields = EQUIPMENT_SHEET_PROFILES.get(item.equipment_type.name, set())
    checklist = ChecklistTemplate.objects.filter(equipment_type=item.equipment_type, active=True, name__startswith="چک‌لیست ایمنی پیشنهادی").prefetch_related("items").first()
    checks = list(checklist.items.all()) if checklist else []
    latest_inspection = item.inspections.filter(status=Inspection.Status.COMPLETED).order_by("-completed_at", "-pk").first()
    return render(request, "core/equipment_detail.html", {
        "item": item,
        "sheet_fields": sheet_fields,
        "equipment_checklist": checklist,
        "checklist_items": checks,
        "checklist_critical_count": sum(1 for check in checks if check.critical),
        "latest_inspection": latest_inspection,
        "assignments": item.assignments.filter(Q(ends_on__isnull=True) | Q(ends_on__gte=active_today)).select_related("person"),
        "documents": item.documents.select_related("category").all(),
        "third_party_insurance": documents.filter(category__name__icontains="ثالث").order_by("-uploaded_at").first(),
        "liability_insurance": documents.filter(category__name__icontains="مسئولیت").order_by("-uploaded_at").first(),
        "inspections": item.inspections.select_related("template", "inspector")[:10],
        "findings": item.findings.exclude(status=Finding.Status.CLOSED),
        "maintenance": item.maintenance.all()[:6],
        "can_edit": can_manage(request.user),
        "can_manage": can_manage(request.user),
    })


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
    qs = Person.objects.select_related("organization_position__manager__person").prefetch_related("qualifications").annotate(active_assignments=Count("assignments", filter=Q(assignments__ends_on__isnull=True) | Q(assignments__ends_on__gte=timezone.localdate()), distinct=True))
    q = request.GET.get("q", "").strip()
    if q: qs = qs.filter(Q(full_name__icontains=q) | Q(employee_code__icontains=q) | Q(employer__icontains=q))
    return render(request, "core/people_list.html", {"people": qs, "q": q, "can_manage": can_manage(request.user)})


@require_manager
def person_edit(request, pk=None):
    obj = get_object_or_404(Person, pk=pk) if pk else None
    form = PersonForm(request.POST or None, request.FILES or None, instance=obj)
    with transaction.atomic():
        if request.method == "POST":
            list(OrganizationPosition.objects.select_for_update().values_list("pk", flat=True))
        if form.is_valid():
            person = form.save()
            record_event(request.user, "ویرایش شخص" if obj else "ثبت شخص", person)
            messages.success(request, "اطلاعات فرد و جایگاه سازمانی ذخیره شد.")
            if request.GET.get("next") == "organization":
                return redirect("organization_chart")
            return redirect("person_detail", pk=person.pk)
    return render(request, "core/form.html", {"form": form, "title": "ویرایش مشخصات" if obj else "ثبت فرد", "back_url": "people_list", "submit_label": "ذخیره"})


@login_required
def person_photo(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if not person.photo:
        raise Http404("عکس پروفایل ثبت نشده است.")
    import mimetypes
    response = FileResponse(person.photo.open("rb"), content_type=mimetypes.guess_type(person.photo.name)[0] or "image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300"
    return response


@login_required
def organization_chart(request):
    all_positions = list(OrganizationPosition.objects.select_related("person", "manager__person").prefetch_related("clusters").annotate(
        open_findings=Count("person__assigned_findings", filter=~Q(person__assigned_findings__status=Finding.Status.CLOSED), distinct=True)
    ))
    selected_cluster = None
    cluster_id = request.GET.get("cluster", "")
    if cluster_id.isdigit():
        selected_cluster = get_object_or_404(OrganizationCluster, pk=cluster_id)
    role_labels = selected_cluster.role_labels if selected_cluster and isinstance(selected_cluster.role_labels, dict) else {}
    members = set(selected_cluster.members.values_list("pk", flat=True)) if selected_cluster else None
    positions = [position for position in all_positions if position.chart_visible and (members is None or position.pk in members)]
    unplaced = [position for position in all_positions if not position.chart_visible]
    nodes = {position.pk: {
        "position": position, "children": [],
        "role_label": role_labels.get(position.level) or position.get_level_display(),
    } for position in positions}
    roots = []
    for position in positions:
        node = nodes[position.pk]
        if position.manager_id in nodes:
            nodes[position.manager_id]["children"].append(node)
        else:
            roots.append(node)
    return render(request, "core/organization_chart.html", {
        "roots": roots, "position_count": len(positions),
        "total_visible": sum(1 for position in all_positions if position.chart_visible),
        "clusters": OrganizationCluster.objects.all(), "selected_cluster": selected_cluster,
        "unplaced_count": len(unplaced), "unplaced_positions": unplaced,
        "can_manage": can_manage(request.user),
    })


def organization_cluster_builder_data(cluster):
    root = {
        "key": "slot-root", "person": None, "level": OrganizationPosition.Level.TOP,
        "title": "مدیر ارشد کارخانه", "manager": None,
    }
    if not cluster:
        return [root]

    if isinstance(cluster.chart_structure, list) and cluster.chart_structure:
        return cluster.chart_structure

    positions = list(cluster.members.select_related("person", "manager").order_by("order", "person__full_name", "pk"))
    if not positions:
        return [root]

    member_ids = {position.pk for position in positions}
    roots = [position for position in positions if position.manager_id not in member_ids]
    nodes = []
    if len(roots) != 1:
        nodes.append(root)
    root_position = roots[0] if len(roots) == 1 else None
    for position in positions:
        is_root = position.manager_id not in member_ids
        level = position.level
        manager_key = f"p-{position.manager_id}" if position.manager_id in member_ids else None
        if root_position and position.pk == root_position.pk:
            if level != OrganizationPosition.Level.TOP:
                position_title = "مدیر ارشد کارخانه"
            else:
                position_title = position.title
            level = OrganizationPosition.Level.TOP
        elif not root_position and is_root:
            manager_key = root["key"]
            if level == OrganizationPosition.Level.TOP:
                level = OrganizationPosition.Level.MIDDLE
                position_title = "مدیر میانی"
            else:
                position_title = position.title
        else:
            position_title = position.title
        nodes.append({
            "key": f"p-{position.pk}", "person": position.pk,
            "level": level, "title": position_title,
            "manager": manager_key,
        })
    return nodes


@require_manager
def organization_cluster_edit(request, pk=None):
    cluster = get_object_or_404(OrganizationCluster, pk=pk) if pk else None
    form = OrganizationClusterForm(request.POST or None, instance=cluster)
    if request.method == "GET":
        form.initial["structure"] = json.dumps(organization_cluster_builder_data(cluster), ensure_ascii=False)
    if form.is_valid():
        with transaction.atomic():
            if form.cleaned_data.get("structure") is not None:
                list(OrganizationPosition.objects.select_for_update().values_list("pk", flat=True))
            structure = form.cleaned_data.get("structure")
            cluster = form.save(commit=False)
            if structure is not None:
                cluster.chart_structure = structure
            cluster.save()
            form.save_m2m()
            if structure is not None:
                positions = list(cluster.members.select_for_update())
                by_position = {position.pk: position for position in positions}
                by_slot = {
                    item["key"]: by_position[item["person"]]
                    for item in structure if item["person"] is not None
                }
                for index, item in enumerate(structure):
                    if item["person"] is None:
                        continue
                    position = by_position[item["person"]]
                    position.level = item["level"]
                    position.title = item["title"] or dict(OrganizationPosition.Level.choices)[item["level"]]
                    manager_slot = by_slot.get(item["manager"]) if item["manager"] else None
                    position.manager_id = manager_slot.pk if manager_slot else None
                    position.order = index
                    position.chart_visible = True
                if by_position:
                    OrganizationPosition.objects.bulk_update(
                        by_position.values(), ["level", "title", "manager", "order", "chart_visible"]
                    )
            for position in cluster.members.select_related("manager"):
                show_organization_chain(position)
            record_event(request.user, "ویرایش گروه چارت" if pk else "ثبت گروه چارت", cluster)
        messages.success(request, "گروه سازمانی ذخیره شد.")
        return redirect(f"{reverse('organization_chart')}?cluster={cluster.pk}")
    return render(request, "core/organization_cluster_form.html", {"form": form, "title": "ویرایش گروه چارت" if cluster else "ساخت گروه چارت", "back_url": "organization_chart", "submit_label": "ذخیره گروه و چارت"})


@require_manager
@require_POST
def organization_cluster_delete(request, pk):
    with transaction.atomic():
        cluster = get_object_or_404(OrganizationCluster.objects.select_for_update(), pk=pk)
        record_event(request.user, "حذف گروه چارت", cluster, cluster.name)
        cluster.delete()
    messages.success(request, "گروه حذف شد؛ افراد و روابط مدیریتی حفظ شدند.")
    return redirect("organization_chart")


@require_manager
def organization_edit(request, pk=None):
    if pk is None:
        person_id = request.GET.get("person", "")
        if person_id.isdigit() and Person.objects.filter(pk=person_id).exists():
            return redirect(f"{reverse('person_edit', args=[int(person_id)])}?next=organization")
        return redirect(f"{reverse('person_new')}?next=organization")
    position = get_object_or_404(OrganizationPosition, pk=pk)
    form = OrganizationPositionForm(request.POST or None, instance=position)
    with transaction.atomic():
        if request.method == "POST":
            # Lock existing positions while checking the hierarchy before saving.
            list(OrganizationPosition.objects.select_for_update().values_list("pk", flat=True))
        if form.is_valid():
            saved = form.save(commit=False)
            saved.chart_visible = True
            saved.save()
            show_organization_chain(saved)
            record_event(request.user, "ویرایش جایگاه سازمانی", saved)
            messages.success(request, "جایگاه سازمانی ذخیره شد.")
            return redirect("organization_chart")
    return render(request, "core/form.html", {"form": form, "title": "ویرایش جایگاه سازمانی", "back_url": "organization_chart", "submit_label": "ذخیره جایگاه"})


@require_manager
@require_POST
def organization_remove(request, pk):
    with transaction.atomic():
        position = get_object_or_404(OrganizationPosition.objects.select_for_update(), pk=pk)
        OrganizationPosition.objects.filter(manager=position).update(manager=position.manager)
        record_event(request.user, "حذف جایگاه سازمانی", position, position.person.full_name)
        position.manager = None
        position.chart_visible = False
        position.save(update_fields=["manager", "chart_visible"])
    messages.success(request, "فرد از نمودار جدا شد؛ نقش حفظ و زیرمجموعه‌ها به مدیر بالاتر منتقل شدند.")
    return redirect("organization_chart")


@require_manager
@require_POST
def organization_clear(request):
    with transaction.atomic():
        count = OrganizationPosition.objects.filter(chart_visible=True).count()
        OrganizationPosition.objects.all().update(manager=None, chart_visible=False)
        AuditLog.objects.create(actor=request.user, action="پاک‌کردن چارت سازمانی", entity="OrganizationPosition", entity_id=0, details=str(count))
    messages.success(request, "روابط و نمودار پاک شدند؛ نقش‌ها، اطلاعات افراد و اقدامات حفظ شدند.")
    return redirect("organization_chart")


@login_required
def person_detail(request, pk):
    person = get_object_or_404(Person.objects.prefetch_related("qualifications__documents", "assignments__equipment", "documents"), pk=pk)
    return render(request, "core/person_detail.html", {
        "person": person,
        "position": OrganizationPosition.objects.filter(person=person).select_related("manager__person").first(),
        "assigned_findings_count": person.assigned_findings.exclude(status=Finding.Status.CLOSED).count(),
        "can_edit": can_manage(request.user), "can_sensitive": can_manage(request.user) or request.user.is_superuser,
    })


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
    initial = {}
    equipment_id = request.GET.get("equipment", "")
    if request.method == "GET" and equipment_id.isdigit():
        initial["equipment"] = get_object_or_404(Equipment, pk=equipment_id)
    form = DocumentForm(request.POST or None, request.FILES or None, initial=initial)
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
    initial = {"inspector": request.user.pk, "due_date": timezone.localdate()}
    equipment_id = request.GET.get("equipment", "")
    if equipment_id.isdigit():
        equipment = Equipment.objects.filter(pk=equipment_id, archived=False).select_related("equipment_type").first()
        if equipment:
            initial["equipment"] = equipment.pk
            template = ChecklistTemplate.objects.filter(equipment_type=equipment.equipment_type, active=True, name__startswith="چک‌لیست ایمنی پیشنهادی").first()
            if template: initial["template"] = template.pk
    form = InspectionScheduleForm(request.POST or None, initial=initial)
    if form.is_valid():
        inspection = form.save(commit=False); inspection.full_clean(); inspection.save()
        inspection.template_snapshot = list(inspection.template.items.values("id", "section", "description", "critical", "weight"))
        inspection.threshold_snapshot = inspection.template.rejection_threshold
        inspection.save(update_fields=["template_snapshot", "threshold_snapshot"])
        record_event(request.user, "برنامه‌ریزی بازرسی", inspection, inspection.due_date.isoformat())
        messages.success(request, "بازرسی برنامه‌ریزی شد.")
        return redirect("inspection_detail", pk=inspection.pk)
    return render(request, "core/form.html", {"form": form, "title": "برنامه‌ریزی بازرسی", "back_url": "inspection_list", "submit_label": "ثبت برنامه"})


@login_required
def inspection_detail(request, pk):
    inspection = get_object_or_404(Inspection.objects.select_related("equipment", "template", "inspector"), pk=pk)
    if request.user.groups.filter(name="Inspector").exists() and not can_manage(request.user) and inspection.inspector_id != request.user.pk:
        raise PermissionDenied("بازرسی‌های دیگر بازرس‌ها برای شما در دسترس نیست.")
    items = inspection.template_snapshot or list(inspection.template.items.values("id", "section", "description", "critical", "weight"))
    saved = {response.item_id: response for response in inspection.responses.all()}
    for item in items:
        response = saved.get(item.get("id"))
        item["saved_result"] = response.get_result_display() if response else ""
        item["saved_comment"] = response.comment if response else ""
    return render(request, "core/inspection_detail.html", {"inspection": inspection, "items": items, "people": Person.objects.filter(active=True), "today": timezone.localdate(), "can_complete": can_edit(request.user) and inspection.status in [Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS] and (can_manage(request.user) or inspection.inspector_id == request.user.pk)})


@require_edit
@require_POST
def inspection_complete(request, pk):
    with transaction.atomic():
        inspection = get_object_or_404(Inspection.objects.select_for_update().select_related("template", "equipment", "inspector"), pk=pk)
        if inspection.status not in [Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS]:
            messages.error(request, "این بازرسی پیش‌تر نهایی شده است."); return redirect("inspection_detail", pk=pk)
        if not can_manage(request.user) and inspection.inspector_id != request.user.pk:
            raise PermissionDenied("فقط بازرس تخصیص‌یافته می‌تواند این بازرسی را ثبت کند.")
        snapshot = inspection.template_snapshot or list(inspection.template.items.values("id", "section", "description", "critical", "weight"))
        failures, answers = [], []
        if not snapshot:
            messages.error(request, "چک‌لیست خالی قابل نهایی‌کردن نیست."); return redirect("inspection_detail", pk=pk)
        for item in snapshot:
            response_value = request.POST.get(f"result_{item['id']}")
            if response_value not in ["pass", "fail", "na"]:
                messages.error(request, "برای همه موارد چک‌لیست یک نتیجه انتخاب کنید."); return redirect("inspection_detail", pk=pk)
            comment = request.POST.get(f"comment_{item['id']}", "").strip()
            if response_value == "na" and not comment:
                messages.error(request, "برای موارد غیرقابل‌اعمال توضیح بنویسید."); return redirect("inspection_detail", pk=pk)
            if response_value == "fail" and not comment:
                messages.error(request, "شرح نقص برای موارد مردود الزامی است."); return redirect("inspection_detail", pk=pk)
            if response_value == "fail":
                person_id = request.POST.get(f"assigned_{item['id']}", "").strip()
                assigned_person = Person.objects.filter(pk=person_id, active=True).first() if person_id.isdigit() else None
                try:
                    due_date = parse_date(request.POST.get(f"due_{item['id']}", "").strip())
                except ValueError:
                    due_date = None
                if not assigned_person or not due_date:
                    messages.error(request, "برای هر نقص، نام مسئول و مهلت معتبر اصلاح را وارد کنید."); return redirect("inspection_detail", pk=pk)
                failures.append((item, comment, assigned_person, due_date))
            answers.append((item, response_value, comment, request.POST.get(f"measurement_{item['id']}", "")[:80]))
        meter = request.POST.get("meter_value", "").strip()
        if meter and (not meter.isdigit() or int(meter) < 0):
            messages.error(request, "عدد کارکرد معتبر وارد کنید."); return redirect("inspection_detail", pk=pk)
        applicable_weight = sum(item.get("weight", 1) for item, result, _, _ in answers if result != "na")
        if not applicable_weight:
            messages.error(request, "حداقل یک مورد باید قابل‌اعمال باشد."); return redirect("inspection_detail", pk=pk)
        failed_weight = sum(item.get("weight", 1) for item, _, _, _ in failures)
        percent = Decimal(failed_weight) * 100 / Decimal(applicable_weight)
        threshold = inspection.threshold_snapshot if inspection.template_snapshot else inspection.template.rejection_threshold
        for item, result, comment, measurement in answers:
            InspectionResponse.objects.create(inspection=inspection, item_id=item.get("id"), item_text=item["description"], critical=item.get("critical", False), weight=item.get("weight", 1), result=result, comment=comment, measurement=measurement)
        inspection.failed_weight_percent = percent
        inspection.threshold_snapshot = threshold
        inspection.outcome = (Inspection.Outcome.FAIL if any(item.get("critical") for item, _, _, _ in failures) or percent >= threshold
                              else Inspection.Outcome.CONDITIONAL if failures
                              else Inspection.Outcome.PASS)
        inspection.status = Inspection.Status.COMPLETED
        inspection.completed_at = timezone.now()
        inspection.meter_value = int(meter) if meter else None
        inspection.notes = request.POST.get("notes", "")[:3000]
        inspection.template_snapshot = snapshot
        inspection.save()
        for item, comment, assigned_person, due_date in failures:
            Finding.objects.create(equipment=inspection.equipment, inspection=inspection,
                                   description=f"{item['description']}: {comment}",
                                   severity=Finding.Severity.CRITICAL if item.get("critical") else Finding.Severity.MEDIUM,
                                   blocks_operation=bool(item.get("critical")), assigned_person=assigned_person, assigned_to=assigned_person.full_name[:120], due_date=due_date)
        record_event(request.user, "تکمیل بازرسی", inspection, inspection.get_outcome_display())
        if inspection.outcome != Inspection.Outcome.FAIL and inspection.template.interval_months:
            next_date = add_months(timezone.localdate(), inspection.template.interval_months)
            Inspection.objects.create(equipment=inspection.equipment, template=inspection.template, inspector=inspection.inspector, due_date=next_date, notes="بازرسی دوره‌ای بعدی", template_snapshot=list(inspection.template.items.values("id", "section", "description", "critical", "weight")), threshold_snapshot=inspection.template.rejection_threshold)
        elif inspection.outcome != Inspection.Outcome.FAIL and inspection.template.interval_days:
            next_date = timezone.localdate() + timedelta(days=inspection.template.interval_days)
            Inspection.objects.create(equipment=inspection.equipment, template=inspection.template, inspector=inspection.inspector, due_date=next_date, notes="بازرسی دوره‌ای بعدی", template_snapshot=list(inspection.template.items.values("id", "section", "description", "critical", "weight")), threshold_snapshot=inspection.template.rejection_threshold)
    messages.success(request, "بازرسی نهایی شد و سابقه آن ثبت شد.")
    return redirect("inspection_detail", pk=pk)


def filtered_findings(params):
    qs = Finding.objects.select_related("equipment", "inspection", "assigned_person")
    status = params.get("status", "active")
    if status == "active" or status not in ["all", *Finding.Status.values]:
        qs = qs.exclude(status=Finding.Status.CLOSED)
    elif status != "all":
        qs = qs.filter(status=status)
    for param, field in (("equipment", "equipment_id"), ("type", "equipment__equipment_type_id"), ("assignee", "assigned_person_id")):
        value = params.get(param, "")
        if value.isdigit(): qs = qs.filter(**{field: int(value)})
    area = params.get("area", "")
    if area.isdigit(): qs = qs.filter(equipment__area_id=int(area))
    elif area == "none": qs = qs.filter(equipment__area__isnull=True)
    driver = params.get("driver", "")
    if driver.isdigit():
        today = timezone.localdate()
        assignments = Assignment.objects.filter(equipment_id=OuterRef("equipment_id"), person_id=int(driver), starts_on__lte=today).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        qs = qs.filter(Exists(assignments))
    severity = params.get("severity", "")
    if severity in Finding.Severity.values: qs = qs.filter(severity=severity)
    equipment_status = params.get("equipment_status", "")
    if equipment_status in Equipment.Status.values: qs = qs.filter(equipment__status=equipment_status)
    if params.get("deadline") == "overdue":
        qs = qs.exclude(status=Finding.Status.CLOSED).filter(due_date__lt=timezone.localdate())
    elif params.get("deadline") == "unset":
        qs = qs.filter(due_date__isnull=True)
    q = params.get("q", "").strip()
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(equipment__asset_code__icontains=q) | Q(equipment__name__icontains=q) | Q(assigned_person__full_name__icontains=q) | Q(assigned_to__icontains=q))
    return qs


@login_required
def finding_list(request):
    return render(request, "core/finding_list.html", {
        "findings": filtered_findings(request.GET), "filters": request.GET,
        "selected_status": request.GET.get("status", "active"),
        "equipment_options": Equipment.objects.filter(findings__isnull=False).distinct().order_by("asset_code"),
        "equipment_types": EquipmentType.objects.filter(equipment__findings__isnull=False).distinct(),
        "areas": Area.objects.all(), "drivers": Person.objects.filter(assignments__isnull=False).distinct(),
        "assignees": Person.objects.filter(assigned_findings__isnull=False).distinct(),
        "people": Person.objects.filter(active=True), "statuses": Finding.Status.choices,
        "severities": Finding.Severity.choices, "equipment_statuses": Equipment.Status.choices,
        "can_edit": can_edit(request.user), "can_manage": can_manage(request.user),
    })


@require_manager
def finding_new(request):
    from .forms import FindingForm
    initial = {}
    if request.GET.get("assignee", "").isdigit(): initial["assigned_person"] = request.GET["assignee"]
    form = FindingForm(request.POST or None, initial=initial)
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


def finding_action_response(request, finding, message, *, error=False):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        matches = filtered_findings(request.GET).filter(pk=finding.pk).exists()
        payload = {"ok": not error, "message": message, "closed": finding.status == Finding.Status.CLOSED, "remove": not matches}
        if not error and matches:
            payload["html"] = render_to_string("core/finding_card.html", {
                "finding": finding, "people": Person.objects.filter(active=True),
                "can_edit": can_edit(request.user), "can_manage": can_manage(request.user),
            }, request=request)
        return JsonResponse(payload, status=400 if error else 200)
    (messages.error if error else messages.success)(request, message)
    target = reverse("finding_list")
    return redirect(f"{target}?{request.GET.urlencode()}" if request.GET else target)


@require_edit
@require_POST
def finding_close(request, pk):
    with transaction.atomic():
        finding = get_object_or_404(Finding.objects.select_for_update().select_related("equipment"), pk=pk)
        action = request.POST.get("action", "")
        if finding.status == Finding.Status.CLOSED:
            return finding_action_response(request, finding, "این اقدام قبلاً بسته شده است.", error=True)
        if action == "assign":
            person_id = request.POST.get("assigned_person", "").strip()
            assigned_person = Person.objects.filter(pk=person_id, active=True).first() if person_id.isdigit() else None
            try:
                due_date = parse_date(request.POST.get("due_date", "").strip())
            except ValueError:
                due_date = None
            if not assigned_person or not due_date:
                return finding_action_response(request, finding, "نام مسئول و مهلت معتبر اصلاح الزامی است.", error=True)
            finding.assigned_person, finding.assigned_to, finding.due_date = assigned_person, assigned_person.full_name[:120], due_date
            finding.save(update_fields=["assigned_person", "assigned_to", "due_date"])
            record_event(request.user, "تخصیص اقدام اصلاحی", finding, assigned_person.full_name)
            return finding_action_response(request, finding, "مسئول و مهلت اصلاح ثبت شد.")
        resolution = request.POST.get("resolution", "").strip()
        if action not in ["progress", "verify", "close"] or not resolution:
            return finding_action_response(request, finding, "وضعیت و توضیحات اصلاح را وارد کنید.", error=True)
        if not finding.assigned_person_id or not finding.due_date:
            return finding_action_response(request, finding, "ابتدا مسئول و مهلت اصلاح را تعیین کنید.", error=True)
        finding.resolution = resolution
        if action == "progress": finding.status = Finding.Status.PROGRESS
        elif action == "verify": finding.status = Finding.Status.VERIFY
        else:
            if not can_manage(request.user): raise PermissionDenied("بستن نقص و بازگشت به سرویس به تأیید مدیر نیاز دارد.")
            if finding.blocks_operation and not finding.equipment.inspections.filter(status=Inspection.Status.COMPLETED, outcome__in=[Inspection.Outcome.PASS, Inspection.Outcome.CONDITIONAL], completed_at__gt=finding.created_at).exists():
                return finding_action_response(request, finding, "پیش از بازگشت تجهیز بحرانی به سرویس، بازرسی مجدد با نتیجه قبول لازم است.", error=True)
            finding.status = Finding.Status.CLOSED; finding.verified_by = request.user; finding.verified_at = timezone.now()
        finding.save()
    record_event(request.user, "به‌روزرسانی اقدام اصلاحی", finding, finding.get_status_display())
    return finding_action_response(request, finding, "وضعیت اقدام اصلاحی ثبت شد.")


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
    csv_field_order = [
        "machine_subtype", "manufacturer", "year", "plate", "serial_number", "vin", "engine_number", "position",
        "third_party_insurance_expires_on", "liability_insurance_expires_on", "desert_insurance_expires_on",
        "technical_inspection_expires_on", "rated_capacity", "confirmed_capacity", "large_hook_capacity",
        "small_hook_capacity", "certificate_issued_on", "certificate_expires_on", "status", "entered_on", "exited_on",
        "primary_contractor", "subcontractor",
    ]
    available_fields = set().union(*EQUIPMENT_SHEET_PROFILES.values())
    csv_fields = [name for name in csv_field_order if name in available_fields]
    writer.writerow(["کد دستگاه", str(Equipment._meta.get_field("equipment_type").verbose_name)] + [
        str(Equipment._meta.get_field(name).verbose_name) for name in csv_fields
    ])
    equipment = Equipment.objects.filter(archived=False).select_related("equipment_type")
    if request.GET.get("type", "").isdigit(): equipment = equipment.filter(equipment_type_id=request.GET["type"])
    for item in equipment:
        profile = EQUIPMENT_SHEET_PROFILES.get(item.equipment_type.name, set())
        row = [item.asset_code, item.equipment_type.name]
        for name in csv_fields:
            if name not in profile:
                row.append("")
            elif name == "status":
                row.append(item.get_status_display())
            else:
                row.append(getattr(item, name) or "")
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
    if not settings.DEBUG and settings.PERSISTENCE_CONFIRMED:
        ready = (settings.PERSISTENCE_CONFIRMED
                 and (settings.PERSISTENCE_DIR / ".safetyinspection-initialized").exists()
                 and (settings.PERSISTENCE_DIR / "backups" / "latest.sqlite3").exists())
        if not ready:
            return JsonResponse({"status": "degraded", "persistence": "not-confirmed"}, status=503)
    storage = "local" if settings.DEBUG else ("persistent" if settings.PERSISTENCE_CONFIRMED else "ephemeral")
    return JsonResponse({"status": "ok", "storage": storage})
