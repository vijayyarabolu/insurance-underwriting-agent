"""
Deterministic underwriting rules.

These run before any LLM step and are the only thing allowed to hard-reject an
application. Each check returns (passed, message), and checks that cannot run
because OCR missed a field say so, so the engine can route to review instead of
rejecting someone over a blurry photo.

Age uses an exact birthday comparison. An earlier version subtracted birth
year from the current year, which passed applicants who turn 18 later this
year. The edge cases live in eval/applicants.jsonl.
"""

import csv
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d")
REQUIRED_OCR_FIELDS = ["FIRST_NAME", "LAST_NAME", "DOB", "ID_NUMBER", "EXPIRATION_DATE"]

def get_rules() -> dict:
    return {
        "MIN_AGE": 18,
        "MAX_AGE": 85,
        "REQUIRED_OCR_FIELDS": REQUIRED_OCR_FIELDS,
        "DENIED_REGIONS": ["OFAC_SANCTIONED_COUNTRIES"],
        "HIGH_RISK_WEATHER_STATES": ["FL"],
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

SANCTIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "sanctions_sample.csv"


def normalize_name(value: str) -> str:
    """Lowercase, strip accents and punctuation, and sort tokens so order does not matter."""
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z]+", text.lower())
    return " ".join(sorted(tokens))


def load_sanctions_list(path: Path = SANCTIONS_FILE) -> dict[str, str]:
    with open(path) as handle:
        rows = csv.DictReader(line for line in handle if not line.startswith("#"))
        return {normalize_name(row["full_name"]): row["entry_id"] for row in rows}


_SANCTIONS = None


POSSIBLE_MATCH_RATIO = 0.88


def screen_sanctions(first_name: str, last_name: str) -> tuple[str, str]:
    """
    Screens the applicant name against the sanctions list.

    Returns ("match" | "possible" | "clear", message). Offline this uses a small
    fictional sample list (data/sanctions_sample.csv). Matching ignores case,
    accents, hyphens and name order, so "QUINTERO BAEZ, Marisol" from OCR still
    matches "Marisol Quintero-Baez". Close spellings come back as "possible"
    so a person reviews them instead of the rule silently passing them.
    """
    global _SANCTIONS
    if _SANCTIONS is None:
        _SANCTIONS = load_sanctions_list()

    key = normalize_name(f"{first_name} {last_name}")
    if not key:
        return "clear", "No name to screen"
    if key in _SANCTIONS:
        return "match", f"Name matched sanctions list entry {_SANCTIONS[key]}"

    best_key, best_ratio = None, 0.0
    for listed in _SANCTIONS:
        ratio = SequenceMatcher(None, key, listed).ratio()
        if ratio > best_ratio:
            best_key, best_ratio = listed, ratio
    if best_ratio >= POSSIBLE_MATCH_RATIO:
        return "possible", (f"Possible sanctions match to entry {_SANCTIONS[best_key]} "
                            f"(similarity {best_ratio:.2f}), needs review")
    return "clear", "No sanctions list match"


def check_sanctions_rule(first_name: str, last_name: str) -> tuple[bool, str]:
    status, message = screen_sanctions(first_name, last_name)
    return status == "clear", message


STATE_IN_ADDRESS_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?\s*$")


def extract_state(applicant_data: dict) -> str | None:
    """
    Read the state from the ID's issuing state, or from a trailing "ST 12345" in
    the address. An earlier version searched the address for the token "fl",
    which flagged "3rd FL" (floor) as Florida.
    """
    issuing = str(applicant_data.get("ISSUING_STATE", "")).strip().upper()
    if re.fullmatch(r"[A-Z]{2}", issuing):
        return issuing
    match = STATE_IN_ADDRESS_RE.search(str(applicant_data.get("ADDRESS", "")).strip().upper())
    return match.group(1) if match else None
