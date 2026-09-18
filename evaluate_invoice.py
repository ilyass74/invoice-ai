import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

project_dir = Path(__file__).resolve().parent

# Accept filenames while preserving the original sample as the default.
parser = argparse.ArgumentParser(
    description="Compare extracted invoice fields against an answer key."
)

parser.add_argument(
    "prediction",
    nargs="?",
    default="outputs/invoice_demo_structured.json",
    help="Path to the structured invoice JSON",
)

parser.add_argument(
    "answer_key",
    nargs="?",
    help="Path to the verified answer-key JSON",
)

args = parser.parse_args()


def resolve_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


prediction_path = resolve_path(args.prediction)

# Use the demo answer key only for the default demo prediction.
if args.answer_key:
    answer_key_path = resolve_path(args.answer_key)
elif prediction_path == resolve_path(
    "outputs/invoice_demo_structured.json"
):
    answer_key_path = resolve_path("data/invoice_expected.json")
else:
    parser.error("Supply an answer-key file for this invoice.")


def load_json(path):
    if not path.is_file():
        parser.error(f"File not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"Cannot read {path.name}: {error}")

    if not isinstance(data, dict):
        parser.error(f"{path.name} must contain a JSON object.")

    return data


predicted = load_json(prediction_path)
expected = load_json(answer_key_path)

fields_to_check = [
    "invoice_number",
    "invoice_date",
    "currency",
    "subtotal",
    "tax_amount",
    "total",
    "supplier_name",
    "customer_name",
]

money_fields = {"subtotal", "tax_amount", "total"}

# An incomplete answer key cannot support this eight-field evaluation.
missing_answers = [
    field
    for field in fields_to_check
    if expected.get(field) is None
    or str(expected[field]).strip() == ""
]

if missing_answers:
    parser.error(
        "Answer key is missing values for: "
        + ", ".join(missing_answers)
    )

for field in money_fields:
    try:
        value = Decimal(str(expected[field]))
        if not value.is_finite():
            raise ValueError("Amount must be finite.")
    except (InvalidOperation, ValueError):
        parser.error(f"Invalid answer-key amount: {field}")


def values_match(field, actual, reference):
    if actual is None:
        return False

    if field in money_fields:
        try:
            actual_number = Decimal(str(actual))
            reference_number = Decimal(str(reference))

            return (
                actual_number.is_finite()
                and actual_number == reference_number
            )
        except InvalidOperation:
            return False

    # Ignore extra whitespace; preserve spelling and capitalization.
    actual_text = " ".join(str(actual).split())
    reference_text = " ".join(str(reference).split())
    return actual_text == reference_text


results = []

for field in fields_to_check:
    reference = expected[field]
    actual = predicted.get(field)
    correct = values_match(field, actual, reference)

    results.append({
        "field": field,
        "expected": reference,
        "predicted": actual,
        "correct": correct,
    })

    status = "CORRECT" if correct else "INCORRECT"
    print(f"{field}: {status}")

    if not correct:
        print(f"  Expected: {reference!r}")
        print(f"  Predicted: {actual!r}")

correct_count = sum(result["correct"] for result in results)
field_count = len(fields_to_check)
accuracy = correct_count / field_count * 100

report = {
    "scope": "One invoice; eight selected fields",
    "prediction_file": str(prediction_path),
    "answer_key_file": str(answer_key_path),
    "correct_fields": correct_count,
    "evaluated_fields": field_count,
    "field_accuracy_percent": accuracy,
    "results": results,
}

invoice_name = prediction_path.stem.removesuffix("_structured")
output_path = prediction_path.with_name(
    f"{invoice_name}_evaluation.json"
)

output_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"\nCorrect fields: {correct_count}/{field_count}")
print(f"Field accuracy on this invoice: {accuracy:.1f}%")
print(f"Saved: {output_path}")