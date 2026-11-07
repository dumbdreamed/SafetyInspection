from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import AuditLog

from .models import Equipment, EquipmentType, Finding, Inspection, InspectionResponse, Person, ChecklistItem, ChecklistTemplate


User = get_user_model()


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ChecklistWorkflowTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user("manager", password="Example-safe-1234")
        manager_group, _ = Group.objects.get_or_create(name="Safety Manager")
        self.manager.groups.add(manager_group)
        self.filler = User.objects.create_user("filler", password="Example-safe-1234")
        inspector_group, _ = Group.objects.get_or_create(name="Inspector")
        self.filler.groups.add(inspector_group)
        self.person = Person.objects.create(employee_code="EMP-01", full_name="بازرس نمونه", email="filler@example.test", user=self.filler)
        equipment_type = EquipmentType.objects.create(name="تجهیز نمونه")
        self.equipment = Equipment.objects.create(asset_code="EQ-01", name="ماشین نمونه", equipment_type=equipment_type)
        self.template = ChecklistTemplate.objects.create(name="چک‌لیست نمونه", equipment_type=equipment_type)
        self.item = ChecklistItem.objects.create(template=self.template, description="کنترل حفاظ", critical=False, weight=3)
        self.inspection = Inspection.objects.create(
            equipment=self.equipment, template=self.template, inspector=self.filler, due_date=date.today(),
            template_snapshot=[{"id": self.item.pk, "section": "ایمنی", "description": self.item.description, "critical": False, "weight": 3}],
        )

    def answer_payload(self, result="pass", **extra):
        data = {"action": "submit", f"result_{self.item.pk}": result, f"comment_{self.item.pk}": ""}
        data.update(extra)
        return data

    def test_filler_can_save_partial_draft_and_sees_only_own_workspace(self):
        self.client.force_login(self.filler)
        response = self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), {"action": "save_draft", "notes": "ادامه بعداً"})
        self.assertEqual(response.status_code, 302)
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.review_state, Inspection.ReviewState.DRAFT)
        self.assertEqual(self.inspection.status, Inspection.Status.PROGRESS)
        self.assertEqual(self.client.get(reverse("checklist_workspace")).status_code, 200)
        self.assertContains(self.client.get(reverse("dashboard")), "چک‌لیست‌های محول‌شده")

    def test_submit_waits_for_manager_and_failed_item_creates_linked_anomaly(self):
        payload = self.answer_payload(
            "fail", **{f"comment_{self.item.pk}": "حفاظ نصب نیست", f"assigned_{self.item.pk}": str(self.person.pk),
                       f"due_{self.item.pk}": (date.today() + timedelta(days=4)).isoformat()}
        )
        self.client.force_login(self.filler)
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), payload)
        self.inspection.refresh_from_db()
        finding = Finding.objects.get(inspection=self.inspection)
        self.assertEqual(self.inspection.review_state, Inspection.ReviewState.SUBMITTED)
        self.assertEqual(self.inspection.status, Inspection.Status.COMPLETED)
        self.assertEqual(finding.assigned_user, self.filler)
        self.assertEqual(finding.source_response, InspectionResponse.objects.get(inspection=self.inspection))
        manager_client = self.client_class()
        manager_client.force_login(self.manager)
        self.assertContains(manager_client.get(reverse("inspection_review_list")), "ماشین نمونه")

    def test_manager_can_return_for_correction_then_approve_resubmission(self):
        self.client.force_login(self.filler)
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), self.answer_payload())
        manager_client = self.client_class()
        manager_client.force_login(self.manager)
        manager_client.post(reverse("inspection_review_action", args=[self.inspection.pk]), {"action": "return", "review_note": "اندازه‌گیری را تکمیل کنید"})
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.review_state, Inspection.ReviewState.RETURNED)
        self.assertEqual(self.inspection.status, Inspection.Status.PROGRESS)
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), self.answer_payload())
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.review_state, Inspection.ReviewState.SUBMITTED)
        approval = manager_client.post(reverse("inspection_review_action", args=[self.inspection.pk]), {"action": "approve", "review_note": "بررسی شد"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(approval.json()["review_state"], Inspection.ReviewState.APPROVED)
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.review_state, Inspection.ReviewState.APPROVED)
        self.assertEqual(self.inspection.reviewed_by, self.manager)

    def test_filler_cannot_open_another_users_inspection(self):
        other = User.objects.create_user("other-filler", password="Example-safe-1234")
        inspector_group = Group.objects.get(name="Inspector")
        other.groups.add(inspector_group)
        other_inspection = Inspection.objects.create(equipment=self.equipment, template=self.template, inspector=other, due_date=date.today())
        self.client.force_login(self.filler)
        self.assertEqual(self.client.get(reverse("inspection_detail", args=[other_inspection.pk])).status_code, 403)
        for route in ["equipment_list", "people_list", "settings_page"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_pending_inspection_is_not_treated_as_approved_equipment_result(self):
        self.client.force_login(self.filler)
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), self.answer_payload())
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.review_state, Inspection.ReviewState.SUBMITTED)
        self.assertEqual(self.equipment.condition[0], "بازرسی‌نشده")

    def test_returned_checklist_draft_overrides_previous_submitted_answers(self):
        self.client.force_login(self.filler)
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), self.answer_payload())
        manager_client = self.client_class()
        manager_client.force_login(self.manager)
        manager_client.post(reverse("inspection_review_action", args=[self.inspection.pk]), {
            "action": "return", "review_note": "نتیجه را اصلاح کنید",
        })
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), {
            "action": "save_draft", f"result_{self.item.pk}": "fail",
            f"comment_{self.item.pk}": "پاسخ اصلاح‌شده",
        })
        response = self.client.get(reverse("inspection_detail", args=[self.inspection.pk]))
        self.assertContains(response, 'value="fail" checked')
        self.assertContains(response, "پاسخ اصلاح‌شده")

    def test_validation_error_keeps_checklist_entries_on_screen(self):
        self.client.force_login(self.filler)
        response = self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), {
            "action": "submit", f"result_{self.item.pk}": "fail",
            f"comment_{self.item.pk}": "ثبت اولیه من",
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'value="fail" checked', status_code=400)
        self.assertContains(response, "ثبت اولیه من", status_code=400)

    def test_manager_can_reassign_outstanding_checklist_and_audit_change(self):
        replacement = User.objects.create_user("EMP-02", password="Example-safe-1234")
        replacement.groups.add(Group.objects.get(name="Inspector"))
        Person.objects.create(employee_code="EMP-02", full_name="مسئول جایگزین", user=replacement)
        self.client.force_login(self.manager)
        response = self.client.post(reverse("inspection_reassign", args=[self.inspection.pk]), {
            "inspector": replacement.pk, "due_date": (date.today() + timedelta(days=2)).isoformat(),
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(response.json()["ok"])
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.inspector, replacement)
        self.assertTrue(AuditLog.objects.filter(action="واگذاری مجدد چک‌لیست", entity_id=self.inspection.pk).exists())

    def test_manager_edit_recalculates_score_and_records_changed_fields(self):
        self.client.force_login(self.filler)
        self.client.post(reverse("inspection_complete", args=[self.inspection.pk]), self.answer_payload())
        manager_client = self.client_class()
        manager_client.force_login(self.manager)
        manager_client.post(reverse("inspection_complete", args=[self.inspection.pk]), {
            "action": "manager_save", f"result_{self.item.pk}": "fail",
            f"comment_{self.item.pk}": "حفاظ مفقود", f"assigned_{self.item.pk}": self.person.pk,
            f"due_{self.item.pk}": (date.today() + timedelta(days=3)).isoformat(),
        })
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.outcome, Inspection.Outcome.FAIL)
        event = AuditLog.objects.get(action="ویرایش پاسخ‌های چک‌لیست", entity_id=self.inspection.pk)
        self.assertIn("نتیجه", event.details)

    def test_manager_can_disable_linked_filler_login(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("person_edit", args=[self.person.pk]), {
            "full_name": self.person.full_name, "employee_code": self.person.employee_code,
            "email": self.person.email, "account_user": self.filler.pk,
            "org_level": "employee", "org_title": "کارمند", "org_manager": "",
            "active": "on", "notes": "",
        })
        self.assertEqual(response.status_code, 302)
        self.filler.refresh_from_db()
        self.assertFalse(self.filler.is_active)
        self.assertEqual(self.filler.username, self.person.employee_code)
        self.assertEqual(self.filler.first_name, self.person.full_name)

    def test_manager_can_schedule_checklist_for_linked_filler_with_instructions(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("inspection_new"), {
            "equipment": self.equipment.pk, "template": self.template.pk,
            "inspector": self.filler.pk, "due_date": (date.today() + timedelta(days=5)).isoformat(),
            "instructions": "ایمنی محیط را پیش از شروع بررسی کنید.",
        })
        self.assertEqual(response.status_code, 302)
        assigned = Inspection.objects.exclude(pk=self.inspection.pk).get()
        self.assertEqual(assigned.inspector, self.filler)
        self.assertEqual(assigned.instructions, "ایمنی محیط را پیش از شروع بررسی کنید.")

    def test_manager_can_delegate_current_checklists_and_reissue_approved_ones_from_list(self):
        replacement = User.objects.create_user("EMP-02", password="Example-safe-1234")
        inspector_group, _ = Group.objects.get_or_create(name="Inspector")
        replacement.groups.add(inspector_group)
        Person.objects.create(employee_code="EMP-02", full_name="مسئول دوم", user=replacement)
        approved = Inspection.objects.create(
            equipment=self.equipment, template=self.template, inspector=self.filler, due_date=date.today(),
            status=Inspection.Status.COMPLETED, review_state=Inspection.ReviewState.APPROVED,
            outcome=Inspection.Outcome.PASS, completed_at=timezone.now(),
            template_snapshot=[{"id": self.item.pk, "section": "ایمنی", "description": self.item.description, "critical": False, "weight": 3}],
            threshold_snapshot=35,
        )
        self.client.force_login(self.manager)
        page = self.client.get(reverse("inspection_list"))
        self.assertContains(page, "واگذاری چک‌لیست‌ها")
        self.assertContains(page, 'id="inspection-select-all"')
        due_date = (date.today() + timedelta(days=7)).isoformat()
        response = self.client.post(reverse("inspection_delegate"), {
            "inspection_ids": [self.inspection.pk, approved.pk],
            "inspector": replacement.pk, "due_date": due_date, "instructions": "پیش از شروع، محیط را بررسی کنید.",
        })
        self.assertEqual(response.status_code, 302)
        self.inspection.refresh_from_db()
        approved.refresh_from_db()
        self.assertEqual(self.inspection.inspector, replacement)
        self.assertEqual(self.inspection.due_date.isoformat(), due_date)
        self.assertEqual(approved.review_state, Inspection.ReviewState.APPROVED)
        self.assertEqual(approved.inspector, self.filler)
        fresh = Inspection.objects.exclude(pk__in=[self.inspection.pk, approved.pk]).get()
        self.assertEqual(fresh.inspector, replacement)
        self.assertEqual(fresh.review_state, Inspection.ReviewState.ASSIGNED)
        self.assertEqual(fresh.status, Inspection.Status.SCHEDULED)
        self.assertEqual(fresh.template_snapshot, approved.template_snapshot)
        self.assertEqual(fresh.threshold_snapshot, approved.threshold_snapshot)
        self.assertEqual(fresh.instructions, "پیش از شروع، محیط را بررسی کنید.")

    def test_manager_cannot_delegate_checklist_waiting_for_review(self):
        submitted = Inspection.objects.create(
            equipment=self.equipment, template=self.template, inspector=self.filler, due_date=date.today(),
            status=Inspection.Status.COMPLETED, review_state=Inspection.ReviewState.SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.client.force_login(self.manager)
        response = self.client.post(reverse("inspection_delegate"), {
            "inspection_ids": [submitted.pk], "inspector": self.filler.pk,
            "due_date": (date.today() + timedelta(days=7)).isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        submitted.refresh_from_db()
        self.assertEqual(submitted.inspector, self.filler)
        self.assertEqual(Inspection.objects.count(), 2)
        self.assertFalse(AuditLog.objects.filter(action="واگذاری مجدد چک‌لیست", entity_id=submitted.pk).exists())

    def test_manager_assigns_anomaly_to_linked_filler_and_filler_can_report_progress(self):
        finding = Finding.objects.create(equipment=self.equipment, description="روغن نشت می‌کند")
        self.client.force_login(self.manager)
        self.client.post(reverse("finding_close", args=[finding.pk]), {
            "action": "assign", "assigned_person": self.person.pk,
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
        })
        finding.refresh_from_db()
        self.assertEqual(finding.assigned_user, self.filler)
        self.client.force_login(self.filler)
        self.assertContains(self.client.get(reverse("my_findings")), "روغن نشت می‌کند")
        response = self.client.post(reverse("finding_close", args=[finding.pk]), {"action": "progress", "resolution": "قطعه سفارش داده شد"})
        self.assertEqual(response.status_code, 302)
        finding.refresh_from_db()
        self.assertEqual(finding.status, Finding.Status.PROGRESS)
        self.assertEqual(finding.resolution, "قطعه سفارش داده شد")

    def test_filler_cannot_assign_or_update_an_unassigned_anomaly(self):
        finding = Finding.objects.create(equipment=self.equipment, description="نقص دیگر")
        self.client.force_login(self.filler)
        response = self.client.post(reverse("finding_close", args=[finding.pk]), {"action": "progress", "resolution": "در حال اصلاح"})
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_a_linked_filler_account_and_password_reset_page_renders(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("person_new"), {
            "full_name": "تکمیل‌کننده جدید", "employee_code": "emp-new", "email": "new-filler@example.test",
            "create_account": "on", "account_username": "new-filler", "org_level": "employee",
            "org_title": "کارمند", "org_manager": "", "active": "on", "account_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        person = Person.objects.get(employee_code="EMP-NEW")
        self.assertIsNotNone(person.user_id)
        self.assertEqual(person.user.username, "EMP-NEW")
        self.assertEqual(person.user.first_name, person.full_name)
        self.assertEqual(person.user.email, person.email)
        self.assertTrue(person.user.groups.filter(name="Inspector").exists())
        self.assertTrue(person.user.is_active)
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)
