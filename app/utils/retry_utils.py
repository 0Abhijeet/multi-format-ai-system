import time

def retry_action(func, retries=3, delay=2):
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            print(f"[Retry {attempt+1}] Action failed: {e}")
            time.sleep(delay)
    print("[ERROR] All retries failed.")
    return None
