import json

def validate_json(payload: dict, intent: str):
    schema_map = {
        "Webhook": {"id", "event", "timestamp"},
        "Invoice": {"invoice_id", "amount", "timestamp"},
        "Fraud Risk": {"fraud_flag", "account_id"},  # example
    }

    required_fields = schema_map.get(intent, set())
    missing = list(required_fields - payload.keys())

    return {
        "anomaly": bool(missing),
        "missing_fields": missing if missing else None
    }


def process_json(file_bytes: bytes):
    try:
        data = json.loads(file_bytes.decode("utf-8"))

        # Infer intent from data content (optional fallback)
        if "invoice_id" in data and "amount" in data:
            intent = "Invoice"
        elif "event" in data and "id" in data:
            intent = "Webhook"
        else:
            intent = "Unknown"

        validation_result = validate_json(data, intent)

        return {
            **validation_result,
            "data": data,
            "intent": intent  # Pass intent to the main router if needed
        }

    except Exception as e:
        return {"anomaly": True, "error": str(e)}
