import json
import re
from datetime import datetime, timedelta
from django.utils import timezone
from ..models import MemoryChunk, ChatMessage, ConceptLink, LifecycleStage
from ..services.llm import LLMService
from ..services.filesystem import FileSystemService
from ..services.embedding import EmbeddingService
from ..services.project_knowledge_service import ProjectKnowledgeService, PROJECT_DOC_TYPES
from ..services.audit_service import AuditService
from ..services.concept_link_service import ConceptLinkService
from ..ai_engine.prompts import (
    CONTRADICTION_DETECTION_PROMPT,
    KNOWLEDGE_GAP_ANALYSIS_PROMPT,
    STALENESS_ASSESSMENT_PROMPT,
    CROSS_PROJECT_SYNTHESIS_PROMPT,
    CONCEPT_EXTRACTION_PROMPT,
    KNOWLEDGE_QUALITY_PROMPT,
    DECISION_EXTRACTION_PROMPT,
)


class KnowledgeMaintenanceService:
    def __init__(self):
        self.llm = LLMService()
        self.fs = FileSystemService()
        self.embedder = EmbeddingService()
        self.pks = ProjectKnowledgeService()
        self.audit = AuditService()
        self.cls = ConceptLinkService()

    def run_full_maintenance(self):
        results = []
        results.append(self.contradiction_scan())
        results.append(self.gap_analysis())
        results.append(self.staleness_check())
        results.append(self.quality_assessment())
        results.append(self.cross_project_linking())
        results.append(self.auto_concept_linking())
        results.append(self.auto_decision_extraction())
        return results

    def contradiction_scan(self):
        projects = self.pks.list_projects()
        if not projects:
            return "Contradiction scan: no projects"
        findings = []
        for project in projects:
            docs = {}
            for doc_type in PROJECT_DOC_TYPES:
                content = self.pks.read_doc(project, doc_type)
                if content and "Not yet documented" not in content:
                    docs[doc_type] = content[:1500]
            if len(docs) < 2:
                continue
            doc_text = "\n\n".join(f"--- {dt} ---\n{docs[dt]}" for dt in docs)
            prompt = CONTRADICTION_DETECTION_PROMPT.format(project_docs=doc_text)
            try:
                resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
                if resp and resp.choices:
                    raw = resp.choices[0].message.content
                    contradictions = self._extract_json_array(raw)
                    if contradictions:
                        for c in contradictions:
                            self.audit.log(
                                action_type="contradiction_detected",
                                target_model="ProjectKnowledge",
                                target_id=project,
                                summary=f"[{project}] Contradiction: {c.get('summary', '')[:200]}",
                                new_state={"project": project, "contradiction": c, "scan_type": "contradiction"},
                                approved=True,
                            )
                            findings.append(f"{project}: {c.get('summary', 'issue')[:80]}")
            except Exception as e:
                findings.append(f"{project}: scan error {e}")
        return f"Contradiction scan: {len(findings)} findings" if findings else "Contradiction scan: clean"

    def gap_analysis(self):
        projects = self.pks.list_projects()
        if not projects:
            return "Gap analysis: no projects"
        recent_cutoff = timezone.now() - timedelta(hours=72)
        recent_chunks = MemoryChunk.objects.filter(
            created_at__gte=recent_cutoff,
            is_active=True,
        ).order_by('-created_at')[:30]
        if not recent_chunks:
            return "Gap analysis: no recent conversation data"
        recent_text = "\n".join(f"- {c.content[:200]}" for c in recent_chunks)
        findings = []
        for project in projects:
            docs = {}
            for doc_type in PROJECT_DOC_TYPES:
                content = self.pks.read_doc(project, doc_type)
                if content and "Not yet documented" not in content:
                    docs[doc_type] = content[:800]
            doc_summary = "\n\n".join(f"{dt}: {docs[dt][:300]}" for dt in docs) if docs else "No docs yet"
            prompt = KNOWLEDGE_GAP_ANALYSIS_PROMPT.format(
                project_name=project,
                project_docs=doc_summary,
                recent_conversations=recent_text,
            )
            try:
                resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
                if resp and resp.choices:
                    raw = resp.choices[0].message.content
                    gaps = self._extract_json_array(raw)
                    if gaps:
                        for g in gaps:
                            self.audit.log(
                                action_type="knowledge_gap_found",
                                target_model="ProjectKnowledge",
                                target_id=project,
                                summary=f"[{project}] Gap: {g.get('summary', '')[:200]}",
                                new_state={"project": project, "gap": g, "scan_type": "gap"},
                                approved=True,
                            )
                            findings.append(f"{project}: {g.get('summary', 'gap')[:80]}")
            except Exception as e:
                findings.append(f"{project}: gap error {e}")
        return f"Gap analysis: {len(findings)} gaps found" if findings else "Gap analysis: no gaps"

    def staleness_check(self):
        projects = self.pks.list_projects()
        if not projects:
            return "Staleness check: no projects"
        findings = []
        for project in projects:
            for doc_type in PROJECT_DOC_TYPES:
                content = self.pks.read_doc(project, doc_type)
                if not content or "Not yet documented" in content:
                    continue
                doc_pointers = MemoryChunk.objects.filter(
                    chunk_type="doc_pointer",
                    is_active=True,
                    metadata__project=project,
                    metadata__doc_type=doc_type,
                ).order_by('-created_at')[:1]
                if not doc_pointers:
                    continue
                last_updated = doc_pointers[0].created_at
                days_old = (timezone.now() - last_updated).days
                if days_old < 30:
                    continue
                prompt = STALENESS_ASSESSMENT_PROMPT.format(
                    doc_content=content[:2000],
                    days_old=days_old,
                    doc_type=doc_type,
                    project=project,
                )
                try:
                    resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
                    if resp and resp.choices:
                        raw = resp.choices[0].message.content
                        stale_data = self._extract_json(raw)
                        if stale_data and stale_data.get("is_stale"):
                            self.audit.log(
                                action_type="stale_doc_found",
                                target_model="ProjectKnowledge",
                                target_id=f"{project}/{doc_type}",
                                summary=f"[{project}/{doc_type}] Stale ({days_old}d): {stale_data.get('reason', '')[:200]}",
                                new_state={
                                    "project": project, "doc_type": doc_type,
                                    "days_old": days_old, "assessment": stale_data,
                                    "scan_type": "staleness",
                                },
                                approved=True,
                            )
                            findings.append(f"{project}/{doc_type} ({days_old}d old)")
                except Exception:
                    pass
        return f"Staleness check: {len(findings)} stale docs" if findings else "Staleness check: all fresh"

    def quality_assessment(self):
        projects = self.pks.list_projects()
        if not projects:
            return "Quality assessment: no projects"
        findings = []
        for project in projects:
            for doc_type in PROJECT_DOC_TYPES:
                content = self.pks.read_doc(project, doc_type)
                if not content or "Not yet documented" in content:
                    continue
                if len(content.split()) < 30:
                    self.audit.log(
                        action_type="quality_issue",
                        target_model="ProjectKnowledge",
                        target_id=f"{project}/{doc_type}",
                        summary=f"[{project}/{doc_type}] Thin document ({len(content.split())} words)",
                        new_state={"project": project, "doc_type": doc_type, "word_count": len(content.split()),
                                   "scan_type": "quality"},
                        approved=True,
                    )
                    findings.append(f"{project}/{doc_type}: very thin ({len(content.split())} words)")
                    continue
                prompt = KNOWLEDGE_QUALITY_PROMPT.format(
                    doc_content=content[:2000],
                    doc_type=doc_type,
                    project=project,
                )
                try:
                    resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
                    if resp and resp.choices:
                        raw = resp.choices[0].message.content
                        quality = self._extract_json(raw)
                        if quality and quality.get("quality_score", 5) < 4:
                            self.audit.log(
                                action_type="quality_issue",
                                target_model="ProjectKnowledge",
                                target_id=f"{project}/{doc_type}",
                                summary=f"[{project}/{doc_type}] Quality: {quality.get('summary', 'needs improvement')[:200]}",
                                new_state={"project": project, "doc_type": doc_type,
                                           "quality": quality, "scan_type": "quality"},
                                approved=True,
                            )
                            findings.append(f"{project}/{doc_type}: score {quality.get('quality_score')}")
                except Exception:
                    pass
        return f"Quality assessment: {len(findings)} issues" if findings else "Quality assessment: OK"

    def cross_project_linking(self):
        projects = self.pks.list_projects()
        if len(projects) < 2:
            return "Cross-project linking: need 2+ projects"
        links_created = 0
        for i in range(len(projects)):
            for j in range(i + 1, len(projects)):
                p1, p2 = projects[i], projects[j]
                p1_docs = self.pks.get_project_summary(p1)
                p2_docs = self.pks.get_project_summary(p2)
                if not p1_docs or not p2_docs:
                    continue
                p1_text = "\n".join(f"{k}: {v[:500]}" for k, v in p1_docs.items())
                p2_text = "\n".join(f"{k}: {v[:500]}" for k, v in p2_docs.items())
                prompt = CROSS_PROJECT_SYNTHESIS_PROMPT.format(
                    project_a=p1, docs_a=p1_text,
                    project_b=p2, docs_b=p2_text,
                )
                try:
                    resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
                    if resp and resp.choices:
                        raw = resp.choices[0].message.content
                        connections = self._extract_json_array(raw)
                        if connections:
                            for conn in connections:
                                chunk_a = MemoryChunk.objects.filter(
                                    chunk_type="doc_pointer", is_active=True,
                                    metadata__project=p1,
                                    metadata__doc_type=conn.get("doc_type_a", "operations"),
                                ).first()
                                chunk_b = MemoryChunk.objects.filter(
                                    chunk_type="doc_pointer", is_active=True,
                                    metadata__project=p2,
                                    metadata__doc_type=conn.get("doc_type_b", "operations"),
                                ).first()
                                if chunk_a and chunk_b:
                                    self.cls.create_link(
                                        source_chunk_id=chunk_a.id,
                                        target_chunk_id=chunk_b.id,
                                        link_type=conn.get("link_type", "related"),
                                        label=conn.get("label", f"Cross-project: {p1} ↔ {p2}")[:200],
                                        metadata={"cross_project": True, "source_project": p1, "target_project": p2},
                                    )
                                    links_created += 1
                except Exception:
                    pass
        return f"Cross-project linking: {links_created} links created"

    def auto_concept_linking(self):
        unlinked = MemoryChunk.objects.filter(
            chunk_type="doc_pointer",
            is_active=True,
        ).order_by('?')[:15]
        linked_count = 0
        for chunk in unlinked:
            existing_links = ConceptLink.objects.filter(
                source_chunk=chunk
            ).count()
            if existing_links > 0:
                continue
            concepts = self._extract_concepts(chunk.content[:500])
            if not concepts:
                continue
            for concept in concepts[:5]:
                related = MemoryChunk.objects.filter(
                    chunk_type="doc_pointer",
                    is_active=True,
                ).exclude(id=chunk.id).order_by('?')[:20]
                for candidate in related:
                    if self._concept_in_content(concept, candidate.content):
                        self.cls.create_link(
                            source_chunk_id=chunk.id,
                            target_chunk_id=candidate.id,
                            link_type="related",
                            label=concept,
                            metadata={"auto_linked": True, "concept": concept},
                        )
                        linked_count += 1
                        break
        return f"Auto concept linking: {linked_count} links created"

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

    def auto_decision_extraction(self):
        recent_cutoff = timezone.now() - timedelta(hours=48)
        recent_msgs = ChatMessage.objects.filter(
            created_at__gte=recent_cutoff,
        ).order_by('-created_at')[:20]
        if len(recent_msgs) < 2:
            return "Decision extraction: insufficient conversation data"
        pairs = []
        i = 0
        while i < len(recent_msgs) - 1:
            if recent_msgs[i].role == "assistant" and recent_msgs[i+1].role == "user":
                pairs.append((recent_msgs[i+1].content, recent_msgs[i].content))
                i += 2
            else:
                i += 1
        if not pairs:
            return "Decision extraction: no user/assistant pairs found"
        for user_msg, ai_msg in pairs[:5]:
            try:
                prompt = DECISION_EXTRACTION_PROMPT.format(user_msg=user_msg, ai_msg=ai_msg)
                resp = self.llm.get_response([{"role": "user", "content": prompt}], stream=False)
                if resp and resp.choices:
                    raw = resp.choices[0].message.content
                    decisions = self._extract_json_array(raw)
                    if decisions:
                        from .decision_service import DecisionService
                        ds = DecisionService()
                        for d in decisions:
                            ds.create_decision(
                                project=d.get("project", "general"),
                                title=d.get("title", "Untitled decision"),
                                rationale=d.get("rationale", ""),
                                alternatives=d.get("alternatives", []),
                                context=d.get("context", ""),
                                tags=d.get("tags", []),
                            )
            except Exception:
                pass
        return f"Decision extraction: analyzed {len(pairs)} exchanges"

    def _extract_json(self, text):
        try:
            text = text.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0), strict=False)
        except Exception:
            return None
        return None

    def _extract_json_array(self, text):
        try:
            text = text.strip()
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                return json.loads(match.group(0), strict=False)
        except Exception:
            return None
        return None
