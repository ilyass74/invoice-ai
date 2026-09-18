import argparse
import json
from pathlib import Path
from invoice_parsing import extract_parties


def main():
    parser = argparse.ArgumentParser(description="Extract parties from OCR output.")
    parser.add_argument("input", nargs="?", default="outputs/invoice_demo_res.json")
    args = parser.parse_args()
    path = Path(args.input)
    if not path.is_absolute(): path = Path(__file__).resolve().parent / path
    if not path.name.endswith("_res.json"): parser.error("Expected a _res.json file")
    try:
        text = path.read_text(encoding="utf-8-sig")
        result = extract_parties(json.loads(text))
        from english_layout import parties as english_parties
        result = english_parties(json.loads(text)) or result
        output = path.with_name(path.name.removesuffix("_res.json") + "_parties.json")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
