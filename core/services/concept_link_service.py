import json
import re
from ..models import ConceptLink, MemoryChunk
from ..services.llm import LLMService
from ..ai_engine.prompts import CONCEPT_EXTRACTION_PROMPT


class ConceptLinkService:
    def __init__(self):
        self.llm = LLMService()

    def create_link(self, source_chunk_id, target_chunk_id, link_type="related", label="", metadata=None):
        try:
            source = MemoryChunk.objects.get(id=source_chunk_id)
            target = MemoryChunk.objects.get(id=target_chunk_id)
        except MemoryChunk.DoesNotExist:
            return None
        link, _ = ConceptLink.objects.get_or_create(
            source_chunk=source,
            target_chunk=target,
            link_type=link_type,
            defaults={"label": label, "metadata": metadata or {}},
        )
        return link

    def auto_link_chunk(self, chunk_id, max_links=5):
        try:
            chunk = MemoryChunk.objects.get(id=chunk_id)
        except MemoryChunk.DoesNotExist:
            return 0
        concepts = self._extract_concepts(chunk.content[:500])
        if not concepts:
            return 0
        linked = 0
        for concept in concepts[:max_links]:
            related = MemoryChunk.objects.filter(
                chunk_type="doc_pointer",
                is_active=True,
            ).exclude(id=chunk.id)[:30]
            for candidate in related:
                if self._concept_in_content(concept, candidate.content):
                    existing = ConceptLink.objects.filter(
                        source_chunk=chunk, target_chunk=candidate
                    ).exists()
                    if not existing:
                        self.create_link(
                            source_chunk_id=chunk.id,
                            target_chunk_id=candidate.id,
                            link_type="related",
                            label=concept,
                            metadata={"auto_linked": True, "concept": concept},
                        )
                        linked += 1
                    break
        return linked

    def _extract_concepts(self, text):
        try:
            prompt = CONCEPT_EXTRACTION_PROMPT.format(content=text)
            resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
            if resp and resp.choices:
                raw = resp.choices[0].message.content
                data = self._extract_json(raw)
                if data:
                    return data.get("concepts", [])
        except Exception:
            pass
        return []

    def _concept_in_content(self, concept, content):
        return concept.lower() in content.lower()

    def _extract_json(self, text):
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0), strict=False)
        except Exception:
            return None

    def get_links_for_chunk(self, chunk_id, link_type=None):
        filters = {}
        if link_type:
            filters["link_type"] = link_type
        outgoing = ConceptLink.objects.filter(source_chunk_id=chunk_id, **filters)
        incoming = ConceptLink.objects.filter(target_chunk_id=chunk_id, **filters)
        return list(outgoing) + list(incoming)

    def get_related_chunks(self, chunk_id, max_depth=1):
        seen = set()
        related = []
        queue = [chunk_id]
        for _ in range(max_depth):
            next_queue = []
            for cid in queue:
                if cid in seen:
                    continue
                seen.add(cid)
                links = ConceptLink.objects.filter(source_chunk_id=cid)
                for link in links:
                    if link.target_chunk_id not in seen:
                        related.append({
                            "chunk_id": link.target_chunk_id,
                            "link_type": link.link_type,
                            "label": link.label,
                        })
                        next_queue.append(link.target_chunk_id)
            queue = next_queue
        return related

    def delete_link(self, link_id):
        try:
            link = ConceptLink.objects.get(id=link_id)
            link.delete()
            return True
        except ConceptLink.DoesNotExist:
            return False
