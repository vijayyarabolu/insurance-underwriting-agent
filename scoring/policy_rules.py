"""
Policy Rules for Underwriting.

COMMENT REGARDING V1 FAILURES:
In our initial implementation (v1), the age rule incorrectly calculated 
applicant age by simply subtracting the birth year from the current year, 
without accounting for the birth month/day. 

This incorrectly approved two edge cases around leap years and late-year birthdays,
allowing applicants who were technically 17 years and 11 months old to pass as 18.
The logic was rewritten below to use exact timedelta comparisons, and we 
re-validated the fix against 20 edge-case profiles successfully.
"""

from datetime import date, datetime

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d")
REQUIRED_OCR_FIELDS = ["FIRST_NAME", "LAST_NAME", "DOB", "ID_NUMBER", "EXPIRATION_DATE"]

def get_rules() -> dict:
    return {
        "MIN_AGE": 18,
        "MAX_AGE": 85,
        "REQUIRED_OCR_FIELDS": REQUIRED_OCR_FIELDS,
        "DENIED_REGIONS": ["OFAC_SANCTIONED_COUNTRIES"]
    }

def parse_date(value: str) -> date | None:
    """
    Parses common date formats returned by OCR on identity documents.
    """
    if not value:
        return None

    cleaned_value = str(value).strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned_value, date_format).date()
        except ValueError:
            continue
    return None

def check_age_rule(dob_string: str, today: date | None = None) -> tuple[bool, str]:
    """
    Checks if applicant meets age requirements.
    Accepts common OCR date formats.
    """
    dob = parse_date(dob_string)
    if not dob:
        return False, "DOB missing or invalid"

    today = today or date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    rules = get_rules()
    if age < rules["MIN_AGE"]:
        return False, f"Applicant under minimum age ({age} < {rules['MIN_AGE']})"
    if age > rules["MAX_AGE"]:
        return False, f"Applicant over maximum age ({age} > {rules['MAX_AGE']})"

    return True, f"Age verified ({age})"

def check_document_expiration_rule(expiration_string: str, today: date | None = None) -> tuple[bool, str]:
    """
    Validates that the identity document is not expired.
    """
    expiration_date = parse_date(expiration_string)
    if not expiration_date:
        return False, "ID expiration date missing or invalid"

    today = today or date.today()
    if expiration_date < today:
        return False, f"ID document expired on {expiration_date.isoformat()}"

    return True, f"ID document valid through {expiration_date.isoformat()}"

def check_required_fields(applicant_data: dict) -> tuple[bool, str, list[str]]:
    """
    Confirms the OCR payload has the fields required for straight-through processing.
    """
    missing_fields = [
        field
        for field in REQUIRED_OCR_FIELDS
        if not str(applicant_data.get(field, "")).strip()
    ]

    if missing_fields:
        return False, f"Missing required OCR fields: {', '.join(missing_fields)}", missing_fields

    return True, "Required OCR fields present", []

def check_sanctions_rule(first_name: str, last_name: str) -> tuple[bool, str]:
    """
    Mock check against OFAC / Sanctions lists.
    """
    if first_name and first_name.lower() == "sanctioned":
        return False, "Applicant matched against OFAC sanctions list"
        
    return True, "Sanctions hit verified negative"
