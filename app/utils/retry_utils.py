import asyncio

async def retry_action(func, retries=3, delay=2):
    """
    Async now -- was time.sleep() in the original, which would block the
    event loop inside an async graph node (same class of bug as the
    fastembed/PDF-parsing issue in the RAG project: blocking I/O inside
    async code freezes every other concurrent request, not just this one).
    func itself is still a plain sync callable (post_to_crm/post_risk_alert
    are just print()+return, no real I/O) -- only the retry delay needed
    to become async.
    """
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            print(f"[Retry {attempt+1}] Action failed: {e}")
            await asyncio.sleep(delay)
    print("[ERROR] All retries failed.")
    return None