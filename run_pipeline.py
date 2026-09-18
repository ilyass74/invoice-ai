import argparse
import subprocess
import sys
from pathlib import Path

project_dir = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="Process one invoice image through the complete pipeline."
)

parser.add_argument(
    "image",
    nargs="?",
    default="data/invoice_demo.png",
    help="Path to the invoice image",
)

parser.add_argument(
    "--expected",
    help="Optional answer-key JSON; enables evaluation",
)

parser.add_argument("--skip-ocr", action="store_true", help="Reuse this image stem's existing OCR text and JSON for extraction debugging")
args = parser.parse_args()


def resolve_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


image_path = resolve_path(args.image)

if not image_path.is_file():
    parser.error(f"Image not found: {image_path}")

answer_key = None

if args.expected:
    answer_key = resolve_path(args.expected)

    if not answer_key.is_file():
        parser.error(f"Answer key not found: {answer_key}")

invoice_name = image_path.stem
output_dir = project_dir / "outputs"

text_path = output_dir / f"{invoice_name}_text.txt"
ocr_path = output_dir / f"{invoice_name}_res.json"
fields_path = output_dir / f"{invoice_name}_fields.json"
structured_path = output_dir / f"{invoice_name}_structured.json"
items_path = output_dir / f"{invoice_name}_items.json"

steps = [
    ("Read the image", "read_invoice.py", [image_path]),
    ("Extract fields", "extract_invoice.py", [text_path]),
    ("Extract names", "extract_parties.py", [ocr_path]),
    ("Extract line items", "extract_items.py", [text_path]),
    ("Combine header fields", "build_invoice.py", [fields_path]),
    ("Check invoice arithmetic", "verify_invoice.py", [structured_path]),
    ("Check line items and subtotal", "verify_items.py", [items_path]),
]

if args.skip_ocr:
    for cached in (text_path, ocr_path):
        if not cached.is_file(): parser.error(f"Missing cached OCR output: {cached}")
    steps = steps[1:]

if answer_key is not None:
    steps.extend([
        (
            "Evaluate header fields",
            "evaluate_invoice.py",
            [structured_path, answer_key],
        ),
        (
            "Evaluate line items",
            "evaluate_items.py",
            [structured_path, answer_key],
        ),
    ])
# Check all scripts before starting OCR.
for description, script, arguments in steps:
    if not (project_dir / script).is_file():
        parser.error(f"Required script not found: {script}")

for number, (description, script, arguments) in enumerate(steps, start=1):
    print(
        f"\nSTEP {number}/{len(steps)}: {description}",
        flush=True,
    )

    command = [
        sys.executable,
        str(project_dir / script),
        *[str(argument) for argument in arguments],
    ]

    result = subprocess.run(command, cwd=project_dir)

    if result.returncode != 0:
        print(f"\nStopped: {script} encountered an error.")
        sys.exit(result.returncode)

print(f"\nPipeline finished for: {image_path.name}")
print(f"Results folder: {output_dir}")
print("Review the reports for arithmetic and extraction findings.")