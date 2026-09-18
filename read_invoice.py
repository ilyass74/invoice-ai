from pathlib import Path
from paddleocr import PaddleOCR
import argparse

# Locate the input and output folders beside this script.
project_dir = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(
    description="Read an invoice image with OCR."
)

parser.add_argument(
    "image",
    nargs="?",
    default="data/invoice_demo.png",
    help="Path to the invoice image",
)

args = parser.parse_args()

image_path = Path(args.image)

if not image_path.is_absolute():
    image_path = project_dir / image_path
output_dir = project_dir / "outputs"
output_dir.mkdir(exist_ok=True)

if not image_path.is_file():
    raise FileNotFoundError(f"Image not found: {image_path}")

print("Loading OCR models...")

ocr = PaddleOCR(
    lang="fr",
    device="cpu",
    enable_mkldnn=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)

print(f"Reading: {image_path.name}")

results = ocr.predict(str(image_path))

all_text = []

for result in results:
    result.save_to_json(str(output_dir))
    result.save_to_img(str(output_dir))

    for text in result["rec_texts"]:
        print(text)
        all_text.append(text)

text_path = output_dir / f"{image_path.stem}_text.txt"
text_path.write_text("\n".join(all_text), encoding="utf-8")

print(f"Finished. Results saved in: {output_dir}")