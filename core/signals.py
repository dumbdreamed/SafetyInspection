from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OrganizationPosition, Person, show_organization_chain


@receiver(post_save, sender=Person, dispatch_uid="ensure_person_organization_position")
def ensure_person_organization_position(sender, instance, raw=False, **kwargs):
    if not raw:
        OrganizationPosition.objects.get_or_create(
            person=instance,
            defaults={"title": "کارمند", "level": OrganizationPosition.Level.EMPLOYEE, "chart_visible": False},
        )


@receiver(post_save, sender=OrganizationPosition, dispatch_uid="show_assigned_organization_chain")
def show_assigned_organization_chain(sender, instance, raw=False, **kwargs):
    if not raw and instance.manager_id:
        show_organization_chain(instance)
