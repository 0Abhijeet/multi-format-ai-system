import PyPDF2
import re

def extract_pdf_text(file: bytes):
    from io import BytesIO
    reader = PyPDF2.PdfReader(BytesIO(file))
    return "\n".join([page.extract_text() or "" for page in reader.pages])

def process_pdf(file: bytes):
    text = extract_pdf_text(file)
    total_match = re.search(r"Total: \$(\d+(?:\.\d{2})?)", text)
    total = float(total_match.group(1)) if total_match else 0
    flag = total > 10000
    compliance_terms = [t for t in ["Fire Code", "OSHA"] if t in text]
    return {
        "invoice_total": total,
        "flag_total_exceeds": flag,
        "compliance_terms": compliance_terms,
    }