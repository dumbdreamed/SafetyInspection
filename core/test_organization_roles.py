from django.contrib.auth import get_user_model
from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from importlib import import_module
from types import SimpleNamespace

from .demo_organization import seed_demo_organization
from .models import Area, Department, Equipment, EquipmentType, Finding, OrganizationCluster, OrganizationPosition, Person


@override_settings(PERSISTENCE_CONFIRMED=False, SECURE_SSL_REDIRECT=False, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AutomaticOrganizationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="org-admin", password="test-password")
        self.client.force_login(self.admin)

    def create_person(self, code, name, level, manager="", title=""):
        response = self.client.post(reverse("person_new"), {
            "employee_code": code, "full_name": name, "active": "on",
            "org_level": level, "org_title": title, "org_manager": manager,
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        return Person.objects.get(employee_code=code)

    def test_direct_person_creation_gets_a_default_role(self):
        person = Person.objects.create(employee_code="P-1", full_name="Person One")
        self.assertEqual(person.organization_position.level, OrganizationPosition.Level.EMPLOYEE)
        self.assertFalse(person.organization_position.chart_visible)
        self.assertIsNone(person.organization_position.manager_id)

    def test_backfill_adds_missing_roles_without_overwriting_existing_ones(self):
        existing = Person.objects.create(employee_code="P-1", full_name="Existing")
        position = existing.organization_position
        position.level, position.title, position.chart_visible = "top", "Director", True
        position.save()
        missing = Person.objects.create(employee_code="P-2", full_name="Missing")
        OrganizationPosition.objects.filter(person=missing).delete()
        migration = import_module("core.migrations.0008_organizationposition_chart_visible")
        migration.add_missing_person_roles(apps, SimpleNamespace(connection=connection))
        position.refresh_from_db()
        self.assertEqual((position.level, position.title, position.chart_visible), ("top", "Director", True))
        restored = OrganizationPosition.objects.get(person=missing)
        self.assertEqual(restored.level, "employee")
        self.assertFalse(restored.chart_visible)

    def test_direct_manager_assignment_shows_the_reporting_chain(self):
        manager = Person.objects.create(employee_code="P-1", full_name="Manager")
        staff = Person.objects.create(employee_code="P-2", full_name="Staff")
        manager_position = manager.organization_position
        manager_position.level = OrganizationPosition.Level.SUPERVISOR
        manager_position.save()
        position = staff.organization_position
        position.manager = manager_position
        position.save()
        position.refresh_from_db()
        manager_position.refresh_from_db()
        self.assertTrue(position.chart_visible)
        self.assertTrue(manager_position.chart_visible)

    def test_personnel_form_builds_chart_from_manager_assignment(self):
        manager = self.create_person("P-1", "Manager", "top")
        staff = self.create_person("P-2", "Staff", "employee", manager.organization_position.pk, "Technician")
        manager_position = manager.organization_position
        position = staff.organization_position
        self.assertEqual(position.manager_id, manager_position.pk)
        self.assertTrue(position.chart_visible)
        self.assertTrue(manager_position.chart_visible)
        self.assertEqual(position.title, "Technician")
        response = self.client.get(reverse("organization_chart"))
        self.assertContains(response, "Manager")
        self.assertContains(response, "Staff")
        self.assertContains(response, "Technician")

    def test_employee_cannot_be_selected_as_direct_manager(self):
        employee = Person.objects.create(employee_code="P-1", full_name="Employee")
        response = self.client.post(reverse("person_new"), {
            "employee_code": "P-2", "full_name": "Staff", "active": "on",
            "org_level": "employee", "org_title": "", "org_manager": employee.organization_position.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("org_manager", response.context["form"].errors)
        self.assertFalse(Person.objects.filter(employee_code="P-2").exists())

    def test_promoting_a_default_employee_updates_the_default_title(self):
        person = Person.objects.create(employee_code="P-1", full_name="Promoted")
        default_title = person.organization_position.title
        response = self.client.post(reverse("person_edit", args=[person.pk]), {
            "employee_code": person.employee_code, "full_name": person.full_name, "active": "on",
            "org_level": "top", "org_title": default_title, "org_manager": "",
        })
        self.assertEqual(response.status_code, 302)
        person.organization_position.refresh_from_db()
        self.assertEqual(person.organization_position.title, person.organization_position.get_level_display())
        self.assertTrue(person.organization_position.chart_visible)

    def test_cycle_and_manager_demotion_are_rejected(self):
        root = self.create_person("P-1", "Director", "top")
        lead = self.create_person("P-2", "Supervisor", "supervisor", root.organization_position.pk)
        response = self.client.post(reverse("person_edit", args=[root.pk]), {
            "employee_code": root.employee_code, "full_name": root.full_name, "active": "on",
            "org_level": "top", "org_title": "Director", "org_manager": lead.organization_position.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("org_manager", response.context["form"].errors)
        response = self.client.post(reverse("person_edit", args=[root.pk]), {
            "employee_code": root.employee_code, "full_name": root.full_name, "active": "on",
            "org_level": "employee", "org_title": "Employee", "org_manager": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("org_level", response.context["form"].errors)
        root.organization_position.refresh_from_db()
        self.assertEqual(root.organization_position.level, "top")
        self.assertIsNone(root.organization_position.manager_id)

    def test_clear_chart_preserves_people_roles_and_assigned_anomalies(self):
        manager = self.create_person("P-1", "Manager", "top")
        staff = self.create_person("P-2", "Staff", "employee", manager.organization_position.pk, "Technician")
        kind = EquipmentType.objects.create(name="Test equipment")
        equipment = Equipment.objects.create(asset_code="E-1", name="Test equipment", equipment_type=kind)
        finding = Finding.objects.create(equipment=equipment, description="Test defect", assigned_person=staff, assigned_to=staff.full_name)
        response = self.client.post(reverse("organization_clear"))
        self.assertEqual(response.status_code, 302)
        position = OrganizationPosition.objects.get(person=staff)
        self.assertIsNone(position.manager_id)
        self.assertFalse(position.chart_visible)
        self.assertEqual(position.title, "Technician")
        finding.refresh_from_db()
        self.assertEqual(finding.assigned_person_id, staff.pk)

    def test_remove_position_keeps_role_and_reparents_reports(self):
        director = self.create_person("P-1", "Director", "top")
        manager = self.create_person("P-2", "Manager", "middle", director.organization_position.pk)
        staff = self.create_person("P-3", "Staff", "employee", manager.organization_position.pk)
        response = self.client.post(reverse("organization_remove", args=[manager.organization_position.pk]))
        self.assertEqual(response.status_code, 302)
        manager_position = OrganizationPosition.objects.get(person=manager)
        staff_position = OrganizationPosition.objects.get(person=staff)
        self.assertFalse(manager_position.chart_visible)
        self.assertEqual(manager_position.level, "middle")
        self.assertEqual(staff_position.manager_id, director.organization_position.pk)

    def test_chart_edit_cannot_reassign_a_role_to_another_person(self):
        manager = self.create_person("P-1", "Manager", "top")
        other = Person.objects.create(employee_code="P-2", full_name="Other")
        position = manager.organization_position
        response = self.client.post(reverse("organization_edit", args=[position.pk]), {
            "person": other.pk, "title": "Director", "level": "top", "manager": "", "order": 0,
        })
        self.assertEqual(response.status_code, 302)
        position.refresh_from_db()
        self.assertEqual(position.person_id, manager.pk)
        self.assertTrue(OrganizationPosition.objects.filter(person=other).exists())

    def test_nonmanager_cannot_modify_chart(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="test-password")
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(reverse("organization_clear")).status_code, 403)

    def test_groups_filter_chart_and_deletion_preserves_hierarchy(self):
        manager = self.create_person("P-1", "Manager", "top")
        staff = self.create_person("P-2", "Staff", "employee", manager.organization_position.pk)
        response = self.client.post(reverse("organization_cluster_add"), {
            "name": "Workshop", "members": [staff.organization_position.pk],
        })
        self.assertEqual(response.status_code, 302)
        group = OrganizationCluster.objects.get(name="Workshop")
        response = self.client.get(reverse("organization_chart"), {"cluster": group.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([node["position"].person_id for node in response.context["roots"]], [staff.pk])
        self.assertContains(response, "data-org-canvas")
        response = self.client.post(reverse("organization_cluster_delete", args=[group.pk]))
        self.assertEqual(response.status_code, 302)
        staff.organization_position.refresh_from_db()
        self.assertEqual(staff.organization_position.manager_id, manager.organization_position.pk)
        self.assertTrue(Person.objects.filter(pk=staff.pk).exists())

    def test_group_creation_makes_selected_members_visible(self):
        person = Person.objects.create(employee_code="P-1", full_name="Staff")
        self.assertFalse(person.organization_position.chart_visible)
        response = self.client.post(reverse("organization_cluster_add"), {
            "name": "Team", "members": [person.organization_position.pk],
        })
        self.assertEqual(response.status_code, 302)
        person.organization_position.refresh_from_db()
        self.assertTrue(person.organization_position.chart_visible)

    def test_group_members_can_be_changed_without_removing_personnel(self):
        first = Person.objects.create(employee_code="P-1", full_name="First")
        second = Person.objects.create(employee_code="P-2", full_name="Second")
        group = OrganizationCluster.objects.create(name="Team")
        group.members.add(first.organization_position)
        response = self.client.post(reverse("organization_cluster_edit", args=[group.pk]), {
            "name": "Updated team", "members": [second.organization_position.pk],
        })
        self.assertEqual(response.status_code, 302)
        group.refresh_from_db()
        self.assertEqual(group.name, "Updated team")
        self.assertEqual(list(group.members.values_list("person_id", flat=True)), [second.pk])
        self.assertTrue(Person.objects.filter(pk=first.pk).exists())
        second.organization_position.refresh_from_db()
        self.assertTrue(second.organization_position.chart_visible)

    def test_nonmanager_cannot_modify_groups(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="test-password")
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(reverse("organization_cluster_add"), {"name": "Team"}).status_code, 403)


class DemoOrganizationSeedTests(TestCase):
    def setUp(self):
        area = Area.objects.create(name="Demo area")
        self.production = Department.objects.create(name="Production", area=area)
        self.maintenance = Department.objects.create(name="Maintenance", area=area)

    def add_demo_staff(self, department, codes):
        return [
            Person.objects.create(
                employee_code=f"DEMO-OP-{code}", full_name=f"Sample {code}", department=department
            )
            for code in codes
        ]

    def test_demo_seed_creates_full_department_hierarchies_and_is_repeatable(self):
        staff = self.add_demo_staff(self.production, ["EQ01-001", "EQ01-002", "EQ01-003", "EQ01-004", "EQ01-005"])
        staff += self.add_demo_staff(self.maintenance, ["EQ02-001", "EQ02-002", "EQ02-003", "EQ02-004"])
        real_person = Person.objects.create(employee_code="REAL-1", full_name="Existing")
        real_person.organization_position.title = "Unchanged"
        real_person.organization_position.level = OrganizationPosition.Level.OTHER
        real_person.organization_position.save()

        first_result = seed_demo_organization()
        second_result = seed_demo_organization()

        self.assertEqual(first_result, {"people": 9, "clusters": 2})
        self.assertEqual(second_result, {"people": 9, "clusters": 0})
        positions = OrganizationPosition.objects.filter(person__employee_code__startswith="DEMO-OP-")
        self.assertEqual(positions.count(), 9)
        self.assertEqual(positions.filter(level=OrganizationPosition.Level.TOP).count(), 1)
        self.assertEqual(positions.filter(level=OrganizationPosition.Level.MIDDLE).count(), 2)
        self.assertEqual(positions.filter(level=OrganizationPosition.Level.SUPERVISOR).count(), 4)
        self.assertEqual(positions.filter(level=OrganizationPosition.Level.EMPLOYEE).count(), 2)
        self.assertEqual(positions.filter(chart_visible=True).count(), 9)
        root = OrganizationPosition.objects.get(person=staff[0])
        self.assertIsNone(root.manager_id)
        self.assertEqual(root.level, OrganizationPosition.Level.TOP)
        self.assertTrue(positions.exclude(pk=root.pk).filter(manager__isnull=True).count() == 0)

        production_group = OrganizationCluster.objects.get(name__contains="Production")
        self.assertEqual(
            set(production_group.members.values_list("person_id", flat=True)),
            {person.pk for person in staff if person.department_id == self.production.pk} | {root.person_id},
        )
        real_person.organization_position.refresh_from_db()
        self.assertEqual(real_person.organization_position.title, "Unchanged")
        self.assertEqual(real_person.organization_position.level, OrganizationPosition.Level.OTHER)
        self.assertFalse(real_person.organization_position.chart_visible)
