import re

def extract_sender(email_text: str):
    match = re.search(r"From: (.*)", email_text)
    return match.group(1).strip() if match else "unknown"

def analyze_tone(email_text: str):
    if "angry" in email_text or "not happy" in email_text:
        return "angry", "high"
    elif "please" in email_text:
        return "polite", "medium"
    else:
        return "neutral", "low"

def process_email(raw_email: bytes):
    text = raw_email.decode("utf-8", errors="ignore")
    sender = extract_sender(text)
    tone, urgency = analyze_tone(text)
    action = "escalate" if tone == "angry" and urgency == "high" else "log"
    return {
        "sender": sender,
        "tone": tone,
        "urgency": urgency,
        "action": action,
    }