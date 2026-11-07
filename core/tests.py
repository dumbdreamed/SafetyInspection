import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import AssignmentForm, DocumentForm
from .models import (Assignment, ChecklistItem, ChecklistTemplate, Document, DocumentCategory,
                     Equipment, EquipmentType, Finding, Inspection, InspectionResponse,
                     Person, Qualification, QualificationType, add_months)
from .persistence import backup_database, restore_database


User = get_user_model()


class DomainSetUpMixin:
    def make_user(self, username, group):
        user = User.objects.create_user(username, password="Example-safe-1234")
        role, _ = Group.objects.get_or_create(name=group)
        user.groups.add(role)
        return user

    def make_equipment(self, code="TR-001"):
        type_ = EquipmentType.objects.create(name="کامیون نمونه")
        return Equipment.objects.create(asset_code=code, name="کامیون حمل مواد", equipment_type=type_)


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AccessAndDocumentTests(DomainSetUpMixin, TestCase):
    def setUp(self):
        self.equipment = self.make_equipment()
        self.manager = self.make_user("safety-manager", "Safety Manager")
        self.viewer = self.make_user("read-only", "Viewer")
        self.category = DocumentCategory.objects.create(name="گواهی بیمه", expires=True)

    def test_viewer_can_read_inventory_but_cannot_change_it(self):
        client = Client()
        client.force_login(self.viewer)
        self.assertEqual(client.get(reverse("equipment_list")).status_code, 200)
        self.assertEqual(client.get(reverse("equipment_new")).status_code, 403)

    def test_document_content_is_checked_and_only_authorized_users_can_download(self):
        good = SimpleUploadedFile("insurance.pdf", b"%PDF-1.7\nexample", content_type="application/pdf")
        form = DocumentForm(data={"title": "بیمه کامیون", "category": self.category.pk,
                                  "equipment": self.equipment.pk, "verification": "verified"}, files={"file": good})
        self.assertTrue(form.is_valid(), form.errors)
        doc = form.save(commit=False)
        doc.uploaded_by = self.manager
        doc.save()

        viewer_client = Client(); viewer_client.force_login(self.viewer)
        self.assertEqual(viewer_client.get(reverse("document_download", args=[doc.pk])).status_code, 403)
        manager_client = Client(); manager_client.force_login(self.manager)
        response = manager_client.get(reverse("document_download", args=[doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.7\nexample")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_invalid_pdf_suffix_is_rejected(self):
        upload = SimpleUploadedFile("fake.pdf", b"<html>not a pdf</html>", content_type="application/pdf")
        form = DocumentForm(data={"title": "فایل نامعتبر", "category": self.category.pk,
                                  "equipment": self.equipment.pk}, files={"file": upload})
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_dashboard_counts_each_active_equipment_type_including_zero(self):
        EquipmentType.objects.create(name="جرثقیل نمونه")
        client = Client(); client.force_login(self.viewer)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        rows = {row["name"]: row["total"] for row in response.context["by_type"]}
        self.assertEqual(rows["کامیون نمونه"], 1)
        self.assertEqual(rows["جرثقیل نمونه"], 0)


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AssignmentAndInspectionTests(DomainSetUpMixin, TransactionTestCase):
    def setUp(self):
        self.equipment = self.make_equipment("CR-014")
        self.manager = self.make_user("manager-one", "Safety Manager")
        self.inspector = self.make_user("inspector-one", "Inspector")
        self.person = Person.objects.create(employee_code="OP-014", full_name="اپراتور نمونه", user=self.inspector)

    def test_required_verified_qualification_is_checked_on_assignment(self):
        required = QualificationType.objects.create(name="گواهی رانندگی", required_for_assignment=True)
        required.equipment_types.add(self.equipment.equipment_type)
        data = {"person": self.person.pk, "equipment": self.equipment.pk, "role": Assignment.Role.PRIMARY,
                "starts_on": date.today().isoformat(), "ends_on": "", "notes": ""}
        form = AssignmentForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("صلاحیت معتبر", str(form.errors))

        Qualification.objects.create(person=self.person, qualification_type=required, verified=True)
        form = AssignmentForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        assignment = form.save()
        self.assertEqual(assignment.person, self.person)

    def test_template_wording_is_snapshotted_when_scheduled(self):
        template = ChecklistTemplate.objects.create(name="چک‌لیست نمونه", equipment_type=self.equipment.equipment_type)
        item = ChecklistItem.objects.create(template=template, description="ترمزها", critical=True)
        schedule = Inspection.objects.create(equipment=self.equipment, template=template, inspector=self.inspector,
                                             due_date=date.today(), template_snapshot=[{"id": item.pk, "description": "ترمزها", "critical": True}])
        item.description = "ترمز جدید"; item.save()
        self.assertEqual(schedule.template_snapshot[0]["description"], "ترمزها")

    def test_critical_failure_stops_equipment_and_duplicate_submit_does_not_duplicate_records(self):
        template = ChecklistTemplate.objects.create(name="چک‌لیست کامیون", equipment_type=self.equipment.equipment_type)
        item = ChecklistItem.objects.create(template=template, description="ترمزها", critical=True)
        schedule = Inspection.objects.create(equipment=self.equipment, template=template, inspector=self.inspector,
                                             due_date=date.today(), template_snapshot=[{"id": item.pk, "description": item.description, "critical": True}])
        client = Client(); client.force_login(self.inspector)
        payload = {f"result_{item.pk}": "fail", f"comment_{item.pk}": "نقص در ترمز",
                   f"assigned_{item.pk}": str(self.person.pk), f"due_{item.pk}": (date.today() + timedelta(days=3)).isoformat()}
        response = client.post(reverse("inspection_complete", args=[schedule.pk]), payload)
        self.assertEqual(response.status_code, 302)
        schedule.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertEqual(schedule.outcome, Inspection.Outcome.FAIL)
        self.assertEqual(InspectionResponse.objects.filter(inspection=schedule).count(), 1)
        finding = Finding.objects.get(inspection=schedule)
        self.assertTrue(finding.blocks_operation)
        self.assertEqual(self.equipment.condition[0], "خارج از سرویس")
        client.post(reverse("inspection_complete", args=[schedule.pk]), payload)
        self.assertEqual(InspectionResponse.objects.filter(inspection=schedule).count(), 1)

    def test_critical_finding_cannot_close_without_a_passing_reinspection(self):
        finding = Finding.objects.create(equipment=self.equipment, description="خرابی ترمز", severity=Finding.Severity.CRITICAL)
        client = Client(); client.force_login(self.manager)
        result = client.post(reverse("finding_close", args=[finding.pk]), {"action": "close", "resolution": "تعمیر انجام شد"})
        finding.refresh_from_db()
        self.assertEqual(result.status_code, 302)
        self.assertEqual(finding.status, Finding.Status.OPEN)

    def test_due_dates_clamp_month_end_and_leap_year(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2028, 1, 31), 1), date(2028, 2, 29))


class PersistentSnapshotTests(TransactionTestCase):
    reset_sequences = True

    def test_sqlite_backup_creates_integrity_checked_recoverable_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target_db = root / "restored.sqlite3"
            with override_settings(PERSISTENCE_DIR=root):
                backup_database()
                backup = root / "backups" / "latest.sqlite3"
                self.assertTrue(backup.exists())
                backup_connection = sqlite3.connect(backup)
                try:
                    self.assertEqual(backup_connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                finally:
                    backup_connection.close()
            with override_settings(PERSISTENCE_DIR=root, DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(target_db)}}):
                self.assertTrue(restore_database())
                restored_connection = sqlite3.connect(target_db)
                try:
                    names = {row[0] for row in restored_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                finally:
                    restored_connection.close()
                self.assertIn("core_equipment", names)


class EphemeralDeploymentTests(TestCase):
    @override_settings(DEBUG=False, PERSISTENCE_CONFIRMED=False, SECURE_SSL_REDIRECT=False)
    def test_health_check_accepts_ephemeral_storage_and_reports_it(self):
        response = Client().get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "storage": "ephemeral"})
