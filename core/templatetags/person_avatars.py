from django import template

register = template.Library()

AVATARS_BY_RANK = {
    "top": ("top-1.png",),
    "middle": ("middle-1.png", "middle-2.png"),
    "supervisor": (
        "supervisor-1.png",
        "supervisor-2.png",
        "supervisor-3.png",
        "supervisor-4.png",
    ),
    "employee": tuple(f"employee-{number}.png" for number in range(1, 7)),
    "other": tuple(f"employee-{number}.png" for number in range(1, 7)),
}


@register.filter
def rank_avatar(person, level="employee"):
    """Pick a stable, locally hosted portrait from the person's rank set."""
    variants = AVATARS_BY_RANK.get(level, AVATARS_BY_RANK["employee"])
    person_id = int(getattr(person, "pk", 0) or 1)
    filename = variants[(person_id - 1) % len(variants)]
    return f"icons/avatars/{filename}"
