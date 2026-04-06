from openai import OpenAI
from django.conf import settings

class LLMService:
    def __init__(self):
        self.client = OpenAI(
            base_url=settings.OPENAI_API_BASE,
            api_key=settings.OPENAI_API_KEY
        )

    def get_response(self, messages, stream=True):
        try:
            response = self.client.chat.completions.create(
                model=settings.LLM_MODEL_NAME, # Updated to ministral
                messages=messages,
                stream=stream,
                temperature=0.7,
            )
            return response
        except Exception as e:
            print(f"LLM Error: {e}")
            return None