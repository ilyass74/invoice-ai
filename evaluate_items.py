import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

project_dir = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="Compare extracted invoice items with verified answers."
)
parser.add_argument("prediction", help="Structured invoice JSON")
parser.add_argument("answer_key", help="Verified answer-key JSON")
args = parser.parse_args()


def load_json(value):
    path = Path(value)
    if not path.is_absolute():
        path = project_dir / path

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"Cannot read {path.name}: {error}")

    if not isinstance(data, dict):
        parser.error(f"{path.name} must contain a JSON object.")

    return path, data


prediction_path, predicted = load_json(args.prediction)
answer_key_path, expected = load_json(args.answer_key)

item_fields = ["description", "quantity", "unit_price", "line_total"]
numeric_fields = {"quantity", "unit_price", "line_total"}

expected_items = expected.get("items")
predicted_items = predicted.get("items", [])

if not isinstance(expected_items, list) or not expected_items:
    parser.error("The answer key must contain a non-empty items list.")

if not isinstance(predicted_items, list):
    parser.error("Predicted items must be a list.")

for index, item in enumerate(expected_items, start=1):
    if not isinstance(item, dict):
        parser.error(f"Answer-key item {index} must be an object.")

    for field in item_fields:
        value = item.get(field)

        if value is None or not str(value).strip():
            parser.error(f"Missing answer: item {index}, {field}")

        if field in numeric_fields:
            try:
                if not Decimal(str(value)).is_finite():
                    raise ValueError("Non-finite number")
            except (InvalidOperation, ValueError):
                parser.error(f"Invalid answer: item {index}, {field}")


def matches(field, actual, reference):
    if actual is None or reference is None:
        return False

    if field in numeric_fields:
        try:
            actual_number = Decimal(str(actual))
            return (
                actual_number.is_finite()
                and actual_number == Decimal(str(reference))
            )
        except InvalidOperation:
            return False

    return " ".join(str(actual).split()) == " ".join(str(reference).split())


results = []

# Include extra predicted rows so they also count against the score.
row_count = max(len(expected_items), len(predicted_items))

for index in range(row_count):
    reference = (
        expected_items[index] if index < len(expected_items) else {}
    )
    actual = (
        predicted_items[index] if index < len(predicted_items) else {}
    )

    if not isinstance(actual, dict):
        actual = {}

    for field in item_fields:
        correct = matches(field, actual.get(field), reference.get(field))

        results.append({
            "row": index + 1,
            "field": field,
            "expected": reference.get(field),
            "predicted": actual.get(field),
            "correct": correct,
        })

        status = "CORRECT" if correct else "INCORRECT"
        print(f"Item {index + 1} - {field}: {status}")

correct_count = sum(result["correct"] for result in results)
comparison_count = len(results)
accuracy = correct_count / comparison_count * 100

report = {
    "scope": "One invoice; items matched by row order",
    "expected_item_count": len(expected_items),
    "predicted_item_count": len(predicted_items),
    "correct_fields": correct_count,
    "evaluated_fields": comparison_count,
    "item_field_accuracy_percent": accuracy,
    "results": results,
}

invoice_name = prediction_path.stem.removesuffix("_structured")
output_path = prediction_path.with_name(
    f"{invoice_name}_items_evaluation.json"
)

output_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"\nCorrect item fields: {correct_count}/{comparison_count}")
print(f"Item field accuracy on this invoice: {accuracy:.1f}%")
print(f"Saved: {output_path}")