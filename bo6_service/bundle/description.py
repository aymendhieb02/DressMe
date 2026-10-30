"""Deterministic garment description: a template over validated structured fields.
No generative language model is involved, and nothing is read from the image here."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "description_schema.json").read_text(encoding="utf-8"))
ALLOWED = {k: v["allowed"] for k, v in SCHEMA["fields"].items()}
PLURAL = set(SCHEMA["plural_categories"])


def validate_fields(fields):
    """-> (clean, problems). Keys outside the schema are dropped; disallowed values become "unknown"."""
    clean, problems = {}, []
    for key, allowed in ALLOWED.items():
        v = fields.get(key, "unknown")
        v = v.strip().lower() if isinstance(v, str) else "unknown"
        if v not in allowed:
            problems.append(key + ": value not allowed")
            v = "unknown"
        clean[key] = v
    extra = sorted(set(fields) - set(ALLOWED))
    if extra:
        problems.append("dropped keys: " + ", ".join(map(str, extra)))
    return clean, problems


def parse_model_json(text):
    """Parse a model reply that should contain one flat JSON object -> (clean or None, problems)."""
    m = re.search(r"\{[^{}]*\}", text or "", re.S)
    if not m:
        return None, ["no JSON object found"]
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None, ["invalid JSON"]
    if not isinstance(obj, dict):
        return None, ["JSON is not an object"]
    return validate_fields(obj)


def render(fields):
    f, _ = validate_fields(fields)
    words = []
    if f["color"] != "unknown":
        words.append(f["color"])
    if f["pattern"] not in ("unknown", "not_visible", "solid"):
        words.append(f["pattern"])
    if f["sleeve_length"] in ("short", "long"):
        words.append(f["sleeve_length"] + "-sleeved")
    elif f["sleeve_length"] == "sleeveless":
        words.append("sleeveless")
    noun = f["category"] if f["category"] != "unknown" else "garment"
    words.append(noun)
    lead = "A pair of " if noun in PLURAL else ("An " if words[0][0] in "aeiou" else "A ")
    return lead + " ".join(words) + "."


def describe(category, category_source="classifier", confirmed=None, predicted=None):
    """category: predicted label or "unknown".
    predicted: {field: value} from the attribute heads (provenance "attribute_model").
    confirmed: {field: value} corrected by the user; overrides everything (provenance "user_confirmed")."""
    fields = {k: "unknown" for k in ALLOWED}
    prov = {k: "not_estimated" for k in ALLOWED}
    fields["category"], prov["category"] = category, category_source
    for source, values in (("attribute_model", predicted), ("user_confirmed", confirmed)):
        for key, value in (values or {}).items():
            v = str(value).strip().lower()
            if key not in ALLOWED or v not in ALLOWED[key]:
                raise ValueError("field not allowed by the schema: %s=%r" % (key, value))
            fields[key], prov[key] = v, source
    clean, problems = validate_fields(fields)
    return {"text": render(clean), "fields": clean, "provenance": prov,
            "category_only": all(clean[k] == "unknown" for k in ("color", "pattern", "sleeve_length")),
            "problems": problems, "schema_version": SCHEMA["version"], "never_claimed": SCHEMA["forbidden_claims"]}
