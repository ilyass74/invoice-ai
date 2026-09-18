"""Local invoice review app. Run: python -m streamlit run app.py"""
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parent
LABELS = {
    "invoice_number": "Invoice number", "invoice_date": "Invoice date (YYYY-MM-DD)",
    "supplier_name": "Supplier", "customer_name": "Customer", "currency": "Currency",
    "discount_amount": "Discount amount (positive deduction)",
    "subtotal": "Subtotal", "tax_amount": "Tax amount", "total": "Total",
}
ITEM_FIELDS = ["description", "quantity", "unit_price", "line_total"]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def display_value(value):
    return "" if value is None else str(value)


def decimal_value(value, money=False):
    text = "".join(display_value(value).split()).replace(",", ".")
    # No exponent, currency symbols, negative values or mixed decimal separators.
    if not re.fullmatch(r"\d+(?:\.\d+)?", text) or len(text) > 20:
        raise ValueError("enter a non-negative number, for example 175.50")
    number = Decimal(text)
    if money and number != number.quantize(Decimal("0.01")):
        raise ValueError("use at most two decimal places for amounts")
    return number


def validate_invoice(raw):
    """Normalize a copy and recompute checks; never change original OCR data."""
    invoice = copy.deepcopy(raw)
    errors = []
    for field, label in LABELS.items():
        invoice[field] = display_value(raw.get(field, "0.00" if field == "discount_amount" else None)).strip()
        if not invoice[field]:
            errors.append(f"{label}: a value is required.")
    try:
        value = invoice["invoice_date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError()
        date.fromisoformat(value)
    except ValueError:
        errors.append("Invoice date: enter a valid date in YYYY-MM-DD format.")
    invoice["currency"] = invoice["currency"].upper()
    if invoice["currency"] not in {"MAD", "EUR"}:
        errors.append("This version supports MAD and EUR invoices.")
    for field in ("subtotal", "tax_amount", "total", "discount_amount"):
        try:
            invoice[field] = format(decimal_value(raw.get(field, "0.00" if field == "discount_amount" else None), money=True), ".2f")
        except (ValueError, InvalidOperation) as error:
            errors.append(f"{LABELS[field]}: {error}")
    items = raw.get("items", [])
    if not isinstance(items, list) or not items:
        errors.append("At least one line item is required.")
        items = []
    invoice["items"] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"Row {index}: invalid item data.")
            continue
        cleaned = {key: display_value(item.get(key)).strip() for key in ITEM_FIELDS}
        if not cleaned["description"]:
            errors.append(f"Row {index}: description is required.")
        for key in ("quantity", "unit_price", "line_total"):
            try:
                value = decimal_value(item.get(key), money=key != "quantity")
                if key == "quantity" and value <= 0:
                    raise ValueError("quantity must be greater than zero")
                cleaned[key] = str(value) if key == "quantity" else format(value, ".2f")
            except (ValueError, InvalidOperation) as error:
                errors.append(f"Row {index}, {key}: {error}")
        invoice["items"].append(cleaned)
    if errors:
        blocked = {"status": "NEEDS_REVIEW", "reason": "Correct the validation errors above."}
        return invoice, errors, {"arithmetic": dict(blocked), "items": dict(blocked)}
    subtotal, tax, total = (Decimal(invoice[k]) for k in ("subtotal", "tax_amount", "total"))
    discount = Decimal(invoice["discount_amount"])
    calculated_total = subtotal + tax - discount
    arithmetic = {
        "status": "PASS" if calculated_total == total else "FAIL",
        "discount_amount": str(discount), "calculated_total": str(calculated_total), "extracted_or_corrected_total": str(total),
        "difference": str(total - calculated_total),
    }
    row_checks = []
    sum_lines = Decimal("0.00")
    for index, item in enumerate(invoice["items"], 1):
        with localcontext() as context:
            context.prec = 60
            calculated = (Decimal(item["quantity"]) * Decimal(item["unit_price"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
        entered = Decimal(item["line_total"])
        sum_lines += entered
        row_checks.append({
            "row": index, "description": item["description"],
            "status": "PASS" if entered == calculated else "FAIL",
            "calculated_total": str(calculated), "entered_total": str(entered),
            "difference": str(entered - calculated),
        })
    item_check = {
        "status": "PASS" if sum_lines == subtotal and all(r["status"] == "PASS" for r in row_checks) else "FAIL",
        "rounding": "ROUND_HALF_UP to 0.01 per line",
        "rows": row_checks,
        "subtotal_check": {
            "status": "PASS" if sum_lines == subtotal else "FAIL",
            "sum_of_line_totals": str(sum_lines), "subtotal": str(subtotal),
            "difference": str(subtotal - sum_lines),
        },
    }
    return invoice, [], {"arithmetic": arithmetic, "items": item_check}


def record_changes(before, after):
    changes = []
    for field in LABELS:
        if before.get(field) != after.get(field):
            changes.append({"field": field, "before": before.get(field), "after": after.get(field)})
    old, new = before.get("items", []), after.get("items", [])
    for i in range(max(len(old), len(new))):
        a, b = (old[i] if i < len(old) else {}), (new[i] if i < len(new) else {})
        for field in ITEM_FIELDS:
            if a.get(field) != b.get(field):
                changes.append({"field": f"items[{i}].{field}", "before": a.get(field), "after": b.get(field)})
    return changes


def update_review_state(state, raw, review_key):
    """Invalidate approval after every committed change, including reverting it."""
    if state["last_candidate"] != raw:
        state["history"].append({"changed_at_utc": now(), "changes": record_changes(state["last_candidate"], raw)})
        state["last_candidate"] = copy.deepcopy(raw)
        st.session_state[review_key] = False


def save_approval(root, payload, image_bytes, extension):
    """Create a unique folder; publish invoice.json last, without renaming folders.

    Only a folder containing invoice.json is a completed approval. A process
    interruption can leave an incomplete folder, which must not be imported.
    """
    if extension not in {".png", ".jpg"}:
        raise ValueError("Unsupported source image extension")
    approval_id = uuid.uuid4().hex
    record = {**payload, "approval_id": approval_id, "saved_source": f"source{extension}"}
    serialized = json.dumps(record, ensure_ascii=False, indent=2)
    root.mkdir(parents=True, exist_ok=True)
    final = root / approval_id
    final.mkdir(exist_ok=False)
    try:
        with (final / record["saved_source"]).open("xb") as stream:
            stream.write(image_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_record = final / "invoice.pending.json"
        with temporary_record.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        # All handles are closed. Rename only the JSON file, never its directory.
        os.replace(temporary_record, final / "invoice.json")
    except OSError:
        shutil.rmtree(final, ignore_errors=True)
        raise
    return approval_id


def show_review(result, image_bytes, fingerprint, source_name, extension):
    original = result["invoice"]
    state = st.session_state["review_state"]
    revision = state["revision"]
    review_key = f"confirmed_{revision}"
    st.subheader("Review and correct")
    for warning in original.get("extraction_warnings", []):
        st.warning("Original extraction needs review: " + warning)
    if not original.get("supplier_name"):
        st.info("Supplier not identified reliably. Read its name from the image and enter it below.")
    st.caption("Edit a field and press Enter or click outside it. Checks update after each edit. Amounts accept a decimal comma or point.")
    raw = copy.deepcopy(original)
    for field, label in LABELS.items():
        raw[field] = st.text_input(label, value=display_value(original.get(field, "0.00" if field == "discount_amount" else None)), key=f"{revision}_{field}")
    st.subheader("Line items")
    rows = [{k: display_value(item.get(k)) for k in ITEM_FIELDS} for item in original.get("items", [])]
    frame = pd.DataFrame(rows, columns=ITEM_FIELDS).astype("string")
    edited = st.data_editor(frame, num_rows="dynamic", hide_index=True, width="stretch", key=f"items_{revision}",
                            column_config={k: st.column_config.TextColumn(k.replace("_", " ").title()) for k in ITEM_FIELDS})
    raw["items"] = edited.fillna("").to_dict("records")
    update_review_state(state, raw, review_key)
    invoice, errors, checks = validate_invoice(raw)
    for error in errors:
        st.error(error)
    st.subheader("Recalculated checks")
    for title, report in [("Subtotal + tax − discount = total", checks["arithmetic"]), ("Line totals and subtotal", checks["items"])]:
        status = report["status"]
        message = f"{title}: {status}"
        if status == "PASS":
            st.success(message)
        elif status == "FAIL":
            st.error(message)
        else:
            st.warning(message)
        with st.expander(f"{title} - details"):
            st.json(report)
    st.caption("Checks use quantity × unit price, two-decimal rounding and subtotal + tax minus the displayed discount amount. Enter discounts as positive deductions. Tax is taken from the document, not recomputed. Extra fees and credit notes are not supported. A PASS does not establish OCR accuracy or document authenticity.")
    with st.expander("Original extraction (unchanged)"):
        st.json(original)
    changes = record_changes(original, raw)
    with st.expander(f"Changes from original: {len(changes)}"):
        st.json(changes)
    st.download_button("Download current draft JSON", data=json.dumps(invoice, ensure_ascii=False, indent=2),
                       file_name="invoice_draft.json", mime="application/json")
    reviewed = st.checkbox("I compared every current field and item with the original image.", key=review_key)
    can_approve = not errors and all(r["status"] == "PASS" for r in checks.values())
    current_digest = digest(invoice)
    already_saved = state["saved"].get(current_digest)
    if st.button("Approve and save", disabled=not (reviewed and can_approve) or bool(already_saved)):
        # Revalidate the current candidate at the save boundary.
        invoice, errors, checks = validate_invoice(raw)
        if errors or any(r["status"] != "PASS" for r in checks.values()):
            st.error("Approval blocked. Correct the current values and review again.")
        else:
            payload = {
                "schema_version": 2, "status": "APPROVED", "approved_at_utc": now(),
                "review_method": "Manual confirmation in local app; reviewer identity not authenticated",
                "source_filename": source_name, "source_sha256": fingerprint,
                "pipeline_run": result.get("run_name"),
                "original_invoice": copy.deepcopy(original), "invoice": invoice,
                "original_checks": {"arithmetic": result["arithmetic"], "items": result["items_check"]},
                "checks": checks, "corrections": changes, "edit_history": copy.deepcopy(state["history"]),
            }
            try:
                already_saved = save_approval(PROJECT_DIR / "approved", payload, image_bytes, extension)
                state["saved"][current_digest] = already_saved
            except OSError as error:
                st.error(f"Saving failed: {error}")
    if already_saved:
        st.success(f"Reviewed invoice saved. Reference: {already_saved}")
    if not can_approve:
        st.info("Approval becomes available when required values are valid and all calculations pass.")
    st.caption("Unapproved edits are held in this browser session. Download the draft or approve it before closing. Reprocessing starts a fresh review. Duplicate prevention here applies only within this processing session.")


def main():
    st.set_page_config(page_title="Invoice AI", layout="wide")
    st.title("Invoice AI")
    st.write("Upload an invoice, correct its extracted data, and save it after review.")
    st.caption("Local prototype for supported French and English MAD/EUR invoice layouts.")
    uploaded = st.file_uploader("Choose an invoice image", type=["png", "jpg", "jpeg"], max_upload_size=10)
    if uploaded is None:
        st.session_state.pop("invoice_result", None)
        st.session_state.pop("review_state", None)
        return
    image_bytes = uploaded.getvalue()
    fingerprint = hashlib.sha256(image_bytes).hexdigest()
    if st.session_state.get("invoice_fingerprint") != fingerprint:
        st.session_state["invoice_fingerprint"] = fingerprint
        st.session_state.pop("invoice_result", None)
        st.session_state.pop("review_state", None)
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = image.format
            image.verify()
        if image_format not in {"PNG", "JPEG"}:
            raise ValueError("Unsupported image")
    except Exception:
        st.error("This file could not be read as a PNG or JPEG image.")
        return
    extension = ".png" if image_format == "PNG" else ".jpg"
    left, right = st.columns(2)
    with left:
        st.subheader("Original invoice")
        st.image(image_bytes, caption=uploaded.name)
    with right:
        if st.button("Process invoice", type="primary"):
            st.session_state.pop("invoice_result", None)
            st.session_state.pop("review_state", None)
            run_name = f"upload_{uuid.uuid4().hex}"
            try:
                upload_dir = PROJECT_DIR / "data" / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                image_path = upload_dir / f"{run_name}{extension}"
                image_path.write_bytes(image_bytes)
                environment = os.environ.copy()
                environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
                with st.spinner("Reading the invoice and checking calculations..."):
                    process = subprocess.run([sys.executable, str(PROJECT_DIR / "run_pipeline.py"), str(image_path)],
                                             cwd=PROJECT_DIR, env=environment, capture_output=True, text=True,
                                             encoding="utf-8", errors="replace")
                if process.returncode != 0:
                    st.error("Processing could not finish. The document may not match the supported layout.")
                    with st.expander("Error details"):
                        st.code(process.stdout + "\n" + process.stderr)
                else:
                    def read_output(suffix):
                        return json.loads((PROJECT_DIR / "outputs" / f"{run_name}{suffix}").read_text(encoding="utf-8"))
                    st.session_state["invoice_result"] = {
                        "run_name": run_name, "invoice": read_output("_structured.json"),
                        "arithmetic": read_output("_structured_checks.json"), "items_check": read_output("_items_checks.json"),
                    }
            except (OSError, ValueError) as error:
                st.error(f"Could not load processing results: {error}")
        result = st.session_state.get("invoice_result")
        if result:
            if "review_state" not in st.session_state:
                original = result["invoice"]
                initial = copy.deepcopy(original)
                for field in LABELS:
                    initial[field] = display_value(original.get(field, "0.00" if field == "discount_amount" else None))
                initial["items"] = [{k: display_value(item.get(k)) for k in ITEM_FIELDS} for item in original.get("items", [])]
                st.session_state["review_state"] = {"revision": uuid.uuid4().hex, "last_candidate": initial, "history": [], "saved": {}}
            show_review(result, image_bytes, fingerprint, uploaded.name, extension)


if __name__ == "__main__":
    main()
