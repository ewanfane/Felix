import json
from ..services.filesystem import FileSystemService
from ..services.llm import LLMService
from ..models import MemoryChunk
from pgvector.django import CosineDistance
from .prompts import SEARCH_QUERY_PROMPT, SANITIZER_PROMPT 
from core.services.embedding import EmbeddingService

# Router Prompt: Decides IF we need to read files
ROUTER_PROMPT = """
You are a Context Manager. 
User Query: "{user_query}"
Current Files:
{file_tree}

Do you need to READ any files to answer this query? 
- If YES, output a JSON list of paths: ["plans/v1.md"]
- If NO, output: []

JSON ONLY.
"""

class ContextManager:
    def __init__(self):
        self.fs = FileSystemService()
        self.llm = LLMService()
        self.embedder = EmbeddingService()


    def gather_context(self, user_query):
        """
        1. Router (Check Files)
        2. Vector Search (Check Memory)
        3. **Sanitizer (Refine Data)** <--- NEW STEP
        """
        # --- Step 1 & 2: Get Raw Data ---
        # (Using the methods we defined previously)
        raw_file_text = self._get_file_context(user_query)
        raw_memory_text = self._get_memory_context(user_query)
        
        # If we found nothing, return empty immediately to save an LLM call
        if not raw_file_text and not raw_memory_text:
            return ""

        # --- Step 3: The Sanitization Loop ---
        full_raw_dump = ""
        if raw_file_text:
            full_raw_dump += f"--- FROM FILES ---\n{raw_file_text}\n"
        if raw_memory_text:
            full_raw_dump += f"--- FROM MEMORY ---\n{raw_memory_text}\n"
            
        return self._sanitize_context(user_query, full_raw_dump)

    def _sanitize_context(self, user_query, raw_text):
        """
        Uses the LLM to condense the raw dump into a briefing.
        """
        # If the context is very small, don't waste time sanitizing it.
        if len(raw_text) < 500:
            return raw_text

        messages = [
            {"role": "system", "content": "You are a data analyst. Output clean facts only."},
            {"role": "user", "content": SANITIZER_PROMPT.format(
                user_query=user_query, 
                raw_context=raw_text
            )}
        ]
        
        try:
            # We use stream=False here because we need the full text before proceeding
            response = self.llm.get_response(messages, stream=False)
            cleaned_context = response.choices[0].message.content
            
            # Optional: Add a header so the main Agent knows this is processed data
            return f"### 🛡️ VERIFIED KNOWLEDGE BRIEF ###\n{cleaned_context}"
            
        except Exception as e:
            print(f"Sanitization Failed: {e}")
            # Fallback: Return raw text if the sanitizer crashes
            return raw_text

    def _get_file_context(self, user_query):
        # 1. Get Tree
        tree = self.fs.list_files()
        
        # 2. Ask Router
        router_msg = [{"role": "user", "content": ROUTER_PROMPT.format(user_query=user_query, file_tree=tree)}]
        resp = self.llm.get_response(router_msg, stream=False)
        
        try:
            clean_json = resp.choices[0].message.content.replace("```json", "").replace("```", "").strip()
            files_to_read = json.loads(clean_json)
        except:
            return "" # Fallback

        if not files_to_read:
            return ""

        # 3. Read & Format
        context_block = "\n### 📂 FILE CONTEXT ###\n"
        for path in files_to_read:
            content = self.fs.read_file(path)
            # Truncate strictly to prevent context overflow (simple summarization fallback)
            if len(content) > 5000:
                content = content[:5000] + "\n...[truncated]..."
            
            context_block += f"File: {path}\nContent:\n{content}\n---\n"
            
        return context_block



    def _get_memory_context(self, user_query):
        # 1. Rewrite Query
        recall_msg = [{"role": "user", "content": SEARCH_QUERY_PROMPT.format(user_input=user_query)}]
        search_query_resp = self.llm.get_response(recall_msg, stream=False)
        search_query = search_query_resp.choices[0].message.content.strip()
        
        print(f"🔍 Memory Search Query: {search_query}")

        # 2. Embed
        try:
            query_vector = self.embedder.embed_text(search_query)
        except Exception as e:
            print(f"❌ Embedding failed: {e}")
            return ""

        # 3. Search (pgvector)
        # INCREASE LIMIT AND LOG DISTANCES
        chunks = MemoryChunk.objects.annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:5]

        if not chunks:
            print("⚠️ No chunks found in database at all.")
            return ""

        memory_block = "\n### 🧠 INTERNAL MEMORY & REFLECTIONS ###\n"
        found_relevant = False

        for chunk in chunks:
            if chunk.distance > 0.5: 
                continue

            found_relevant = True
            
            # We explicitly label the content vs the reflection for the Sanitizer
            memory_block += f"CHUNK [{chunk.id}]:\n"
            memory_block += f"FACT: {chunk.content}\n"
            if chunk.reflection:
                memory_block += f"INTERNAL_REFLECTION: {chunk.reflection}\n"
            memory_block += "---\n"

        return memory_block if found_relevant else ""