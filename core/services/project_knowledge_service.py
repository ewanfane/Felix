import re
import json
from ..services.filesystem import FileSystemService
from ..services.llm import LLMService
from ..services.embedding import EmbeddingService
from ..models import MemoryChunk
from .audit_service import AuditService
from pgvector.django import CosineDistance

PROJECT_DOC_TYPES = [
    "vision",
    "architecture",
    "schemas",
    "decisions",
    "roadmap",
    "operations",
]

PROJECT_ROOT = "knowledge/projects"


class ProjectKnowledgeService:
    def __init__(self):
        self.fs = FileSystemService()
        self.llm = LLMService()
        self.embedder = EmbeddingService()
        self.audit = AuditService()

    def get_project_path(self, project_name, doc_type=None):
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name.lower())[:40]
        if doc_type:
            return f"{PROJECT_ROOT}/{safe_name}/{doc_type}.md"
        return f"{PROJECT_ROOT}/{safe_name}"

    def ensure_project_structure(self, project_name):
        base = self.get_project_path(project_name)
        self.fs.write_file(f"{base}/.placeholder", "")
        for doc_type in PROJECT_DOC_TYPES:
            path = f"{base}/{doc_type}.md"
            existing = self.fs.read_file(path)
            if not existing or existing.startswith("Error"):
                self.fs.write_file(path, f"# {project_name.title()} — {doc_type.title()}\n\n_Not yet documented._\n")

    def read_doc(self, project_name, doc_type):
        path = self.get_project_path(project_name, doc_type)
        content = self.fs.read_file(path)
        if content and not content.startswith("Error"):
            return content
        return None

    def write_doc(self, project_name, doc_type, content):
        path = self.get_project_path(project_name, doc_type)

        self.fs.write_file(path, content)
        self._create_doc_pointer(project_name, doc_type, content)

        self.audit.log(
            action_type="project_doc_write",
            target_model="ProjectKnowledge",
            target_id=path,
            summary=f"Written {path}",
            new_state={"snippet": content[:200]},
        )
        return f"Written to {path}"

    def _create_doc_pointer(self, project_name, doc_type, content):
        summary = content[:300].replace("\n", " ").strip()
        pointer_text = f"[{project_name}/{doc_type}] {summary}"

        try:
            vector = self.embedder.embed_text(pointer_text)
            MemoryChunk.objects.create(
                content=pointer_text,
                embedding=vector,
                chunk_type="doc_pointer",
                memory_tier="archival",
                target_file=self.get_project_path(project_name, doc_type),
                consolidated=True,
                is_active=True,
                metadata={
                    "topic": f"{project_name}:{doc_type}",
                    "type": "doc_pointer",
                    "project": project_name,
                    "doc_type": doc_type,
                },
            )
        except Exception:
            pass

    def find_related_docs(self, query, project_name=None, limit=5):
        try:
            query_vector = self.embedder.embed_text(query)
            filters = {"chunk_type": "doc_pointer", "is_active": True}
            if project_name:
                filters["metadata__project"] = project_name

            chunks = MemoryChunk.objects.filter(**filters).annotate(
                distance=CosineDistance('embedding', query_vector)
            ).order_by('distance')[:limit]

            results = []
            for c in chunks:
                if c.distance < 0.6:
                    content = self.fs.read_file(c.target_file) if c.target_file else ""
                    results.append({
                        "file": c.target_file,
                        "summary": c.content,
                        "content_snippet": (content[:500] + "...") if content and len(content) > 500 else content,
                    })
            return results
        except Exception:
            return []

    def list_projects(self):
        import os
        from pathlib import Path
        base_path = self.fs.root_path / PROJECT_ROOT
        if not base_path.exists():
            return []
        projects = set()
        for item in base_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                projects.add(item.name)
        return sorted(projects)

    def get_project_summary(self, project_name):
        docs = {}
        for doc_type in PROJECT_DOC_TYPES:
            content = self.read_doc(project_name, doc_type)
            if content and "Not yet documented" not in content:
                docs[doc_type] = content[:400]
        return docs

    def detect_contradictions(self, project_name, new_content, doc_type):
        related = self.find_related_docs(new_content, project_name=project_name, limit=3)
        contradictions = []
        for doc in related:
            if doc["file"] and doc_type not in doc["file"]:
                if doc["content_snippet"]:
                    contradictions.append({
                        "existing_file": doc["file"],
                        "existing_snippet": doc["content_snippet"][:200],
                    })
        return contradictions
