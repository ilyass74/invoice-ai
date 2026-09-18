import argparse
import json
from pathlib import Path
from invoice_parsing import extract_fields


def main():
    parser = argparse.ArgumentParser(description="Extract fields from OCR output.")
    parser.add_argument("input", nargs="?", default="outputs/invoice_demo_text.txt")
    args = parser.parse_args()
    path = Path(args.input)
    if not path.is_absolute(): path = Path(__file__).resolve().parent / path
    if not path.name.endswith("_text.txt"): parser.error("Expected a _text.txt file")
    try:
        text = path.read_text(encoding="utf-8-sig")
        result = extract_fields(text)
        ocr_path = path.with_name(path.name.removesuffix("_text.txt") + "_res.json")
        if ocr_path.is_file():
            from english_layout import fields as english_fields, fields as english_extract
            ocr_data = json.loads(ocr_path.read_text(encoding="utf-8-sig"))
            if english_fields(ocr_data) is not None:
                result = english_extract(ocr_data)
        output = path.with_name(path.name.removesuffix("_text.txt") + "_fields.json")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
