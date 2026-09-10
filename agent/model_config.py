"""
agent/model_config.py
---------------------
Dynamically routes between AWS Bedrock and Local (Ollama) providers.
"""
import os

def get_agent_kwargs() -> dict:
    mode = os.environ.get("SCOPEGUARD_MODE", "aws").lower()
    
    if mode == "local":
        model_name = os.environ.get("LOCAL_MODEL_ID", "llama3")
        
        # Inject standard OpenAI environment variables so the Strands 
        # adapter automatically picks them up without throwing kwargs errors.
        os.environ["OPENAI_API_KEY"] = "ollama"
        os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
        
        from strands.models.openai import OpenAIModel
        
        # 1. The adapter strictly accepts 'model_id', not 'model'.
        adapter = OpenAIModel(model_id=model_name)
        
        # 2. The Agent base class expects the kwarg name to be 'model'.
        return {"model": adapter}

    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError(
            "BEDROCK_MODEL_ID is not set in the environment. "
            "If running locally, set SCOPEGUARD_MODE=local in your .env file."
        )
    return {"model": model_id}