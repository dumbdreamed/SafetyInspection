from django.core.management.base import BaseCommand

from core.demo_organization import seed_demo_organization


class Command(BaseCommand):
    help = "Create a sample organization chart using DEMO-OP personnel only."

    def handle(self, *args, **options):
        result = seed_demo_organization()
        self.stdout.write(self.style.SUCCESS(
            f"Prepared roles and reporting lines for {result['people']} demo staff; "
            f"created {result['clusters']} department groups."
        ))
