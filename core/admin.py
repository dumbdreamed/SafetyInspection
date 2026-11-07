from django.contrib import admin
from django.utils.html import format_html

from .models import (Area, Assignment, AuditLog, ChecklistItem, ChecklistTemplate, Department,
                    Document, DocumentCategory, Equipment, EquipmentType, Finding,
                    Inspection, InspectionResponse, MaintenanceRecord, OrganizationCluster, OrganizationPosition, Person,
                    Qualification, QualificationType, show_organization_chain)


class ItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "equipment_type", "rejection_threshold", "interval_months", "interval_days", "active")
    list_filter = ("active", "equipment_type")
    inlines = (ItemInline,)


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("asset_code", "name", "equipment_type", "area", "status", "archived")
    list_filter = ("equipment_type", "area", "status", "archived")
    search_fields = ("asset_code", "name", "serial_number", "plate")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("employee_code", "full_name", "employer", "department", "active")
    list_filter = ("active", "department")
    search_fields = ("employee_code", "full_name", "employer")


@admin.register(OrganizationPosition)
class OrganizationPositionAdmin(admin.ModelAdmin):
    list_display = ("person", "title", "level", "manager", "order")
    list_filter = ("level",)
    search_fields = ("person__full_name", "person__employee_code", "title")

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("person",) if obj else ()


@admin.register(OrganizationCluster)
class OrganizationClusterAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    filter_horizontal = ("members",)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        for position in form.instance.members.select_related("manager"):
            show_organization_chain(position)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "verification", "expires_on", "uploaded_by", "uploaded_at")
    list_filter = ("category", "verification", "expires_on")
    search_fields = ("title", "reference_number")
    exclude = ("file",)
    readonly_fields = ("uploaded_at",)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.groups.filter(name__in={"Administrator", "Safety Manager"}).exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.groups.filter(name__in={"Administrator", "Safety Manager"}).exists()


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "entity", "entity_id")
    list_filter = ("action", "entity")
    search_fields = ("details", "entity")
    readonly_fields = ("actor", "action", "entity", "entity_id", "details", "created_at")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("equipment", "template", "due_date", "status", "outcome", "inspector")
    list_filter = ("status", "outcome", "template")
    search_fields = ("equipment__asset_code", "equipment__name", "template__name")
    readonly_fields = ("completed_at", "template_snapshot")


admin.site.register([EquipmentType, Area, Department, QualificationType, Qualification, Assignment,
                     DocumentCategory, ChecklistItem, InspectionResponse, Finding, MaintenanceRecord])
admin.site.site_header = "مدیریت نگهبان ایمنی"
admin.site.site_title = "مدیریت سامانه"
admin.site.index_title = "مدیریت داده‌های سامانه بازرسی"
