"""Build a realistic, explicitly synthetic reporting hierarchy for demo staff."""

from django.db import transaction

from .models import Assignment, OrganizationCluster, OrganizationPosition, Person


DEMO_PERSON_PREFIX = "DEMO-OP-"


def _employee_title(person):
    assignment = (
        Assignment.objects.filter(person=person)
        .select_related("equipment__equipment_type")
        .order_by("-starts_on", "pk")
        .first()
    )
    if assignment:
        return f"{assignment.get_role_display()} {assignment.equipment.equipment_type.name}"
    return "نیروی اجرایی"


@transaction.atomic
def seed_demo_organization():
    """Assign demo-only staff to a repeatable plant/department/team hierarchy."""
    people = list(
        Person.objects.filter(employee_code__startswith=DEMO_PERSON_PREFIX)
        .select_related("department")
        .order_by("department_id", "employee_code", "pk")
    )
    if not people:
        return {"people": 0, "clusters": 0}

    positions = {}
    for person in people:
        positions[person.pk], _ = OrganizationPosition.objects.get_or_create(
            person=person,
            defaults={"title": "کارمند", "level": OrganizationPosition.Level.EMPLOYEE},
        )

    root_person = next(
        (person for person in people if person.employee_code == f"{DEMO_PERSON_PREFIX}EQ01-001"),
        people[0],
    )
    root = positions[root_person.pk]
    plan = {
        root.pk: {
            "level": OrganizationPosition.Level.TOP,
            "title": "مدیر ارشد کارخانه",
            "manager": None,
            "order": 0,
        }
    }

    departments = {}
    ungrouped = []
    for person in people:
        if person.department_id:
            departments.setdefault(person.department_id, []).append(person)
        elif person.pk != root_person.pk:
            ungrouped.append(person)

    cluster_count = 0
    for department_id, department_people in departments.items():
        department = department_people[0].department
        candidates = [person for person in department_people if person.pk != root_person.pk]
        manager_position = None
        supervisor_positions = []

        if candidates:
            manager_person = candidates.pop(0)
            manager_position = positions[manager_person.pk]
            plan[manager_position.pk] = {
                "level": OrganizationPosition.Level.MIDDLE,
                "title": f"مدیر {department.name}",
                "manager": root,
                "order": department_id,
            }

            for index, supervisor_person in enumerate(candidates[:2], start=1):
                supervisor_position = positions[supervisor_person.pk]
                supervisor_positions.append(supervisor_position)
                plan[supervisor_position.pk] = {
                    "level": OrganizationPosition.Level.SUPERVISOR,
                    "title": f"سرپرست تیم {index} — {department.name}",
                    "manager": manager_position,
                    "order": index,
                }
            candidates = candidates[2:]

        for index, person in enumerate(candidates):
            position = positions[person.pk]
            if supervisor_positions:
                direct_manager = supervisor_positions[index % len(supervisor_positions)]
            else:
                direct_manager = manager_position or root
            plan[position.pk] = {
                "level": OrganizationPosition.Level.EMPLOYEE,
                "title": _employee_title(person),
                "manager": direct_manager,
                "order": index,
            }

        cluster_name = f"ساختار آزمایشی — {department.name}"
        cluster, created = OrganizationCluster.objects.get_or_create(name=cluster_name)
        cluster_count += int(created)
        cluster_members = [positions[person.pk] for person in department_people]
        if root.pk not in {position.pk for position in cluster_members}:
            cluster_members.append(root)
        cluster.members.set(cluster_members)

    for index, person in enumerate(ungrouped):
        position = positions[person.pk]
        plan[position.pk] = {
            "level": OrganizationPosition.Level.EMPLOYEE,
            "title": _employee_title(person),
            "manager": root,
            "order": index,
        }

    changed_positions = []
    for person in people:
        position = positions[person.pk]
        details = plan.get(position.pk)
        if details is None:
            # The root may be the only person in its department; it is already in the plan.
            details = {
                "level": OrganizationPosition.Level.EMPLOYEE,
                "title": _employee_title(person),
                "manager": root,
                "order": 0,
            }
        position.level = details["level"]
        position.title = details["title"]
        position.manager = details["manager"]
        position.order = details["order"]
        position.chart_visible = True
        changed_positions.append(position)

    OrganizationPosition.objects.bulk_update(
        changed_positions, ["level", "title", "manager", "order", "chart_visible"]
    )
    return {"people": len(people), "clusters": cluster_count}
