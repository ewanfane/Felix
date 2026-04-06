from django.conf import settings
from openai import OpenAI

class EmbeddingService:
    def __init__(self):
        self.client = OpenAI(
            base_url=settings.OPENAI_API_BASE,
            api_key=settings.OPENAI_API_KEY
        )

    def embed_text(self, text):
        """
        Generates an embedding vector using LM Studio's endpoint.
        """
        try:
            # Clean newlines which can negatively affect embeddings
            text = text.replace("\n", " ")
            
            response = self.client.embeddings.create(
                input=[text],
                model=settings.EMBEDDING_MODEL_NAME
            )
            
            # Extract the vector (list of floats)
            return response.data[0].embedding
            
        except Exception as e:
            print(f"⚠️ Embedding Failed: {e}")
            # Fallback: Return a zero-vector or re-raise depending on your strategy
            # For now, we re-raise so the Celery task fails and retries
            raise e