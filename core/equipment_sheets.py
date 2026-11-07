"""Equipment fields that exist in each register sheet in Machinery GISDCO.xlsx."""

BASE_REGISTER_FIELDS = {
    "asset_code",
    "year",
    "entered_on",
    "status",
    "primary_contractor",
    "subcontractor",
}

# These sheets use one "date of exit / status" column. The overhead-crane
# sheet has a status column only, so it deliberately has no exited_on field.
EXIT_DATE_TYPES = {
    "لودر",
    "بیل مکانیکی",
    "بیل بکهو",
    "تانکر آبپاش",
    "تراکتور",
    "تراک میکسر",
    "پمپ بتن",
    "کامیون",
    "گریدر",
    "بابکت",
    "بولدوزر",
    "جرثقیل",
    "جرثقیل متحرک",
    "لیفتراک",
    "غلطک",
    "فینیشر",
    "حفار",
    "تریلی",
}

SHEET_FIELDS = {
    "لودر": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "بیل مکانیکی": {"machine_subtype", "serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "بیل بکهو": {"machine_subtype", "serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "تانکر آبپاش": {"machine_subtype", "plate", "vin", "engine_number", "third_party_insurance_expires_on", "technical_inspection_expires_on"},
    "تراکتور": {"plate", "serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "تراک میکسر": {"plate", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on", "technical_inspection_expires_on"},
    "پمپ بتن": {"plate", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on", "technical_inspection_expires_on"},
    "کامیون": {"machine_subtype", "plate", "vin", "engine_number", "third_party_insurance_expires_on", "technical_inspection_expires_on"},
    "گریدر": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "بابکت": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "بولدوزر": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "جرثقیل": {
        "machine_subtype", "manufacturer", "plate", "serial_number", "vin", "engine_number",
        "third_party_insurance_expires_on", "liability_insurance_expires_on", "technical_inspection_expires_on",
        "rated_capacity", "capacity_unit", "large_hook_capacity", "small_hook_capacity",
        "certificate_issued_on", "certificate_expires_on",
    },
    "جرثقیل متحرک": {
        "machine_subtype", "manufacturer", "plate", "serial_number", "vin", "engine_number",
        "third_party_insurance_expires_on", "liability_insurance_expires_on", "technical_inspection_expires_on",
        "rated_capacity", "capacity_unit", "large_hook_capacity", "small_hook_capacity",
        "certificate_issued_on", "certificate_expires_on",
    },
    # The head-crane sheet has no engine, chassis, plate, third-party policy,
    # technical-inspection date, or exit-date column.
    "جرثقیل سقفی": {
        "position", "manufacturer", "serial_number", "liability_insurance_expires_on",
        "rated_capacity", "capacity_unit", "large_hook_capacity", "small_hook_capacity",
        "certificate_issued_on", "certificate_expires_on",
    },
    "لیفتراک": {
        "manufacturer", "serial_number", "vin", "engine_number", "third_party_insurance_expires_on",
        "liability_insurance_expires_on", "rated_capacity", "capacity_unit", "confirmed_capacity",
        "certificate_issued_on", "certificate_expires_on",
    },
    "غلطک": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "فینیشر": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    "حفار": {"serial_number", "vin", "engine_number", "third_party_insurance_expires_on", "liability_insurance_expires_on"},
    # Trailer entries are recorded on the combined light / semi-heavy sheet.
    "تریلی": {
        "machine_subtype", "plate", "vin", "engine_number", "third_party_insurance_expires_on",
        "desert_insurance_expires_on", "technical_inspection_expires_on",
    },
}

EQUIPMENT_SHEET_PROFILES = {
    name: BASE_REGISTER_FIELDS | fields | ({"exited_on"} if name in EXIT_DATE_TYPES else set())
    for name, fields in SHEET_FIELDS.items()
}

SHEET_OPTIONAL_FIELDS = set().union(*EQUIPMENT_SHEET_PROFILES.values()) - BASE_REGISTER_FIELDS
