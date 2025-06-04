import re

def classify(input_data: bytes, filename: str) -> dict:
    """
    Classifies the input data by format and business intent.

    Args:
        input_data (bytes): Raw content of the file/email.
        filename (str): Name of the file to help detect format.

    Returns:
        dict: Contains 'format' and 'intent' keys.
    """

    # Detect format based on filename extension
    if filename:
        if filename.endswith(".json"):
            format_type = "JSON"
        elif filename.endswith(".pdf"):
            format_type = "PDF"
        elif filename.endswith(".eml") or filename.endswith(".txt"):
            format_type = "Email"
        else:
            format_type = "Unknown"
    else:
        format_type = "Unknown"

    # Decode content safely
    content = input_data.decode("utf-8", errors="ignore")

    # Simple regex-based intent detection
    if re.search(r"quote|pricing|rfq", content, re.IGNORECASE):
        intent = "RFQ"
    elif re.search(r"complaint|angry|not happy|bad service", content, re.IGNORECASE):
        intent = "Complaint"
    elif re.search(r"invoice|amount due", content, re.IGNORECASE):
        intent = "Invoice"
    elif re.search(r"regulation|compliance|GDPR|FDA", content, re.IGNORECASE):
        intent = "Regulation"
    elif re.search(r"fraud|unauthorized|suspicious", content, re.IGNORECASE):
        intent = "Fraud Risk"
    else:
        intent = "Unknown"

    return {
        "format": format_type,
        "intent": intent,
    }
