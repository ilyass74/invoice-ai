import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys

project_dir = Path(__file__).resolve().parent
if len(sys.argv) > 1:
    input_path = Path(sys.argv[1])
else:
    input_path = project_dir / "outputs" / "invoice_demo_fields.json"

output_path = input_path.with_name(input_path.stem + "_checks.json")

fields = json.loads(input_path.read_text(encoding="utf-8"))

try:
    amounts = {}

    for name in ("subtotal", "tax_amount", "total"):
        value = fields.get(name)

        if value is None:
            raise ValueError(f"Missing field: {name}")

        amount = Decimal(str(value))

        if not amount.is_finite():
            raise ValueError(f"Invalid amount: {name}")

        amounts[name] = amount

    discount = Decimal(str(fields.get("discount_amount", "0.00")))
    if not discount.is_finite() or discount < 0:
        raise ValueError("Discount must be a non-negative deduction")
    calculated_total = amounts["subtotal"] + amounts["tax_amount"] - discount
    difference = amounts["total"] - calculated_total

    report = {
        "check": "subtotal_plus_tax_minus_discount_equals_total",
        "status": "PASS" if difference == Decimal("0") else "FAIL",
        "calculated_total": str(calculated_total),
        "extracted_total": str(amounts["total"]),
        "difference": str(difference),
    }

except (InvalidOperation, ValueError) as error:
    report = {
        "check": "subtotal_plus_tax_minus_discount_equals_total",
        "status": "NEEDS_REVIEW",
        "reason": str(error),
    }

output_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps(report, ensure_ascii=False, indent=2))
print(f"Saved: {output_path}")