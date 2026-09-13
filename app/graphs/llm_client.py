import os
from groq import AsyncGroq

_client = None

def get_groq_client():
    """Lazy singleton, same pattern used throughout the RAG project
    (get_embeddings/get_bedrock_client/get_langfuse_client)."""
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client

MODEL = "openai/gpt-oss-20b"  # same model already used in the RAG project -- reused for consistency