# Invoice AI

A local invoice extraction and review prototype built with Python, PaddleOCR and Streamlit.
Upload a PNG or JPEG, inspect extracted fields and line items, correct mistakes, check
arithmetic, and save an approval record with the original extraction and edit history.

## Features

- CPU OCR with PaddleOCR; MKL-DNN disabled for the tested Windows setup.
- Rule-based field extraction for the French and English layouts exercised in this project.
- MAD and EUR support, without currency conversion.
- Coordinate-based English table reconstruction, including multiline descriptions.
- Decimal arithmetic for line totals and subtotal + tax - discount.
- Editable fields and items; approval blocked when required data or arithmetic is invalid.
- Original and reviewed data, timestamps, source hash and edit history saved locally.
- Command-line pipeline and optional comparison with a manually verified answer key.

## How it works

`read_invoice.py` produces OCR text and bounding boxes. The extraction scripts turn those
outputs into fields, parties and items; `build_invoice.py` combines them. Verification
scripts check arithmetic. `app.py` provides image review, corrections and approval.
The OCR uses pretrained AI models; the field extraction layer uses explicit rules.
No LLM or paid API is used by this implementation.

## Run on Windows

The author used Python 3.13.3 and Streamlit 1.64.0 on Windows. Dependencies in
`requirements.txt` are compatibility ranges, not a reproducible environment lock.
A fresh installation from these ranges has not been verified here.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run .\app.py --server.address 127.0.0.1
```

Open the URL printed by Streamlit. OCR models download on first use and are cached.
Upload an image, click **Process invoice**, compare every field with the image, correct
as needed, tick the review confirmation and click **Approve and save**.
Enter a discount as a positive deduction. Displayed tax is used as supplied; tax rules
are not inferred. Editing a field invalidates the previous review confirmation.

Only folders containing a completed `invoice.json` under `approved/` represent completed
saves. Reviewer identity is not authenticated. This is a local prototype.

## CLI

Place your own sample image in a local `data/` folder:

```powershell
.\.venv\Scripts\python.exe .\run_pipeline.py .\data\sample.png
.\.venv\Scripts\python.exe .\run_pipeline.py .\data\sample.png --expected .\data\sample_expected.json
```

`--skip-ocr` reuses existing OCR outputs with the same image stem for debugging.
The answer key is a JSON object with the eight header fields and an `items` array;
each item has description, quantity, unit_price and line_total. See the field names
in `evaluate_invoice.py` and `evaluate_items.py`. The header evaluator currently
scores eight original fields and does not score the later-added discount field.

## Tests and evidence

Run the dependency-free parser and subprocess replay tests:

```powershell
python -m unittest -v test_regression test_english
```

13 tests passed during preparation of this release. They cover known French samples,
English OCR replay, multiline items, ambiguous dates, missing numeric cells and recovery
from unsupported tables. The English fixture retains OCR text and boxes only; local
paths and model metadata have been removed. It is a user-supplied RedmineCRM sample,
not a representative invoice benchmark. Original artwork is not included.

The author confirmed local processing and approval saving. Exported values from the
English sample matched its image, with the date order inferred from the due date.
These are development/regression results, not a claim of general OCR accuracy.

Initial unfamiliar-document checks also exposed limitations: the Elevate quote returned
empty fields/items; results for the other two submitted templates were not yet available
when this version was packaged. No broad accuracy percentage is claimed.

## Limitations

- Layout-specific extraction; unfamiliar layouts can return incomplete results.
- French four-column and English six-column service tables are covered as tested.
- MAD/EUR only; ambiguous dollar symbols are not assumed to mean USD.
- Ambiguous dates require review; date inferences should be confirmed.
- Quotes are not explicitly classified. Do not approve a quote as an invoice.
- No general handling of fees, complex taxes, credit notes or multipage PDFs.
- An arithmetic PASS does not prove OCR accuracy or document authenticity.
- Drafts can contain default zero discounts; these are not evidence of OCR extraction.

## Project files

| Files | Purpose |
| --- | --- |
| `app.py` | Upload, correction, validation and approval UI |
| `read_invoice.py` | Image OCR |
| `invoice_parsing.py`, `english_layout.py` | Extraction rules |
| `extract_*.py`, `build_invoice.py` | CLI extraction and assembly |
| `verify_*.py` | Arithmetic checks |
| `evaluate_*.py` | Comparison with answer keys |
| `run_pipeline.py` | Pipeline orchestration |
| `test_*.py`, `test_data/` | Regression tests and fixture |

Generated invoices, uploaded images, outputs, approval records, environment files and
model caches should stay local. The supplied `.gitignore` excludes project data folders.

## References

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- [Streamlit](https://docs.streamlit.io/)
- [Python Decimal](https://docs.python.org/3/library/decimal.html)

Project behavior and validation claims above are grounded in the included source and tests.
