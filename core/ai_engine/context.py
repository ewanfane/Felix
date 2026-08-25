from ..services.llm import LLMService
from ..models import MemoryChunk, ConceptLink
from pgvector.django import CosineDistance
from core.services.embedding import EmbeddingService
from core.services.core_memory_service import CoreMemoryService
from .prompts import SEARCH_QUERY_PROMPT

GREETING_WORDS = {"hi", "hello", "hey", "greetings", "howdy", "yo", "sup", "what's up", "good morning", "good afternoon", "good evening"}
MAX_ARCHIVAL_CHARS = 3000
MAX_POINTER_RESOLVE_CHARS = 2000
GRAPH_BOOST_FACTOR = 0.85


class ContextManager:
    def __init__(self):
        self.embedder = EmbeddingService()
        self.llm = LLMService()
        self.core_memory = CoreMemoryService()

    def is_simple_query(self, user_query):
        q = user_query.lower().strip().rstrip("?!.")
        for word in GREETING_WORDS:
            if q == word or q.startswith(word + " "):
                return True
        if len(q.split()) <= 3 and "?" not in q:
            return True
        return False

    def get_core_context(self):
        return self.core_memory.get_condensed_core()

    def gather_archival_context(self, user_query):
        search_query = self._generate_search_query(user_query)
        print(f"Archival Search: {search_query}")

        try:
            query_vector = self.embedder.embed_text(search_query)
        except Exception as e:
            print(f"Embedding failed: {e}")
            return ""

        chunks = list(MemoryChunk.objects.filter(
            memory_tier="archival",
            is_active=True,
        ).annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:12])

        if not chunks:
            return ""

        seen_ids = {c.id for c in chunks}
        linked_chunks = []

        for chunk in chunks[:6]:
            outgoing = ConceptLink.objects.filter(
                source_chunk=chunk
            ).select_related('target_chunk')[:3]
            for link in outgoing:
                tc = link.target_chunk
                if tc.id not in seen_ids and tc.is_active and tc.memory_tier == "archival":
                    linked_chunks.append({
                        "chunk": tc,
                        "distance": chunk.distance * GRAPH_BOOST_FACTOR,
                    })
                    seen_ids.add(tc.id)

        for lc in linked_chunks:
            chunks.append(lc["chunk"])

        chunks.sort(key=lambda c: c.distance if hasattr(c, 'distance') else 1.0)

        NEGATIVE_PATTERNS = ["no historical context", "no identity", "blank slate",
                             "starting fresh", "no personal information", "no context"]
        memory_block = ""
        found_relevant = False
        char_count = 0

        for chunk in chunks:
            if chunk.distance > 0.55:
                continue
            content_lower = chunk.content.lower()
            if any(neg in content_lower for neg in NEGATIVE_PATTERNS) and chunk.distance > 0.35:
                continue
            found_relevant = True

            if chunk.chunk_type == "doc_pointer" and chunk.target_file:
                resolved = self._resolve_pointer(chunk, remaining_budget=MAX_POINTER_RESOLVE_CHARS - char_count)
                if resolved:
                    memory_block += resolved + "\n---\n"
                    char_count += len(resolved)
                continue

            entry = f"[{chunk.id}]: {chunk.content}\n"
            if char_count + len(entry) > MAX_ARCHIVAL_CHARS:
                break
            memory_block += entry
            char_count += len(entry)

        if not found_relevant:
            return ""

        return memory_block

    def gather_important_context(self, user_query, top_k=3):
        search_query = self._generate_search_query(user_query)
        try:
            query_vector = self.embedder.embed_text(search_query)
        except Exception as e:
            print(f"Embedding failed: {e}")
            return ""

        chunks = list(MemoryChunk.objects.filter(
            memory_tier="archival",
            is_active=True,
        ).annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('-importance', 'distance')[:top_k])

        if not chunks:
            return ""

        parts = []
        for c in chunks:
            if c.distance > 0.6:
                continue
            label = f"[imp={c.importance:.1f}] {c.content[:200]}"
            parts.append(label)
        return "\n".join(parts) if parts else ""

    def _resolve_pointer(self, chunk, remaining_budget=2000):
        from ..services.filesystem import FileSystemService
        fs = FileSystemService()
        content = fs.read_file(chunk.target_file)
        if content and not content.startswith("Error"):
            label = chunk.target_file.replace("knowledge/projects/", "").replace(".md", "").replace("/", " → ")
            snippet = content[:remaining_budget]
            if len(content) > remaining_budget:
                snippet += "\n...[truncated]..."
            return f"📄 {label}\n{snippet}"
        return ""

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
