import csv
import io
import json
import secrets
import smtplib
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Group
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
                    InspectionDelegationForm, InspectionReassignmentForm, InspectionScheduleForm, MaintenanceForm, OrganizationClusterForm, OrganizationPositionForm, PersonForm, QualificationForm)
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


def is_checklist_filler(user):
    return user.is_authenticated and not can_manage(user) and user.groups.filter(name="Inspector").exists()


def checklist_assignees():
    return Person.objects.filter(
        active=True, user__is_active=True, user__groups__name="Inspector"
    ).exclude(user__groups__name__in=["Administrator", "Safety Manager"]).distinct()


def deny_checklist_filler(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.is_authenticated and is_checklist_filler(request.user):
            raise PermissionDenied("این بخش در فضای کاری مسئول تکمیل چک‌لیست در دسترس نیست.")
        return view(request, *args, **kwargs)
    return wrapped


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


def inspection_is_delegatable(inspection):
    if inspection.review_state in [Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED]:
        return inspection.status != Inspection.Status.CANCELLED
    return (
        inspection.review_state == Inspection.ReviewState.APPROVED
        and inspection.status == Inspection.Status.COMPLETED
        and not inspection.equipment.archived
        and inspection.template.active
    )


@login_required
def dashboard(request):
    if is_checklist_filler(request.user):
        today = timezone.localdate()
        inspections = Inspection.objects.filter(inspector=request.user).select_related("equipment", "template").order_by("due_date")
        assigned = inspections.filter(review_state__in=[Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED])
        findings = Finding.objects.filter(Q(assigned_user=request.user) | Q(assigned_person__user=request.user)).exclude(
            status=Finding.Status.CLOSED
        ).select_related("equipment", "inspection", "assigned_person").order_by("due_date", "-created_at")
        return render(request, "core/filler_dashboard.html", {
            "assigned_inspections": assigned,
            "submitted_inspections": inspections.filter(review_state=Inspection.ReviewState.SUBMITTED),
            "approved_inspections": inspections.filter(review_state=Inspection.ReviewState.APPROVED).order_by("-reviewed_at")[:5],
            "approved_inspection_count": inspections.filter(review_state=Inspection.ReviewState.APPROVED).count(),
            "overdue_inspection_count": assigned.filter(due_date__lt=today).count(),
            "due_soon_inspection_count": assigned.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
            "returned_inspection_count": inspections.filter(review_state=Inspection.ReviewState.RETURNED).count(),
            "findings": findings[:6], "open_finding_count": findings.count(),
            "overdue_finding_count": findings.filter(due_date__lt=today).count(),
            "today": today,
            "person": Person.objects.filter(user=request.user).first(),
        })
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
    scheduled = inspections.filter(
        equipment_id__in=ids,
        status__in=[Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS],
        review_state__in=[Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED],
    )
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
    approved_inspections = scoped_inspections.filter(review_state=Inspection.ReviewState.APPROVED)
    pending_review_total = scoped_inspections.filter(review_state=Inspection.ReviewState.SUBMITTED).count()
    outcome_counts = dict(
        approved_inspections.filter(
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
        for row in approved_inspections.filter(
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
        "can_manage": can_manage(request.user),
        "equipment_total": equipment.count(), "by_type": by_type,
        "available_total": equipment.filter(status=Equipment.Status.ACTIVE).exclude(findings__blocks_operation=True, findings__status__in=[Finding.Status.OPEN, Finding.Status.PROGRESS, Finding.Status.VERIFY]).distinct().count(),
        "stopped_total": equipment.filter(Q(status__in=[Equipment.Status.STOPPED, Equipment.Status.SERVICE]) | Q(findings__blocks_operation=True, findings__status__in=[Finding.Status.OPEN, Finding.Status.PROGRESS, Finding.Status.VERIFY])).distinct().count(),
        "uninspected_total": equipment.exclude(id__in=Inspection.objects.filter(status=Inspection.Status.COMPLETED, review_state=Inspection.ReviewState.APPROVED, outcome__in=[Inspection.Outcome.PASS, Inspection.Outcome.CONDITIONAL]).values("equipment_id")).count(),
        "pending_review_total": pending_review_total,
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
        "recent": Inspection.objects.filter(status=Inspection.Status.COMPLETED, review_state=Inspection.ReviewState.APPROVED).select_related("equipment", "inspector").order_by("-completed_at")[:6],
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


@deny_checklist_filler
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


@deny_checklist_filler
@login_required
def equipment_detail(request, pk):
    item = get_object_or_404(Equipment.objects.select_related("equipment_type", "area", "department"), pk=pk)
    active_today = timezone.localdate()
    documents = item.documents.select_related("category").filter(superseded_by__isnull=True)
    sheet_fields = EQUIPMENT_SHEET_PROFILES.get(item.equipment_type.name, set())
    checklist = ChecklistTemplate.objects.filter(equipment_type=item.equipment_type, active=True, name__startswith="چک‌لیست ایمنی پیشنهادی").prefetch_related("items").first()
    checks = list(checklist.items.all()) if checklist else []
    latest_inspection = item.inspections.filter(
        status=Inspection.Status.COMPLETED,
        review_state=Inspection.ReviewState.APPROVED,
    ).order_by("-completed_at", "-pk").first()
    pending_inspection = item.inspections.filter(
        review_state=Inspection.ReviewState.SUBMITTED,
    ).order_by("-submitted_at", "-pk").first()
    return render(request, "core/equipment_detail.html", {
        "item": item,
        "sheet_fields": sheet_fields,
        "equipment_checklist": checklist,
        "checklist_items": checks,
        "checklist_critical_count": sum(1 for check in checks if check.critical),
        "latest_inspection": latest_inspection,
        "pending_inspection": pending_inspection,
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


@deny_checklist_filler
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
            User = get_user_model()
            if form.cleaned_data.get("create_account"):
                user = User.objects.create_user(
                    username=form.cleaned_data["account_username"].strip(),
                    first_name=person.full_name[:150],
                    email=person.email,
                    password=secrets.token_urlsafe(40),
                    is_active=bool(form.cleaned_data.get("account_active") and person.active),
                )
                inspector_group, _ = Group.objects.get_or_create(name="Inspector")
                user.groups.add(inspector_group)
                person.user = user
                person.save(update_fields=["user"])
                reset_form = PasswordResetForm({"email": person.email})
                if reset_form.is_valid():
                    try:
                        reset_form.save(request=request, use_https=request.is_secure(),
                                        email_template_name="registration/password_reset_email.html",
                                        subject_template_name="registration/password_reset_subject.txt")
                    except (OSError, smtplib.SMTPException):
                        messages.warning(request, "حساب ساخته شد؛ ارسال پیوند گذرواژه ناموفق بود. تنظیمات ایمیل سرور را بررسی کنید تا فرد بتواند گذرواژه خود را تنظیم کند.")
                    else:
                        messages.success(request, "حساب ساخته شد و پیوند تنظیم گذرواژه برای رایانامه فرد ارسال شد.")
                else:
                    messages.warning(request, "حساب ساخته شد؛ برای ارسال پیوند گذرواژه، رایانامه کاربر را بررسی کنید.")
            elif form.cleaned_data.get("account_user"):
                person.user = form.cleaned_data["account_user"]
                person.user.username = person.employee_code.strip().upper()
                person.user.first_name = person.full_name[:150]
                person.user.email = person.email
                person.user.is_active = bool(form.cleaned_data.get("account_active") and person.active)
                person.user.save(update_fields=["username", "first_name", "email", "is_active"])
                inspector_group, _ = Group.objects.get_or_create(name="Inspector")
                person.user.groups.add(inspector_group)
                person.save(update_fields=["user"])
            elif obj and obj.user_id and not form.cleaned_data.get("account_user"):
                obj.user.groups.remove(*obj.user.groups.filter(name="Inspector"))
                person.user = None
                person.save(update_fields=["user"])
            record_event(request.user, "ویرایش شخص" if obj else "ثبت شخص", person)
            messages.success(request, "اطلاعات فرد و جایگاه سازمانی ذخیره شد.")
            if request.GET.get("next") == "organization":
                return redirect("organization_chart")
            return redirect("person_detail", pk=person.pk)
    return render(request, "core/form.html", {"form": form, "title": "ویرایش مشخصات" if obj else "ثبت فرد", "back_url": "people_list", "submit_label": "ذخیره"})


@deny_checklist_filler
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


@deny_checklist_filler
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


@deny_checklist_filler
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


@require_manager
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


@deny_checklist_filler
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
    qs = Inspection.objects.select_related("equipment", "template", "inspector", "inspector__person_profile")
    if is_checklist_filler(request.user):
        qs = qs.filter(inspector=request.user)
    status = request.GET.get("status", "")
    if status in Inspection.Status.values: qs = qs.filter(status=status)
    review_state = request.GET.get("review_state", "")
    if review_state in Inspection.ReviewState.values:
        qs = qs.filter(review_state=review_state)
    if request.GET.get("overdue") == "1": qs = qs.filter(status__in=[Inspection.Status.SCHEDULED, Inspection.Status.PROGRESS], due_date__lt=timezone.localdate())
    for inspection in qs:
        inspection.can_delegate = inspection_is_delegatable(inspection)
    today = timezone.localdate()
    return render(request, "core/inspection_list.html", {
        "inspections": qs, "selected_status": status, "selected_review_state": review_state,
        "review_states": Inspection.ReviewState.choices, "today": today,
        "can_manage": can_manage(request.user),
        "delegate_form": InspectionDelegationForm(initial={"due_date": today}) if can_manage(request.user) else None,
        "delegateable_ids": [inspection.pk for inspection in qs if inspection.can_delegate],
    })


@require_manager
@require_POST
def inspection_delegate(request):
    raw_ids = request.POST.getlist("inspection_ids")
    try:
        selected_ids = list(dict.fromkeys(int(value) for value in raw_ids))
    except (TypeError, ValueError):
        selected_ids = []
    form = InspectionDelegationForm(request.POST)
    if not selected_ids:
        messages.error(request, "ابتدا یک یا چند چک‌لیست قابل واگذاری را انتخاب کنید.")
        return redirect("inspection_list")
    if not form.is_valid():
        messages.error(request, "مسئول یا مهلت واگذاری معتبر نیست؛ مقادیر را بررسی کنید.")
        return redirect("inspection_list")

    reassignable_states = [Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED]
    with transaction.atomic():
        inspections = list(Inspection.objects.select_for_update().filter(pk__in=selected_ids).select_related("equipment", "template", "inspector"))
        if len(inspections) != len(selected_ids):
            messages.error(request, "برخی از چک‌لیست‌های انتخاب‌شده پیدا نشدند؛ فهرست را تازه کنید.")
            return redirect("inspection_list")
        if any(not inspection_is_delegatable(item) for item in inspections):
            messages.error(request, "چک‌لیست‌های در انتظار بررسی یا لغوشده قابل واگذاری نیستند؛ ابتدا وضعیت آن‌ها را تعیین کنید.")
            return redirect("inspection_list")

        assignee = form.cleaned_data["inspector"]
        due_date = form.cleaned_data["due_date"]
        instructions = form.cleaned_data["instructions"].strip()
        reassigned_count = 0
        created_count = 0
        for source in inspections:
            if source.review_state in reassignable_states:
                old_inspector, old_due_date = source.inspector, source.due_date
                source.inspector = assignee
                source.due_date = due_date
                if instructions:
                    source.instructions = instructions
                source.save(update_fields=["inspector", "due_date", "instructions"])
                details = f"{old_inspector.username} → {assignee.username}; {old_due_date.isoformat()} → {due_date.isoformat()}"
                record_event(request.user, "واگذاری مجدد چک‌لیست", source, details)
                reassigned_count += 1
                continue

            snapshot = source.template_snapshot or list(source.template.items.values("id", "section", "description", "critical", "weight"))
            delegated = Inspection(
                equipment=source.equipment,
                template=source.template,
                inspector=assignee,
                due_date=due_date,
                status=Inspection.Status.SCHEDULED,
                review_state=Inspection.ReviewState.ASSIGNED,
                instructions=instructions or source.instructions,
                template_snapshot=[dict(item) for item in snapshot],
                threshold_snapshot=source.threshold_snapshot,
            )
            delegated.full_clean()
            delegated.save()
            record_event(request.user, "واگذاری مجدد چک‌لیست", delegated,
                         f"برنامه تازه بر پایه بازرسی تأییدشده {source.pk} برای {assignee.username}")
            created_count += 1

    messages.success(request, f"واگذاری انجام شد: {reassigned_count} چک‌لیست منتقل و {created_count} برنامه تازه از سوابق تأییدشده ساخته شد.")
    return redirect("inspection_list")


@login_required
def checklist_workspace(request):
    if not is_checklist_filler(request.user):
        raise PermissionDenied("این بخش برای کاربران مسئول تکمیل چک‌لیست است.")
    inspections = Inspection.objects.filter(inspector=request.user).select_related("equipment", "template")
    state = request.GET.get("state", "")
    deadline = request.GET.get("deadline", "")
    query = request.GET.get("q", "").strip()
    if state in Inspection.ReviewState.values:
        inspections = inspections.filter(review_state=state)
    today = timezone.localdate()
    if deadline == "overdue":
        inspections = inspections.filter(due_date__lt=today).exclude(review_state__in=[Inspection.ReviewState.APPROVED, Inspection.ReviewState.CANCELLED])
    elif deadline == "soon":
        inspections = inspections.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).exclude(review_state__in=[Inspection.ReviewState.APPROVED, Inspection.ReviewState.CANCELLED])
    if query:
        inspections = inspections.filter(Q(equipment__name__icontains=query) | Q(equipment__asset_code__icontains=query) | Q(template__name__icontains=query))
    return render(request, "core/checklist_workspace.html", {
        "inspections": inspections.order_by("due_date", "-created_at"),
        "editable_states": [Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED],
        "review_states": Inspection.ReviewState.choices, "selected_state": state, "selected_deadline": deadline,
        "query": query, "today": today,
    })


@require_manager
def inspection_review_list(request):
    inspections = Inspection.objects.filter(review_state=Inspection.ReviewState.SUBMITTED).select_related(
        "equipment", "template", "inspector"
    ).order_by("submitted_at", "due_date")
    return render(request, "core/inspection_review_list.html", {"inspections": inspections})


@require_manager
def inspection_new(request):
    filler = checklist_assignees().select_related("user").first()
    initial = {"due_date": timezone.localdate()}
    if filler:
        initial["inspector"] = filler.user_id
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
    if is_checklist_filler(request.user) and inspection.inspector_id != request.user.pk:
        raise PermissionDenied("بازرسی‌های دیگر بازرس‌ها برای شما در دسترس نیست.")
    return render(request, "core/inspection_detail.html", inspection_detail_context(request, inspection))


def inspection_detail_context(request, inspection, reassignment_form=None):
    items = inspection.template_snapshot or list(inspection.template.items.values("id", "section", "description", "critical", "weight"))
    has_answer_post = request.method == "POST" and any(key.startswith("result_") for key in request.POST)
    saved = {response.item_id: response for response in inspection.responses.all()}
    draft = inspection.draft_data or {}
    for item in items:
        response = saved.get(item.get("id"))
        saved_draft = draft.get(str(item.get("id")), {})
        has_draft = str(item.get("id")) in draft
        item["saved_result"] = saved_draft.get("result", "") if has_draft else (response.result if response else "")
        item["saved_comment"] = saved_draft.get("comment", "") if has_draft else (response.comment if response else "")
        item["saved_measurement"] = saved_draft.get("measurement", "") if has_draft else (response.measurement if response else "")
        item["saved_assigned_person"] = saved_draft.get("assigned_person", "") if has_draft else (response.finding.assigned_person_id if response and hasattr(response, "finding") else "")
        item["saved_due_date"] = saved_draft.get("due_date", "") if has_draft else (response.finding.due_date.isoformat() if response and hasattr(response, "finding") and response.finding.due_date else "")
        if has_answer_post:
            item_id = str(item.get("id"))
            item["saved_result"] = request.POST.get(f"result_{item_id}", "")
            item["saved_comment"] = request.POST.get(f"comment_{item_id}", "")
            item["saved_measurement"] = request.POST.get(f"measurement_{item_id}", "")
            item["saved_assigned_person"] = request.POST.get(f"assigned_{item_id}", "")
            item["saved_due_date"] = request.POST.get(f"due_{item_id}", "")
    can_fill = (can_manage(request.user) or is_checklist_filler(request.user)) and inspection.inspector_id == request.user.pk and inspection.review_state in [
        Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED
    ] and inspection.status != Inspection.Status.CANCELLED
    can_manager_edit = can_manage(request.user) and inspection.review_state == Inspection.ReviewState.SUBMITTED
    audit_events = AuditLog.objects.filter(entity=str(inspection._meta.verbose_name), entity_id=inspection.pk).select_related("actor")[:12]
    return {
        "inspection": inspection, "items": items, "people": checklist_assignees(),
        "today": timezone.localdate(), "can_complete": can_fill or can_manager_edit,
        "can_fill": can_fill, "can_manager_edit": can_manager_edit,
        "can_review": can_manage(request.user) and inspection.review_state == Inspection.ReviewState.SUBMITTED,
        "can_manage": can_manage(request.user),
        "is_checklist_filler": is_checklist_filler(request.user),
        "has_answer_post": has_answer_post,
        "posted_meter_value": request.POST.get("meter_value", "") if has_answer_post else inspection.meter_value,
        "posted_notes": request.POST.get("notes", "") if has_answer_post else inspection.notes,
        "posted_review_note": request.POST.get("review_note", inspection.review_note) if request.method == "POST" else inspection.review_note,
        "reassignment_form": reassignment_form or (InspectionReassignmentForm(instance=inspection) if can_manage(request.user) and inspection.review_state in [Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED] else None),
        "audit_events": audit_events,
    }


@require_manager
@require_POST
def inspection_reassign(request, pk):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    with transaction.atomic():
        inspection = get_object_or_404(Inspection.objects.select_for_update().select_related("inspector"), pk=pk)
        if inspection.review_state not in [Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED]:
            if is_ajax:
                return JsonResponse({"ok": False, "message": "این چک‌لیست در وضعیت قابل واگذاری مجدد نیست."}, status=409)
            messages.error(request, "برای حفظ سابقه، چک‌لیست پس از ارسال یا تأیید قابل واگذاری مجدد نیست.")
            return redirect("inspection_detail", pk=pk)
        old_inspector, old_due_date = inspection.inspector, inspection.due_date
        form = InspectionReassignmentForm(request.POST, instance=inspection)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.save(update_fields=["inspector", "due_date"])
            details = f"{old_inspector.username} → {updated.inspector.username}; {old_due_date.isoformat()} → {updated.due_date.isoformat()}"
            record_event(request.user, "واگذاری مجدد چک‌لیست", updated, details)
            success_message = "مسئول و موعد چک‌لیست به‌روزرسانی شد؛ پیش‌نویس و سابقه حفظ شد."
            if is_ajax:
                person = Person.objects.filter(user=updated.inspector).first()
                return JsonResponse({
                    "ok": True, "message": success_message,
                    "assignee": f"{person.full_name} · {updated.inspector.username}" if person else updated.inspector.get_full_name() or updated.inspector.username,
                    "due_date": updated.due_date.isoformat(),
                })
        else:
            if is_ajax:
                return JsonResponse({"ok": False, "message": "نام مسئول یا موعد معتبر نیست.", "errors": form.errors.get_json_data()}, status=400)
            return render(request, "core/inspection_detail.html", inspection_detail_context(request, inspection, form), status=400)
    return redirect("inspection_detail", pk=pk)


def _get_posted_answers(request, snapshot, *, allow_partial=False):
    failures, answers = [], []
    for item in snapshot:
        item_id = str(item.get("id", ""))
        response_value = request.POST.get(f"result_{item_id}", "").strip()
        comment = request.POST.get(f"comment_{item_id}", "").strip()[:500]
        measurement = request.POST.get(f"measurement_{item_id}", "").strip()[:80]
        person_id = request.POST.get(f"assigned_{item_id}", "").strip()
        due_raw = request.POST.get(f"due_{item_id}", "").strip()
        if allow_partial and not response_value:
            answers.append((item, "", comment, measurement, None, None))
            continue
        if response_value not in ["pass", "fail", "na"]:
            return None, "برای همه موارد چک‌لیست یک نتیجه انتخاب کنید."
        if allow_partial:
            assigned_person = checklist_assignees().filter(pk=person_id).first() if person_id.isdigit() else None
            try:
                due_date = parse_date(due_raw) if due_raw else None
            except ValueError:
                due_date = None
            answers.append((item, response_value, comment, measurement, assigned_person, due_date))
            continue
        if response_value == "na" and not comment:
            return None, "برای موارد غیرقابل‌اعمال توضیح بنویسید."
        if response_value == "fail" and not comment:
            return None, "شرح نقص برای موارد مردود الزامی است."
        assigned_person = checklist_assignees().filter(pk=person_id).first() if person_id.isdigit() else None
        try:
            due_date = parse_date(due_raw) if due_raw else None
        except ValueError:
            due_date = None
        if response_value == "fail":
            if not assigned_person or not due_date:
                return None, "برای هر نقص، نام مسئول و مهلت معتبر اصلاح را وارد کنید."
            failures.append((item, comment, assigned_person, due_date))
        answers.append((item, response_value, comment, measurement, assigned_person, due_date))
    applicable_weight = sum(item.get("weight", 1) for item, result, *_ in answers if result and result != "na")
    if not allow_partial and not applicable_weight:
        return None, "حداقل یک مورد باید قابل‌اعمال باشد."
    return {"answers": answers, "failures": failures}, ""


def _save_inspection_answers(inspection, answers):
    responses = {}
    for item, result, comment, measurement, assigned_person, due_date in answers:
        if not result:
            continue
        item_id = item.get("id")
        response = InspectionResponse.objects.filter(inspection=inspection, item_id=item_id).first()
        if response is None:
            response = InspectionResponse(inspection=inspection, item_id=item_id)
        response.item_text = item["description"]
        response.critical = item.get("critical", False)
        response.weight = item.get("weight", 1)
        response.result = result
        response.comment = comment
        response.measurement = measurement
        response.save()
        responses[str(item_id)] = response
    return responses


def _create_or_update_inspection_findings(inspection, parsed, responses):
    for item, comment, person, due_date in parsed["failures"]:
        response = responses[str(item.get("id"))]
        finding = Finding.objects.filter(source_response=response).first()
        defaults = {
            "equipment": inspection.equipment, "inspection": inspection, "description": f"{item['description']}: {comment}",
            "severity": Finding.Severity.CRITICAL if item.get("critical") else Finding.Severity.MEDIUM,
            "blocks_operation": bool(item.get("critical")), "assigned_person": person,
            "assigned_user": person.user if person.user_id else None, "assigned_to": person.full_name[:120],
            "due_date": due_date,
        }
        if finding:
            for field, value in defaults.items():
                setattr(finding, field, value)
            if finding.status == Finding.Status.CLOSED:
                finding.status = Finding.Status.OPEN
                finding.resolution = ""
                finding.verified_by = None
                finding.verified_at = None
            finding.save()
        else:
            Finding.objects.create(source_response=response, **defaults)


def create_next_inspection(inspection):
    template = inspection.template
    if inspection.outcome == Inspection.Outcome.FAIL or not (template.interval_months or template.interval_days):
        return
    next_date = (add_months(timezone.localdate(), template.interval_months) if template.interval_months
                 else timezone.localdate() + timedelta(days=template.interval_days))
    exists = Inspection.objects.filter(equipment=inspection.equipment, template=template, inspector=inspection.inspector,
                                       status=Inspection.Status.SCHEDULED, due_date=next_date).exists()
    if not exists:
        Inspection.objects.create(equipment=inspection.equipment, template=template, inspector=inspection.inspector,
                                  due_date=next_date, notes="بازرسی دوره‌ای بعدی",
                                  template_snapshot=list(template.items.values("id", "section", "description", "critical", "weight")),
                                  threshold_snapshot=template.rejection_threshold)


@require_edit
@require_POST
def inspection_complete(request, pk):
    with transaction.atomic():
        inspection = get_object_or_404(Inspection.objects.select_for_update().select_related("template", "equipment", "inspector"), pk=pk)
        action = request.POST.get("action", "submit")
        is_owner = inspection.inspector_id == request.user.pk
        if not can_manage(request.user) and (not is_checklist_filler(request.user) or not is_owner):
            raise PermissionDenied("فقط بازرس تخصیص‌یافته می‌تواند این بازرسی را ثبت کند.")
        if action == "manager_save":
            if not can_manage(request.user) or inspection.review_state != Inspection.ReviewState.SUBMITTED:
                raise PermissionDenied("ویرایش پاسخ‌های ارسالی برای مدیر مجاز است.")
        elif not can_manage(request.user) and inspection.review_state not in [Inspection.ReviewState.ASSIGNED, Inspection.ReviewState.DRAFT, Inspection.ReviewState.RETURNED]:
            messages.error(request, "این چک‌لیست در وضعیت قابل‌ویرایش نیست."); return redirect("inspection_detail", pk=pk)
        elif can_manage(request.user) and inspection.review_state in [Inspection.ReviewState.SUBMITTED, Inspection.ReviewState.APPROVED, Inspection.ReviewState.CANCELLED]:
            messages.error(request, "برای تغییر این سابقه، از بخش بازبینی مدیر استفاده کنید."); return redirect("inspection_detail", pk=pk)
        snapshot = inspection.template_snapshot or list(inspection.template.items.values("id", "section", "description", "critical", "weight"))
        if not snapshot:
            messages.error(request, "چک‌لیست خالی قابل نهایی‌کردن نیست."); return redirect("inspection_detail", pk=pk)
        if action == "save_draft":
            if not is_owner or not is_checklist_filler(request.user):
                raise PermissionDenied("ذخیره پیش‌نویس فقط برای بازرس تخصیص‌یافته مجاز است.")
            parsed, error = _get_posted_answers(request, snapshot, allow_partial=True)
            if error:
                messages.error(request, error); return redirect("inspection_detail", pk=pk)
            inspection.draft_data = {
                str(item.get("id")): {"result": result, "comment": comment, "measurement": measurement,
                                       "assigned_person": person.pk if person else "", "due_date": due_date.isoformat() if due_date else ""}
                for item, result, comment, measurement, person, due_date in parsed["answers"]
            }
            inspection.notes = request.POST.get("notes", "")[:3000]
            inspection.status = Inspection.Status.PROGRESS
            inspection.review_state = Inspection.ReviewState.DRAFT
            inspection.save(update_fields=["draft_data", "notes", "status", "review_state"])
            record_event(request.user, "ذخیره پیش‌نویس چک‌لیست", inspection)
            messages.success(request, "پیش‌نویس چک‌لیست ذخیره شد.")
            return redirect("inspection_detail", pk=pk)
        parsed, error = _get_posted_answers(request, snapshot)
        if error:
            messages.error(request, error)
            return render(request, "core/inspection_detail.html", inspection_detail_context(request, inspection), status=400)
        answers = parsed["answers"]
        previous_outcome = inspection.outcome
        previous_responses = {
            str(response.item_id): response
            for response in inspection.responses.all()
        } if action == "manager_save" else {}
        meter = request.POST.get("meter_value", "").strip()
        if meter and (not meter.isdigit() or int(meter) < 0):
            messages.error(request, "عدد کارکرد معتبر وارد کنید.")
            return render(request, "core/inspection_detail.html", inspection_detail_context(request, inspection), status=400)
        applicable_weight = sum(item.get("weight", 1) for item, result, *_ in answers if result != "na")
        if not applicable_weight:
            messages.error(request, "حداقل یک مورد باید قابل‌اعمال باشد.")
            return render(request, "core/inspection_detail.html", inspection_detail_context(request, inspection), status=400)
        failed_weight = sum(item.get("weight", 1) for item, *_ in parsed["failures"])
        percent = Decimal(failed_weight) * 100 / Decimal(applicable_weight)
        threshold = inspection.threshold_snapshot if inspection.template_snapshot else inspection.template.rejection_threshold
        responses = _save_inspection_answers(inspection, answers)
        inspection.failed_weight_percent = percent
        inspection.threshold_snapshot = threshold
        inspection.outcome = (Inspection.Outcome.FAIL if any(item.get("critical") for item, *_ in parsed["failures"]) or percent >= threshold
                              else Inspection.Outcome.CONDITIONAL if parsed["failures"]
                              else Inspection.Outcome.PASS)
        inspection.status = Inspection.Status.COMPLETED
        inspection.completed_at = timezone.now()
        if action != "manager_save":
            inspection.review_state = Inspection.ReviewState.SUBMITTED
            inspection.submitted_at = timezone.now()
            inspection.reviewed_by = None
            inspection.reviewed_at = None
            inspection.review_note = ""
        inspection.meter_value = int(meter) if meter else None
        inspection.notes = request.POST.get("notes", "")[:3000]
        inspection.template_snapshot = snapshot
        inspection.draft_data = {}
        inspection.save()
        _create_or_update_inspection_findings(inspection, parsed, responses)
        if action == "manager_save":
            response_changes = []
            changed_labels = {
                "result": "نتیجه", "comment": "توضیح", "measurement": "اندازه‌گیری",
                "assigned_person": "مسئول نقص", "due_date": "مهلت نقص",
            }
            for item, result, comment, measurement, assigned_person, due_date in answers:
                old = previous_responses.get(str(item.get("id")))
                if old is None:
                    changed_fields = list(changed_labels.values())
                else:
                    new_values = {
                        "result": result, "comment": comment, "measurement": measurement,
                        "assigned_person": assigned_person.pk if assigned_person else None,
                        "due_date": due_date.isoformat() if due_date else None,
                    }
                    old_values = {
                        "result": old.result, "comment": old.comment, "measurement": old.measurement,
                        "assigned_person": old.finding.assigned_person_id if hasattr(old, "finding") else None,
                        "due_date": old.finding.due_date.isoformat() if hasattr(old, "finding") and old.finding.due_date else None,
                    }
                    changed_fields = [changed_labels[key] for key in changed_labels if old_values[key] != new_values[key]]
                if changed_fields:
                    response_changes.append({"item": item.get("description", "")[:100], "fields": changed_fields})
            change_summary = {
                "outcome": {"from": previous_outcome, "to": inspection.outcome},
                "changed_responses": response_changes,
            }
            record_event(request.user, "ویرایش پاسخ‌های چک‌لیست", inspection, json.dumps(change_summary, ensure_ascii=False))
        else:
            record_event(request.user, "ارسال چک‌لیست برای بازبینی", inspection, inspection.get_outcome_display())
    messages.success(request, "تغییرات بررسی و ذخیره شد." if action == "manager_save" else "چک‌لیست برای بررسی مدیر ارسال شد.")
    return redirect("inspection_detail", pk=pk)


@require_manager
@require_POST
def inspection_review_action(request, pk):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    message = ""
    succeeded = False
    with transaction.atomic():
        inspection = get_object_or_404(Inspection.objects.select_for_update().select_related("template"), pk=pk)
        action = request.POST.get("action")
        if action == "approve" and inspection.review_state == Inspection.ReviewState.SUBMITTED:
            inspection.review_state = Inspection.ReviewState.APPROVED
            inspection.reviewed_by = request.user
            inspection.reviewed_at = timezone.now()
            inspection.review_note = request.POST.get("review_note", "")[:2000]
            inspection.save(update_fields=["review_state", "reviewed_by", "reviewed_at", "review_note"])
            create_next_inspection(inspection)
            record_event(request.user, "تأیید چک‌لیست", inspection, inspection.get_outcome_display())
            message, succeeded = "چک‌لیست تأیید شد.", True
        elif action == "return" and inspection.review_state == Inspection.ReviewState.SUBMITTED:
            note = request.POST.get("review_note", "").strip()
            if not note:
                if is_ajax:
                    return JsonResponse({"ok": False, "message": "برای بازگرداندن چک‌لیست، دلیل اصلاح را بنویسید."}, status=400)
                messages.error(request, "برای بازگرداندن چک‌لیست، دلیل اصلاح را بنویسید.")
                return render(request, "core/inspection_detail.html", inspection_detail_context(request, inspection), status=400)
            inspection.review_state = Inspection.ReviewState.RETURNED
            inspection.status = Inspection.Status.PROGRESS
            inspection.reviewed_by = request.user
            inspection.reviewed_at = timezone.now()
            inspection.review_note = note[:2000]
            inspection.save(update_fields=["review_state", "status", "reviewed_by", "reviewed_at", "review_note"])
            record_event(request.user, "بازگرداندن چک‌لیست برای اصلاح", inspection, note)
            message, succeeded = "چک‌لیست برای اصلاح به مسئول آن بازگردانده شد.", True
        elif action == "cancel" and inspection.review_state != Inspection.ReviewState.APPROVED:
            inspection.review_state = Inspection.ReviewState.CANCELLED
            inspection.status = Inspection.Status.CANCELLED
            inspection.reviewed_by = request.user
            inspection.reviewed_at = timezone.now()
            inspection.review_note = request.POST.get("review_note", "")[:2000]
            inspection.save(update_fields=["review_state", "status", "reviewed_by", "reviewed_at", "review_note"])
            record_event(request.user, "لغو چک‌لیست", inspection, inspection.review_note)
            message, succeeded = "چک‌لیست لغو شد و سابقه آن حفظ شد.", True
        else:
            message = "این تغییر با وضعیت فعلی چک‌لیست سازگار نیست."
    if is_ajax:
        return JsonResponse({
            "ok": succeeded, "message": message,
            "review_state": inspection.review_state,
            "review_state_label": inspection.get_review_state_display(),
        }, status=200 if succeeded else 400)
    (messages.success if succeeded else messages.error)(request, message)
    return redirect("inspection_detail", pk=pk)


def filtered_findings(params):
    qs = Finding.objects.select_related("equipment", "inspection", "assigned_person", "assigned_user")
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
    if is_checklist_filler(request.user):
        return redirect("my_findings")
    return render(request, "core/finding_list.html", {
        "findings": filtered_findings(request.GET), "filters": request.GET,
        "selected_status": request.GET.get("status", "active"),
        "equipment_options": Equipment.objects.filter(findings__isnull=False).distinct().order_by("asset_code"),
        "equipment_types": EquipmentType.objects.filter(equipment__findings__isnull=False).distinct(),
        "areas": Area.objects.all(), "drivers": Person.objects.filter(assignments__isnull=False).distinct(),
        "assignees": Person.objects.filter(assigned_findings__isnull=False).distinct(),
        "people": checklist_assignees(), "statuses": Finding.Status.choices,
        "severities": Finding.Severity.choices, "equipment_statuses": Equipment.Status.choices,
        "can_edit": can_edit(request.user), "can_manage": can_manage(request.user),
    })


@login_required
def my_findings(request):
    if not is_checklist_filler(request.user):
        raise PermissionDenied("این بخش برای کاربران مسئول پیگیری نقص‌ها است.")
    findings = Finding.objects.filter(Q(assigned_user=request.user) | Q(assigned_person__user=request.user)).exclude(
        status=Finding.Status.CLOSED
    ).select_related("equipment", "inspection", "assigned_person", "assigned_user").order_by("due_date", "-created_at")
    return render(request, "core/my_findings.html", {
        "findings": findings, "people": checklist_assignees(),
        "can_edit": True, "can_manage": False, "my_findings": True, "today": timezone.localdate(),
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
                "finding": finding, "people": checklist_assignees(),
                "can_edit": can_edit(request.user), "can_manage": can_manage(request.user),
                "my_findings": is_checklist_filler(request.user),
                "today": timezone.localdate(),
            }, request=request)
        return JsonResponse(payload, status=400 if error else 200)
    (messages.error if error else messages.success)(request, message)
    target = reverse("finding_list")
    return redirect(f"{target}?{request.GET.urlencode()}" if request.GET else target)


@require_edit
@require_POST
def finding_close(request, pk):
    with transaction.atomic():
        finding = get_object_or_404(Finding.objects.select_for_update().select_related("equipment", "assigned_person", "assigned_user"), pk=pk)
        action = request.POST.get("action", "")
        if finding.status == Finding.Status.CLOSED:
            return finding_action_response(request, finding, "این اقدام قبلاً بسته شده است.", error=True)
        if action == "assign":
            if not can_manage(request.user):
                raise PermissionDenied("تخصیص مسئول نقص فقط برای مدیر مجاز است.")
            person_id = request.POST.get("assigned_person", "").strip()
            assigned_person = checklist_assignees().filter(pk=person_id).first() if person_id.isdigit() else None
            try:
                due_date = parse_date(request.POST.get("due_date", "").strip())
            except ValueError:
                due_date = None
            if not assigned_person or not due_date:
                return finding_action_response(request, finding, "نام مسئول و مهلت معتبر اصلاح الزامی است.", error=True)
            finding.assigned_person, finding.assigned_user = assigned_person, assigned_person.user
            finding.assigned_to, finding.due_date = assigned_person.full_name[:120], due_date
            finding.save(update_fields=["assigned_person", "assigned_user", "assigned_to", "due_date"])
            record_event(request.user, "تخصیص اقدام اصلاحی", finding, assigned_person.full_name)
            return finding_action_response(request, finding, "مسئول و مهلت اصلاح ثبت شد.")
        owns_finding = finding.assigned_user_id == request.user.pk or (finding.assigned_person_id and finding.assigned_person.user_id == request.user.pk)
        if not can_manage(request.user) and (not is_checklist_filler(request.user) or not owns_finding):
            raise PermissionDenied("فقط مدیر یا مسئول تعیین‌شده می‌تواند وضعیت این نقص را تغییر دهد.")
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
            if finding.blocks_operation and not finding.equipment.inspections.filter(
                status=Inspection.Status.COMPLETED,
                review_state=Inspection.ReviewState.APPROVED,
                outcome__in=[Inspection.Outcome.PASS, Inspection.Outcome.CONDITIONAL],
                completed_at__gt=finding.created_at,
            ).exists():
                return finding_action_response(request, finding, "پیش از بازگشت تجهیز بحرانی به سرویس، بازرسی مجدد با نتیجه قبول لازم است.", error=True)
            finding.status = Finding.Status.CLOSED; finding.verified_by = request.user; finding.verified_at = timezone.now()
        finding.save()
    record_event(request.user, "به‌روزرسانی اقدام اصلاحی", finding, finding.get_status_display())
    return finding_action_response(request, finding, "وضعیت اقدام اصلاحی ثبت شد.")


@deny_checklist_filler
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


@deny_checklist_filler
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


@deny_checklist_filler
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


@deny_checklist_filler
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
