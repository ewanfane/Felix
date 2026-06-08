from ..services.filesystem import FileSystemService
from ..services.llm import LLMService
from ..models import MemoryChunk
from pgvector.django import CosineDistance
from core.services.embedding import EmbeddingService
from .prompts import SEARCH_QUERY_PROMPT

GREETING_WORDS = {"hi", "hello", "hey", "greetings", "howdy", "yo", "sup", "what's up", "good morning", "good afternoon", "good evening"}
IDENTITY_KEYWORDS = ["my name", "who am i", "remember me", "what is my", "who i am", "about me", "do you know", "do you remember"]

PROFILE_PATHS = ["user/profile.md", "identity/personality.md", "user/goals.md", "user/preferences.md"]


class ContextManager:
    def __init__(self):
        self.fs = FileSystemService()
        self.embedder = EmbeddingService()
        self.llm = LLMService()

    def is_simple_query(self, user_query):
        q = user_query.lower().strip().rstrip("?!.")
        for word in GREETING_WORDS:
            if q == word or q.startswith(word + " "):
                return True
        if len(q.split()) <= 3 and "?" not in q:
            return True
        return False

    def gather_context(self, user_query):
        raw_memory_text = self._get_memory_context(user_query)
        raw_user_model_text = self._get_user_model_context(user_query)
        raw_file_text = self._get_file_context(user_query)

        parts = []
        if raw_user_model_text:
            parts.append(f"--- USER PROFILE ---\n{raw_user_model_text}")
        if raw_file_text:
            parts.append(f"--- FROM FILES ---\n{raw_file_text}")
        if raw_memory_text:
            parts.append(f"--- FROM MEMORY ---\n{raw_memory_text}")

        return "\n\n".join(parts)

    def _get_user_model_context(self, user_query):
        q = user_query.lower()
        is_identity_query = any(kw in q for kw in IDENTITY_KEYWORDS)
        if not is_identity_query:
            return ""

        for path in PROFILE_PATHS:
            content = self.fs.read_file(path)
            if content and not content.startswith("Error"):
                lines = [l for l in content.split("\n") if l.strip() and not l.startswith("#") and not l.startswith("##")]
                meaningful = [l for l in lines if ":" in l and l.split(":", 1)[1].strip()]
                if meaningful:
                    return "\n".join(meaningful)

        return ""

    def _get_file_context(self, user_query):
        file_keywords = ["personality", "learnings", "project", "knowledge", "knowledg"]
        if not any(kw in user_query.lower() for kw in file_keywords):
            return ""

        tree = self.fs.list_files()
        if not tree or "Directory is empty" in tree:
            return ""

        file_paths = [line.strip().rstrip("/") for line in tree.split("\n") if line.strip() and not line.strip().endswith("/")]
        if not file_paths:
            return ""

        context_block = ""
        for path in file_paths[:5]:
            content = self.fs.read_file(path)
            if content and not content.startswith("Error"):
                if len(content) > 2000:
                    content = content[:2000] + "\n...[truncated]..."
                context_block += f"File: {path}\nContent:\n{content}\n---\n"

        return context_block

    def _get_memory_context(self, user_query):
        search_query = self._generate_search_query(user_query)
        print(f"Memory Search: {search_query}")

        try:
            query_vector = self.embedder.embed_text(search_query)
        except Exception as e:
            print(f"Embedding failed: {e}")
            return ""

        chunks = MemoryChunk.objects.annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:12]

        if not chunks:
            return ""

        NEGATIVE_PATTERNS = ["no historical context", "lacks knowledge", "does not know", "no identity",
                             "no user identity", "starting fresh", "blank slate", "first time connecting",
                             "no personal information", "no context has been", "doesn't know",
                             "lacks specific", "not been provided", "initial state", "does not have"]
        memory_block = ""
        found_relevant = False

        for chunk in chunks:
            if chunk.distance > 0.6:
                continue
            content_lower = chunk.content.lower()
            if any(neg in content_lower for neg in NEGATIVE_PATTERNS) and chunk.distance > 0.4:
                continue
            found_relevant = True
            memory_block += f"CHUNK [{chunk.id}]:\nCONTENT: {chunk.content}\n"
            if chunk.reflection:
                memory_block += f"REFLECTION: {chunk.reflection}\n"
            memory_block += "---\n"

        if not found_relevant:
            name_chunks = MemoryChunk.objects.filter(content__icontains="Ewan")[:5]
            if name_chunks:
                for c in name_chunks:
                    memory_block += f"CHUNK [{c.id}]:\nCONTENT: {c.content}\n---\n"
                found_relevant = True

        return memory_block if found_relevant else ""

    def _generate_search_query(self, user_query):
        if len(user_query.split()) < 3:
            return user_query
        try:
            msg = [{"role": "user", "content": SEARCH_QUERY_PROMPT.format(user_input=user_query)}]
            resp = self.llm.get_response(msg, stream=False)
            if resp and resp.choices:
                return resp.choices[0].message.content.strip()
        except:
            pass
        return user_query
