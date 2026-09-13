from langfuse import get_client

def get_langfuse_client():
    """Thin wrapper for consistency with get_groq_client() elsewhere in
    this project, and identical to the RAG project's own tracing.py.
    get_client() reads LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY/LANGFUSE_HOST
    from the environment and degrades gracefully (no exception) if they're
    missing -- same SDK, same verified behavior as the RAG project's step 3."""
    return get_client()