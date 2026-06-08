import json
from celery import shared_task
from .models import ChatMessage, MemoryChunk
from .services.llm import LLMService
from .services.embedding import EmbeddingService
from .services.filesystem import FileSystemService
from .services.scribe import ScribeService
from .services.file_manager import FileManager
from .ai_engine.prompts import USER_CHUNKING_PROMPT, AI_CHUNKING_PROMPT, FILE_OPS_PROMPT
from .services.utils import parse_chunking_output

def extract_json(raw_text):
    """Helper to pull a JSON list or object out of a chatty LLM response."""
    try:
        start_index = raw_text.find('[')
        end_index = raw_text.rfind(']')
        if start_index == -1 or end_index == -1:
            # Try looking for curly braces if it's not a list
            start_index = raw_text.find('{')
            end_index = raw_text.rfind('}')
            
        if start_index == -1:
            return None

        json_str = raw_text[start_index : end_index + 1]
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


@shared_task
def process_message_for_memory(message_id):
    try:
        message = ChatMessage.objects.get(id=message_id)
        if message.processed:
            return "Already Processed"

        llm = LLMService()
        fs = FileSystemService() # <--- FIXED: Initialize FS Service

        # Select Prompt based on Role
        if message.role == 'user':
            # === NEW: Contextual Chunking ===
            # Fetch the previous AI response to understand the 'meaning' of the user's reply
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
            prompt = AI_CHUNKING_PROMPT.format(
                ai_response=message.content
            )
            system_role = "You are an AI Memory Extractor."

        # Execute LLM Call
        messages = [
            {"role": "system", "content": f"{system_role} Output strict XML."},
            {"role": "user", "content": prompt}
        ]
        response = llm.get_response(messages, stream=False)
        
        # Parse Results
        chunk_data = parse_chunking_output(response.choices[0].message.content)

        if chunk_data["skip"]:
            message.processed = True
            message.save()
            return "Skipped (Trivial)"

        if not chunk_data["content"]:
            return "Failed: No content tag found."

        # Create Embedding ONLY on Content (The Summary)
        embedder = EmbeddingService()
        vector = embedder.embed_text(chunk_data['content'])
        
        # Save to DB
        MemoryChunk.objects.create(
            content=chunk_data['content'],        # The Summary (Searchable)
            embedding=vector,                     # Vector of Summary
            reflection="",                        # Reflection removed
            metadata=chunk_data['metadata'],      # Tags
            source_message=message
        )

        message.processed = True
        message.save()
        return "Success: Created 1 Structured Chunk"

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
            # New format: category + content
            category = act.get('category', '')
            content = act.get('content', '')
            
            # Old format fallback: action + path
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
def run_scribe_consolidation():
    """
    Periodic task to clean up the Vector DB and crystallize knowledge.
    Run this every 30-60 minutes or after X messages.
    """
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
    """
    Consolidate stale/duplicate files into the canonical structure.
    Run periodically to keep the file system clean.
    """
    try:
        fm = FileManager()
        empty_removed = fm.cleanup_empty_files()
        consolidated = fm.consolidate_stale_files()
        return f"Cleaned {empty_removed} empty files. Consolidated: {consolidated}"
    except Exception as e:
        return f"Consolidation error: {e}"