from datetime import datetime

memory_store = {
    "inputs": [],
    "extracted_data": [],
    "actions": [],
    "logs": [],
}

def log_input(source, classification):
    entry = {
        "source": source,
        "timestamp": datetime.utcnow().isoformat(),
        "classification": classification,
    }
    memory_store["inputs"].append(entry)
    print("[INPUT LOGGED]", entry)

def log_extracted(agent, data):
    entry = {
        "agent": agent,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data,
    }
    memory_store["extracted_data"].append(entry)
    print("[EXTRACTION LOGGED]", entry)

def log_action(action, reason):
    entry = {
        "action": action,
        "timestamp": datetime.utcnow().isoformat(),
        "reason": reason,
    }
    memory_store["actions"].append(entry)
    print("[ACTION LOGGED]", entry)

def log_trace(agent, step):
    entry = {
        "agent": agent,
        "timestamp": datetime.utcnow().isoformat(),
        "step": step,
    }
    memory_store["logs"].append(entry)
    print("[TRACE LOGGED]", entry)
