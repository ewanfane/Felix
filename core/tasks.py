import json
from celery import shared_task
from .models import ChatMessage, MemoryChunk, LifecycleStage
from .services.llm import LLMService
from .services.embedding import EmbeddingService
from .services.filesystem import FileSystemService
from .services.scribe import ScribeService
from .services.file_manager import FileManager
from .services.project_knowledge_service import ProjectKnowledgeService
from .ai_engine.prompts import USER_CHUNKING_PROMPT, AI_CHUNKING_PROMPT, FILE_OPS_PROMPT, PROJECT_CLASSIFIER_PROMPT
from .services.utils import parse_chunking_output


def extract_json(raw_text):
    try:
        start_index = raw_text.find('[')
        end_index = raw_text.rfind(']')
        if start_index == -1 or end_index == -1:
            start_index = raw_text.find('{')
            end_index = raw_text.rfind('}')
        if start_index == -1:
            return None
        json_str = raw_text[start_index: end_index + 1]
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_xml_tag(text, tag):
    import re
    match = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


@shared_task
def process_message_for_memory(message_id):
    try:
        message = ChatMessage.objects.get(id=message_id)
        if message.processed:
            return "Already Processed"

        llm = LLMService()
        fs = FileSystemService()

        if message.role == 'user':
            prev_ai = ChatMessage.objects.filter(
                session=message.session,
                role='assistant',
                created_at__lt=message.created_at
            ).order_by('-created_at').first()

            if prev_ai:
                context_payload = f"AI PREVIOUS RESPONSE: \"{prev_ai.content}\"\nUSER REPLY: \"{message.content}\""
            else:
                context_payload = f"USER INPUT: \"{message.content}\""

            prompt = USER_CHUNKING_PROMPT.format(user_input=context_payload)
            system_role = "You are a User Insight Extractor."
        else:
            prompt = AI_CHUNKING_PROMPT.format(ai_response=message.content)
            system_role = "You are an AI Memory Extractor."

        messages = [
            {"role": "system", "content": f"{system_role} Output strict XML."},
            {"role": "user", "content": prompt},
        ]
        response = llm.get_response(messages, stream=False)

        chunk_data = parse_chunking_output(response.choices[0].message.content)

        if chunk_data["skip"]:
            message.processed = True
            message.save()
            return "Skipped (Trivial)"

        if not chunk_data["content"]:
            return "Failed: No content tag found."

        embedder = EmbeddingService()
        vector = embedder.embed_text(chunk_data['content'])

        content_len = len(chunk_data['content'])
        if content_len > 200:
            importance = 0.7
        elif content_len > 80:
            importance = 0.5
        else:
            importance = 0.3
        topic_count = len(chunk_data.get('metadata', {}).get('topics', []))
        if topic_count >= 3:
            importance = min(1.0, importance + 0.2)

        MemoryChunk.objects.create(
            content=chunk_data['content'],
            embedding=vector,
            chunk_type="raw",
            memory_tier="archival",
            lifecycle_stage=LifecycleStage.INBOX,
            consolidated=False,
            is_active=True,
            importance=importance,
            metadata=chunk_data['metadata'],
            source_message=message,
        )

        message.processed = True
        message.save()
        return "Success: Created 1 raw scratchpad chunk"

    except Exception as e:
        return f"Memory Task Error: {str(e)}"


PATH_TO_CATEGORY = {
    "user": "user_profile",
    "identity": "user_profile",
    "profile": "user_profile",
    "preference": "user_preferences",
    "goal": "user_goals",
    "agent": "agent_identity",
    "ontology": "agent_identity",
    "capability": "agent_capabilities",
    "project": "project",
    "projects": "project",
}


def _map_old_path_to_category(path):
    path_lower = path.lower().replace("\\", "/")
    for keyword, category in PATH_TO_CATEGORY.items():
        if keyword in path_lower:
            return category
    return "user_profile"


def _extract_project_name(path):
    parts = path.replace("\\", "/").split("/")
    for i, p in enumerate(parts):
        if p.lower() in ("projects", "project") and i + 1 < len(parts):
            return parts[i + 1].replace(".md", "")
    return "general"


@shared_task
def perform_file_operations(user_msg_content, ai_msg_content):
    try:
        llm = LLMService()
        prompt = FILE_OPS_PROMPT.format(user_msg=user_msg_content, ai_msg=ai_msg_content)
        messages = [{"role": "user", "content": prompt}]
        response = llm.get_response(messages, stream=False)
        actions = extract_json(response.choices[0].message.content)

        if not actions:
            return "No valid file actions found in response."

        fm = FileManager()
        results = []
        for act in actions:
            category = act.get('category', '')
            content = act.get('content', '')

            if not category and act.get('action') == 'write' and act.get('path'):
                path = act['path']
                category = _map_old_path_to_category(path)
                content = act.get('content', '')

            if not category or not content:
                continue

            if category == "project":
                project_name = act.get('project_name', '') or _extract_project_name(act.get('path', ''))
                res = fm.write_project_knowledge(project_name, content)
            else:
                res = fm.write_knowledge(category, content)
            results.append(res)

        return f"File Ops Success: {', '.join(results)}"

    except Exception as e:
        return f"File Ops Critical Error: {e}"


@shared_task
def classify_project_content(user_msg_content, ai_msg_content):
    try:
        llm = LLMService()
        prompt = PROJECT_CLASSIFIER_PROMPT.format(user_msg=user_msg_content, ai_msg=ai_msg_content)
        messages = [{"role": "user", "content": prompt}]
        response = llm.get_response(messages, stream=False)
        raw = response.choices[0].message.content

        is_project = _extract_xml_tag(raw, "is_project")
        if is_project != "TRUE":
            return "Not project-related"

        project_name = _extract_xml_tag(raw, "project_name") or "general"
        doc_type = _extract_xml_tag(raw, "doc_type") or "operations"
        content = _extract_xml_tag(raw, "content")

        if not content:
            return "No content extracted"

        pks = ProjectKnowledgeService()
        pks.ensure_project_structure(project_name)
        result = pks.write_doc(project_name, doc_type, content)
        return f"Project classify: {result}"

    except Exception as e:
        return f"Project classify error: {e}"


@shared_task
def run_scribe_consolidation():
    scribe = ScribeService()
    result = scribe.run_full_consolidation(batch_size=50)
    return result


@shared_task
def run_memory_maintenance():
    from .services.memory_maintenance import MemoryMaintenanceService
    mm = MemoryMaintenanceService()
    results = mm.run_full_maintenance()
    return f"Maintenance complete: {'; '.join(results)}"


@shared_task
def consolidate_knowledge_files():
    try:
        fm = FileManager()
        empty_removed = fm.cleanup_empty_files()
        consolidated = fm.consolidate_stale_files()
        return f"Cleaned {empty_removed} empty files. Consolidated: {consolidated}"
    except Exception as e:
        return f"Consolidation error: {e}"


@shared_task
def run_knowledge_maintenance():
    from .services.knowledge_maintenance_service import KnowledgeMaintenanceService
    km = KnowledgeMaintenanceService()
    results = km.run_full_maintenance()
    return f"Knowledge maintenance: {'; '.join(results)}"


@shared_task
def auto_link_new_chunk(chunk_id):
    from .services.concept_link_service import ConceptLinkService
    cls = ConceptLinkService()
    linked = cls.auto_link_chunk(chunk_id)
    return f"Auto-linked chunk {chunk_id}: {linked} links created"
