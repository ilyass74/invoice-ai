import argparse
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

project_dir = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="Check invoice line totals and subtotal."
)
parser.add_argument("input", help="Path to an _items.json file")
args = parser.parse_args()

items_path = Path(args.input)
if not items_path.is_absolute():
    items_path = project_dir / items_path

if not items_path.name.endswith("_items.json"):
    parser.error("Input filename must end with _items.json")

invoice_name = items_path.name.removesuffix("_items.json")
fields_path = items_path.with_name(f"{invoice_name}_fields.json")
output_path = items_path.with_name(f"{invoice_name}_items_checks.json")

for path in (items_path, fields_path):
    if not path.is_file():
        parser.error(f"File not found: {path}")


def number(value):
    if value is None:
        raise ValueError("Missing numeric value.")

    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Amount must be finite.")

    return result


try:
    items = json.loads(
        items_path.read_text(encoding="utf-8-sig")
    )["items"]

    fields = json.loads(
        fields_path.read_text(encoding="utf-8-sig")
    )

    if not isinstance(items, list) or not items:
        raise ValueError("No valid item list to check.")

    row_checks = []
    sum_of_line_totals = Decimal("0.00")

    for index, item in enumerate(items, start=1):
        quantity = number(item["quantity"])
        unit_price = number(item["unit_price"])
        extracted_total = number(item["line_total"])

        calculated_total = (quantity * unit_price).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        difference = extracted_total - calculated_total

        row_checks.append({
            "row": index,
            "description": item["description"],
            "status": "PASS" if difference == 0 else "FAIL",
            "calculated_total": str(calculated_total),
            "extracted_total": str(extracted_total),
            "difference": str(difference),
        })

        sum_of_line_totals += extracted_total

    subtotal = number(fields.get("subtotal"))
    subtotal_difference = subtotal - sum_of_line_totals

    subtotal_check = {
        "status": "PASS" if subtotal_difference == 0 else "FAIL",
        "sum_of_line_totals": str(sum_of_line_totals),
        "extracted_subtotal": str(subtotal),
        "difference": str(subtotal_difference),
    }

    all_passed = (
        all(row["status"] == "PASS" for row in row_checks)
        and subtotal_check["status"] == "PASS"
    )

    report = {
        "status": "PASS" if all_passed else "FAIL",
        "rounding": "Each calculated line rounded to 0.01, ROUND_HALF_UP",
        "rows": row_checks,
        "subtotal_check": subtotal_check,
    }

except (
    InvalidOperation,
    ValueError,
    KeyError,
    TypeError,
) as error:
    report = {
        "status": "NEEDS_REVIEW",
        "reason": str(error),
    }

output_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps(report, ensure_ascii=False, indent=2))
print(f"Saved: {output_path}")