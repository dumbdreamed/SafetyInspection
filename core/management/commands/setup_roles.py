from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "ایجاد گروه‌های نقش و سطح دسترسی سامانه."

    def handle(self, *args, **options):
        business = Permission.objects.filter(content_type__app_label="core")
        permitted_audit = business.exclude(codename__regex=r"^(add|change|delete)_auditlog$")
        administrator, _ = Group.objects.get_or_create(name="Administrator")
        administrator.permissions.set(Permission.objects.filter(
            Q(content_type__app_label="core") | Q(content_type__app_label="auth", codename__in=[
                "view_user", "add_user", "change_user", "view_group", "add_group", "change_group"
            ])
        ).exclude(codename__regex=r"^(add|change|delete)_auditlog$"))
        manager, _ = Group.objects.get_or_create(name="Safety Manager")
        manager.permissions.set(permitted_audit.filter(codename__regex=r"^(view|add|change)_"))
        inspector, _ = Group.objects.get_or_create(name="Inspector")
        inspector.permissions.set(business.filter(codename__in=[
            "view_equipment", "view_equipmenttype", "view_area", "view_department",
            "view_assignment", "view_inspection", "view_checklisttemplate", "view_checklistitem",
            "view_finding", "view_maintenancerecord"
        ]))
        viewer, _ = Group.objects.get_or_create(name="Viewer")
        viewer.permissions.set(business.filter(codename__regex=r"^view_").exclude(codename__in=[
            "view_person", "view_qualification", "view_qualificationtype", "view_document",
            "view_documentcategory", "view_assignment", "view_auditlog"
        ]))
        self.stdout.write(self.style.SUCCESS("نقش‌های Administrator، Safety Manager، Inspector و Viewer تنظیم شدند."))
