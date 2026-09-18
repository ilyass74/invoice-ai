import argparse
import json
from pathlib import Path

project_dir = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="Combine invoice fields, names, and line items."
)

parser.add_argument(
    "input",
    nargs="?",
    default="outputs/invoice_demo_fields.json",
    help="Path to an extracted file ending in _fields.json",
)

args = parser.parse_args()

fields_path = Path(args.input)

if not fields_path.is_absolute():
    fields_path = project_dir / fields_path

if not fields_path.name.endswith("_fields.json"):
    parser.error("The input filename must end with _fields.json")

invoice_name = fields_path.name.removesuffix("_fields.json")

parties_path = fields_path.with_name(f"{invoice_name}_parties.json")
items_path = fields_path.with_name(f"{invoice_name}_items.json")
output_path = fields_path.with_name(f"{invoice_name}_structured.json")


def load_json(path):
    if not path.is_file():
        parser.error(f"Required file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"Cannot read {path.name}: {error}")

    if not isinstance(data, dict):
        parser.error(f"{path.name} must contain a JSON object.")

    return data


fields = load_json(fields_path)
parties = load_json(parties_path)
items_data = load_json(items_path)

items = items_data.get("items")

if not isinstance(items, list):
    parser.error("The items file must contain an items list.")

required_item_fields = {
    "description",
    "quantity",
    "unit_price",
    "line_total",
}

for index, item in enumerate(items, start=1):
    if not isinstance(item, dict):
        parser.error(f"Item {index} must be a JSON object.")

    missing = required_item_fields - item.keys()

    if missing:
        parser.error(
            f"Item {index} is missing: {', '.join(sorted(missing))}"
        )

invoice = {
    **fields,
    **parties,
    "items": items,
    "extraction_warnings": fields.get("extraction_warnings", []) + items_data.get("warnings", []),
}

output_path.write_text(
    json.dumps(invoice, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps(invoice, ensure_ascii=False, indent=2))
print(f"\nIncluded items: {len(items)}")
print(f"Saved: {output_path}")