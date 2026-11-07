from django import template

register = template.Library()

# Tabler provides exact equipment illustrations for several machine types;
# related vehicle or road symbols cover categories without an exact match.
ICONS_BY_TYPE = {
    "بابکت": "skid", "بولدوزر": "dozer", "بیل بکهو": "backhoe", "بیل مکانیکی": "excavate",
    "تانکر آبپاش": "tanker", "تراک میکسر": "mixer", "تراکتور": "tractor", "تریلی": "trailer",
    "جرثقیل": "crane", "جرثقیل سقفی": "overhead", "جرثقیل متحرک": "mobcrane", "حفار": "drill",
    "غلطک": "roller", "فینیشر": "paver", "لودر": "loader", "لیفتراک": "forklift",
    "پمپ بتن": "pump", "کامیون": "truck", "گریدر": "grader",
}


@register.inclusion_tag("core/equipment_icon.html")
def equipment_icon(type_name):
    return {"icon_key": ICONS_BY_TYPE.get(type_name, "fallback")}
