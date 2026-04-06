# src/core/services/history.py
from ..models import ChatMessage
from ..services.llm import LLMService
from ..ai_engine.prompts import HISTORY_COMPRESSOR_PROMPT

class HistoryManager:
    def __init__(self, session_id):
        self.session_id = session_id
        self.llm = LLMService()

    def get_optimized_history(self):
        """
        Returns a TUPLE: (summary_text, recent_messages_list)
        """
        queryset = ChatMessage.objects.filter(session_id=self.session_id).order_by('-created_at')[:10]
        full_history = list(reversed(queryset))

        if len(full_history) <= 4:
            # No summary needed, just return empty summary and full list
            return "", [{"role": msg.role, "content": msg.content} for msg in full_history]

        older_msgs = full_history[:-4]
        recent_msgs = full_history[-4:]

        # 1. Generate Summary
        transcript_text = ""
        for msg in older_msgs:
            transcript_text += f"{msg.role.upper()}: {msg.content}\n"

        summary = self._compress_transcript(transcript_text)
        
        # 2. Prepare Recent Messages
        recent_list = [{"role": msg.role, "content": msg.content} for msg in recent_msgs]

        return summary, recent_list

    def _compress_transcript(self, text):
        """
        Helper to run the LLM summarization.
        """
        messages = [
            {"role": "system", "content": "You are a summarizer."},
            {"role": "user", "content": HISTORY_COMPRESSOR_PROMPT.format(transcript=text)}
        ]
        try:
            # Quick non-streaming call
            response = self.llm.get_response(messages, stream=False)
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"History Compression Failed: {e}")
            return "" # Fail gracefully by returning nothing, or return raw text if preferred