"""
agent/model_config.py
---------------------
Dynamically routes between AWS Bedrock and Local (Ollama) providers.
"""
import os

def get_agent_kwargs() -> dict:
    mode = os.environ.get("SCOPEGUARD_MODE", "aws").lower()
    
    if mode == "local":
        return {
            "model": os.environ.get("LOCAL_MODEL_ID", "llama3"),
            "provider": os.environ.get("LOCAL_MODEL_PROVIDER", "ollama")
        }
    
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError(
            "BEDROCK_MODEL_ID is not set in the environment. "
            "If running locally, set SCOPEGUARD_MODE=local in your .env file."
        )
    return {"model": model_id}