from django.shortcuts import render
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json
import re
import threading
import time

from .ai_engine.prompts import (
    FINAL_RESPONSE_PROMPT, PERSONALITY_CORE,
    USER_INSIGHT_PROMPT, IDENTITY_EVOLUTION_PROMPT,
    CONTEXT_SYNTHESIS_PROMPT,
)

from .models import ChatSession, ChatMessage, PromptLog, MemoryChunk, LifecycleStage
from .services.llm import LLMService
from .services.filesystem import FileSystemService
from .ai_engine.context import ContextManager
from .tasks import process_message_for_memory, perform_file_operations, classify_project_content
from .services.history_service import HistoryManager
from .services.personality_service import PersonalityService
from .services.user_model_service import UserModelService
from django.shortcuts import get_object_or_404
from .services.scribe import ScribeService
from .services.audit_service import AuditService
from .services.project_knowledge_service import ProjectKnowledgeService, PROJECT_DOC_TYPES
from .services.core_memory_service import CoreMemoryService
from .services.version_service import VersionService
from .services.user_fact_service import UserFactService
from .services.concept_link_service import ConceptLinkService


def _extract_xml_tag(text, tag):
    match = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_xml_skip(text):
    return bool(re.search(r'<skip>TRUE</skip>', text, re.DOTALL))


def _safe_llm_call(llm, messages, retries=2):
    for attempt in range(retries):
        try:
            resp = llm.get_response(messages, stream=False)
            if resp and resp.choices:
                return resp.choices[0].message.content.strip()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
    return None


def _detect_contradictions(user_input, user_model_service):
    contradictions = []
    user_name = user_model_service.get_name()
    sections = user_model_service.get_sections()
    input_lower = user_input.lower()

    if user_name and user_name != "Not explicitly provided":
        import re
        name_patterns = re.findall(r'my name is (\w+(?:\s+\w+)?)', input_lower, re.IGNORECASE)
        for name in name_patterns:
            name = name.strip()
            if name.lower() != user_name.lower():
                contradictions.append(f"Name mismatch: user said '{name}' but stored name is '{user_name}'")

    stored_name = user_model_service.get_name()
    if stored_name:
        import re
        name_patterns = re.findall(r'(?:call me|i am|i\'m|my name is|name\'s)\s+(\w+(?:\s+\w+)?)', input_lower, re.IGNORECASE)
        for name in name_patterns:
            name = name.strip()
            name_lower = name.lower()
            stored_lower = stored_name.lower()
            if name_lower != stored_lower and name_lower not in stored_lower and stored_lower not in name_lower:
                contradictions.append(f"Name mismatch: user introduced themselves as '{name}' but stored name is '{stored_name}'")

    return contradictions


def _run_context_synthesis(llm, user_input, core_context, archival_context, history_summary, personality_snapshot=""):
    synthesis_prompt = CONTEXT_SYNTHESIS_PROMPT.format(
        user_query=user_input,
        personality_snapshot=personality_snapshot[:500] if personality_snapshot else "Default Felix identity.",
        core_memory=core_context if core_context else "No core memory.",
        history_summary=history_summary if history_summary else "No prior history this session.",
        knowledge_context=archival_context if archival_context else "No additional knowledge.",
    )
    msg = [
        {"role": "system", "content": "You are a context synthesizer. Be concise and specific."},
        {"role": "user", "content": synthesis_prompt},
    ]
    raw = _safe_llm_call(llm, msg)
    return raw or "No relevant context found."


def _update_profiles_async(llm, user_input, ai_response, user_model_service, personality_service):
    if len(user_input.strip()) < 3:
        return

    current_personality = personality_service.get_personality_text()
    current_profile = user_model_service.get_profile_text()

    try:
        identity_msgs = [
            {"role": "system", "content": "You are Felix's Identity Architect. Analyze the conversation."},
            {"role": "user", "content": IDENTITY_EVOLUTION_PROMPT.format(
                current_personality=current_personality,
                user_input=user_input,
                ai_response=ai_response or "",
            )}
        ]
        raw = _safe_llm_call(llm, identity_msgs)
        if raw and not _extract_xml_skip(raw):
            evolution_data = {
                "reflection": _extract_xml_tag(raw, "reflection"),
                "identity_statement": _extract_xml_tag(raw, "identity_statement"),
                "voice": _extract_xml_tag(raw, "voice"),
                "drives": _extract_xml_tag(raw, "drives"),
                "principles": _extract_xml_tag(raw, "principles"),
            }
            if evolution_data.get("reflection"):
                has_explicit_direction = bool(
                    evolution_data.get("identity_statement")
                    or evolution_data.get("voice")
                    or evolution_data.get("drives")
                    or evolution_data.get("principles")
                )
                if has_explicit_direction:
                    personality_service.update_from_evolution(evolution_data)
                else:
                    AuditService().log(
                        action_type='personality_reflection',
                        target_model="Personality",
                        target_id="reflection",
                        summary=f"Personality reflection: {evolution_data['reflection'][:200]}",
                        new_state=evolution_data,
                        approved=True,
                    )
    except Exception as e:
        import traceback
        print(f"Identity evolution error: {e}\n{traceback.format_exc()}")

    time.sleep(1)

    contradictions = _detect_contradictions(user_input, user_model_service)
    for c in contradictions:
        AuditService().log(
            action_type='contradiction_detected',
            target_model="UserModel",
            target_id="conversation",
            summary=c[:300],
            new_state={"contradiction": c, "user_input": user_input[:200]},
            approved=True,
        )

    try:
        insight_msgs = [
            {"role": "system", "content": "You are Felix's User Insight Extractor."},
            {"role": "user", "content": USER_INSIGHT_PROMPT.format(
                current_profile=current_profile,
                user_input=user_input,
                ai_response=ai_response or "",
            )}
        ]
        raw = _safe_llm_call(llm, insight_msgs)
        if raw:
            if _extract_xml_skip(raw):
                return
            insight_data = {
                "narrative": _extract_xml_tag(raw, "narrative"),
                "facts": _extract_xml_tag(raw, "facts"),
                "topics": _extract_xml_tag(raw, "topics"),
                "skip": False,
            }
            if insight_data.get("narrative") or insight_data.get("facts"):
                user_model_service.update_from_insight(insight_data)
                from .services.user_fact_service import UserFactService
                try:
                    UserFactService().extract_facts_from_insight(insight_data)
                except Exception:
                    pass
    except Exception as e:
        import traceback
        print(f"User insight error: {e}\n{traceback.format_exc()}")


# ---- SINGLE CONTINUOUS CHAT ----

def _ensure_chat_session():
    session, _ = ChatSession.objects.get_or_create(id=1, defaults={"title": "Felix"})
    return session


def chat_interface(request):
    _ensure_chat_session()
    return render(request, "core/chat.html")


@csrf_exempt
def chat_history(request):
    session = _ensure_chat_session()
    messages = ChatMessage.objects.filter(session=session).order_by('created_at')
    data = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for m in messages
    ]
    return JsonResponse({"messages": data, "count": len(data)})


@csrf_exempt
def chat_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=405)

    try:
        data = json.loads(request.body)
        user_input = data.get("message", "").strip()
        if not user_input:
            return JsonResponse({"error": "Empty message"}, status=400)

        session = _ensure_chat_session()
        llm = LLMService()
        context_man = ContextManager()
        personality_service = PersonalityService()
        user_model_service = UserModelService()

        def sse_event(event_type, data_dict):
            return f"event: {event_type}\ndata: {json.dumps(data_dict)}\n\n"

        def event_stream():
            personality_text = personality_service.get_personality_text()
            is_simple = context_man.is_simple_query(user_input)

            yield sse_event("thought", {"type": "status", "message": "Analyzing query..."})

            if is_simple:
                yield sse_event("thought", {"type": "status", "message": "Simple query — responding directly"})
                context_synthesis = "Simple query — no additional context needed."
                history_summary = ""
            else:
                yield sse_event("thought", {"type": "context", "source": "personality", "summary": "Loaded Felix's identity and core drives"})

                core_context = context_man.get_core_context()
                yield sse_event("thought", {"type": "context", "source": "core_memory", "summary": f"Loaded core memory ({len(core_context)} chars): profile, preferences, goals"})

                yield sse_event("thought", {"type": "status", "message": "Searching memory for relevant context..."})
                archival_context = context_man.gather_archival_context(user_input)
                if archival_context:
                    yield sse_event("thought", {"type": "retrieval", "summary": f"Found relevant memories ({len(archival_context)} chars)"})
                else:
                    yield sse_event("thought", {"type": "retrieval", "summary": "No relevant memories found"})

                hist_man = HistoryManager(session_id=session.id)
                history_summary, recent_messages = hist_man.get_optimized_history()
                hist_label = f"Loaded {len(recent_messages)} messages"
                if history_summary:
                    hist_label += " (summarized older context)"
                yield sse_event("thought", {"type": "history", "summary": hist_label})

                yield sse_event("thought", {"type": "status", "message": "Synthesizing context with your question..."})
                personality_snippet = personality_text[:500] if personality_text else ""
                context_synthesis = _run_context_synthesis(llm, user_input, core_context, archival_context, history_summary, personality_snippet)
                yield sse_event("thought", {"type": "synthesis", "content": context_synthesis[:400]})

            yield sse_event("thought", {"type": "status", "message": "Generating response..."})

            final_prompt = FINAL_RESPONSE_PROMPT.format(
                personality_core=PERSONALITY_CORE,
                context_synthesis=context_synthesis,
                user_input=user_input,
            )

            final_messages = [
                {"role": "system", "content": personality_text},
                {"role": "user", "content": final_prompt},
            ]

            response_stream = llm.get_response(final_messages, stream=True)

            user_msg = ChatMessage.objects.create(
                session=session, role='user', content=user_input
            )
            process_message_for_memory.delay(user_msg.id)

            yield sse_event("meta", {"user_message_id": user_msg.id})

            PromptLog.objects.create(
                session=session,
                full_prompt=json.dumps({
                    "personality_snapshot": personality_text[:500],
                    "context_synthesis": context_synthesis,
                    "final_instructions": final_prompt,
                }, indent=2)
            )

            ai_content = ""
            try:
                for chunk in response_stream:
                    if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        ai_content += content
                        yield sse_event("token", {"token": content})

                if ai_content.strip():
                    ai_msg = ChatMessage.objects.create(
                        session=session, role='assistant', content=ai_content
                    )
                    process_message_for_memory.delay(ai_msg.id)
                    perform_file_operations.delay(user_msg.content, ai_msg.content)
                    classify_project_content.delay(user_msg.content, ai_msg.content)

                if not is_simple and len(user_input) > 10:
                    t = threading.Thread(
                        target=_update_profiles_async,
                        args=(LLMService(), user_input, ai_content,
                              user_model_service, personality_service)
                    )
                    t.start()

            except Exception as e:
                print(f"Stream error: {e}")
                yield sse_event("error", {"message": str(e)})

            yield sse_event("done", {"ai_message_id": ai_msg.id if ai_content.strip() else None})

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")

    except Exception as e:
        print(f"Chat API Error: {e}")
        import traceback
        traceback.print_exc()
        return StreamingHttpResponse(f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n", status=500, content_type="text/event-stream")


# ---- FILE BROWSER ----

def _walk_files(base_path, prefix=""):
    import os
    from pathlib import Path
    entries = []
    try:
        for item in sorted(base_path.iterdir()):
            if item.name.startswith(".") or item.name == "__pycache__":
                continue
            rel = f"{prefix}/{item.name}" if prefix else item.name
            if item.is_dir():
                children = _walk_files(item, rel)
                if children:
                    entries.append({"name": item.name, "type": "directory", "path": rel.replace("\\", "/"), "children": children})
            else:
                entries.append({"name": item.name, "type": "file", "path": rel.replace("\\", "/")})
    except Exception:
        pass
    return entries


@csrf_exempt
def list_knowledge_files(request):
    if request.method == "GET":
        fs = FileSystemService()
        tree = _walk_files(fs.root_path)
        return JsonResponse({"tree": tree})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def read_knowledge_file(request, file_path):
    if request.method == "GET":
        fs = FileSystemService()
        content = fs.read_file(file_path)
        if content and not content.startswith("Error"):
            return JsonResponse({"path": file_path, "content": content})
        return JsonResponse({"error": "File not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def write_knowledge_file(request, file_path):
    if request.method == "POST":
        data = json.loads(request.body)
        content = data.get("content", "")
        fs = FileSystemService()
        result = fs.write_file(file_path, content)
        if result.startswith("Error"):
            return JsonResponse({"error": result}, status=400)
        AuditService().log(
            action_type="file_write",
            target_model="KnowledgeFile",
            target_id=file_path,
            summary=f"Updated {file_path}",
        )
        return JsonResponse({"status": "saved", "path": file_path})
    return JsonResponse({"status": "error"}, status=405)


# ---- SYSTEM ----

@csrf_exempt
def system_purge(request):
    if request.method == "POST":
        from .services.memory_maintenance import MemoryMaintenanceService
        mm = MemoryMaintenanceService()
        mm.wipe_data_folder()
        ChatSession.objects.all().delete()
        MemoryChunk.objects.all().delete()
        PromptLog.objects.all().delete()
        return JsonResponse({"status": "success", "message": "Full factory reset complete."})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def system_status(request):
    from .services.memory_maintenance import MemoryMaintenanceService
    mm = MemoryMaintenanceService()
    status = mm.get_boarding_status()
    status["pending_changes"] = 0
    status["message_count"] = ChatMessage.objects.filter(session_id=1).count()
    status["chunk_count"] = MemoryChunk.objects.filter(is_active=True).count()
    status["project_count"] = len(ProjectKnowledgeService().list_projects())
    return JsonResponse(status)


@csrf_exempt
def trigger_maintenance(request):
    if request.method == "POST":
        from .services.memory_maintenance import MemoryMaintenanceService
        mm = MemoryMaintenanceService()
        results = mm.run_full_maintenance()
        return JsonResponse({"status": "complete", "results": results})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def trigger_scribe(request):
    scribe = ScribeService()
    result_message = scribe.run_full_consolidation(batch_size=30)
    return JsonResponse({"status": "complete", "result": result_message})


@csrf_exempt
def trigger_file_cleanup(request):
    from .services.file_manager import FileManager
    fm = FileManager()
    empty_removed = fm.cleanup_empty_files()
    consolidated = fm.consolidate_stale_files()
    return JsonResponse({"status": "complete", "cleaned": empty_removed, "consolidated": consolidated})





# ---- PROJECT KNOWLEDGE ----

@csrf_exempt
def list_projects(request):
    if request.method == "GET":
        pks = ProjectKnowledgeService()
        projects = pks.list_projects()
        return JsonResponse({"projects": projects})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def project_detail(request, project_name):
    if request.method == "GET":
        pks = ProjectKnowledgeService()
        summary = pks.get_project_summary(project_name)
        return JsonResponse({"project": project_name, "docs": summary})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def project_doc(request, project_name, doc_type):
    if request.method == "GET":
        pks = ProjectKnowledgeService()
        content = pks.read_doc(project_name, doc_type)
        if content:
            return JsonResponse({"project": project_name, "doc_type": doc_type, "content": content})
        return JsonResponse({"error": "Not found"}, status=404)
    if request.method == "POST":
        data = json.loads(request.body)
        content = data.get("content", "")
        pks = ProjectKnowledgeService()
        pks.ensure_project_structure(project_name)
        result = pks.write_doc(project_name, doc_type, content)
        return JsonResponse({"status": "success", "result": result})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def project_search(request):
    if request.method == "POST":
        data = json.loads(request.body)
        query = data.get("query", "")
        project_name = data.get("project_name", None)
        pks = ProjectKnowledgeService()
        results = pks.find_related_docs(query, project_name=project_name)
        return JsonResponse({"results": results})
    return JsonResponse({"status": "error"}, status=405)


# ---- VERSION SNAPSHOTS ----

@csrf_exempt
def list_snapshots(request):
    if request.method == "GET":
        content_type = request.GET.get("content_type", "")
        content_id = request.GET.get("content_id", "")
        vs = VersionService()
        snapshots = vs.get_snapshots(content_type, content_id)
        data = [{"id": s.id, "content_type": s.content_type, "content_id": s.content_id, "summary": s.summary, "created_at": s.created_at.isoformat()} for s in snapshots]
        return JsonResponse({"snapshots": data})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def restore_snapshot(request, snapshot_id):
    if request.method == "POST":
        vs = VersionService()
        snapshot, msg = vs.restore_snapshot(snapshot_id)
        if snapshot:
            return JsonResponse({"status": "success", "message": msg, "snapshot_id": snapshot_id})
        return JsonResponse({"status": "error", "message": msg}, status=404)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def diff_snapshot(request, snapshot_id):
    if request.method == "GET":
        vs = VersionService()
        compare_id = request.GET.get("compare_to", None)
        if compare_id:
            compare_id = int(compare_id) if compare_id.isdigit() else None
        diff = vs.get_diff(snapshot_id, compare_id)
        return JsonResponse({"diff": diff})
    return JsonResponse({"status": "error"}, status=405)


# ---- STRUCTURED FACTS ----

@csrf_exempt
def list_facts(request):
    if request.method == "GET":
        ufs = UserFactService()
        category = request.GET.get("category", None)
        facts = ufs.get_facts(category=category)
        data = [{"id": f.id, "category": f.category, "fact_key": f.fact_key, "fact_value": f.fact_value, "source": f.source, "confidence": f.confidence, "updated_at": f.updated_at.isoformat()} for f in facts]
        return JsonResponse({"facts": data})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def create_fact(request):
    if request.method == "POST":
        data = json.loads(request.body)
        ufs = UserFactService()
        fact = ufs.add_fact(category=data.get("category", "other"), fact_key=data.get("fact_key", ""), fact_value=data.get("fact_value", ""), source=data.get("source", ""), confidence=data.get("confidence", 1.0))
        return JsonResponse({"status": "created", "fact_id": fact.id})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def delete_fact(request, fact_id):
    if request.method == "DELETE":
        ufs = UserFactService()
        success = ufs.deactivate_fact(fact_id)
        if success:
            return JsonResponse({"status": "deactivated"})
        return JsonResponse({"status": "error", "message": "Fact not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


# ---- MEMORY LIFECYCLE ----

@csrf_exempt
def set_lifecycle_stage(request, chunk_id):
    if request.method == "POST":
        data = json.loads(request.body)
        stage = data.get("stage", "")
        valid_stages = [s.value for s in LifecycleStage]
        if stage not in valid_stages:
            return JsonResponse({"status": "error", "message": f"Invalid stage. Valid: {valid_stages}"}, status=400)
        try:
            chunk = MemoryChunk.objects.get(id=chunk_id)
            chunk.lifecycle_stage = stage
            chunk.save()
            return JsonResponse({"status": "updated", "chunk_id": chunk_id, "stage": stage})
        except MemoryChunk.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Chunk not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def list_chunks_by_stage(request, stage):
    if request.method == "GET":
        valid_stages = [s.value for s in LifecycleStage]
        if stage not in valid_stages:
            return JsonResponse({"status": "error", "message": f"Invalid stage. Valid: {valid_stages}"}, status=400)
        chunks = MemoryChunk.objects.filter(lifecycle_stage=stage, is_active=True).order_by('-created_at')[:50]
        data = [{"id": c.id, "content": c.content[:200], "chunk_type": c.chunk_type, "memory_tier": c.memory_tier, "created_at": c.created_at.isoformat()} for c in chunks]
        return JsonResponse({"chunks": data, "stage": stage, "count": len(data)})
    return JsonResponse({"status": "error"}, status=405)


# ---- CORE MEMORY ----

@csrf_exempt
def promote_to_core(request, chunk_id):
    if request.method == "POST":
        try:
            chunk = MemoryChunk.objects.get(id=chunk_id)
            chunk.memory_tier = "core"
            chunk.save()
            AuditService().log(action_type="core_memory_promote", target_model="MemoryChunk", target_id=chunk_id, summary=f"Promoted chunk {chunk_id} to core memory", new_state={"content": chunk.content[:200], "tier": "core"})
            return JsonResponse({"status": "promoted", "chunk_id": chunk_id})
        except MemoryChunk.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Chunk not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def demote_from_core(request, chunk_id):
    if request.method == "POST":
        try:
            chunk = MemoryChunk.objects.get(id=chunk_id)
            chunk.memory_tier = "archival"
            chunk.save()
            AuditService().log(action_type="core_memory_demote", target_model="MemoryChunk", target_id=chunk_id, summary=f"Demoted chunk {chunk_id} from core memory", new_state={"content": chunk.content[:200], "tier": "archival"})
            return JsonResponse({"status": "demoted", "chunk_id": chunk_id})
        except MemoryChunk.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Chunk not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def list_core_memory(request):
    if request.method == "GET":
        chunks = MemoryChunk.objects.filter(memory_tier="core", is_active=True).order_by('-created_at')
        data = [{"id": c.id, "content": c.content[:300], "chunk_type": c.chunk_type, "lifecycle_stage": c.lifecycle_stage, "created_at": c.created_at.isoformat(), "metadata": c.metadata} for c in chunks]
        return JsonResponse({"core_memory": data, "count": len(data)})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def core_memory_view(request):
    if request.method == "GET":
        cms = CoreMemoryService()
        core = cms.get_core_context()
        condensed = cms.get_condensed_core()
        db_core_chunks = MemoryChunk.objects.filter(memory_tier="core", is_active=True).order_by('-created_at')[:20]
        db_core = [{"id": c.id, "content": c.content[:300], "lifecycle_stage": c.lifecycle_stage, "created_at": c.created_at.isoformat()} for c in db_core_chunks]
        return JsonResponse({"core_context": core, "condensed": condensed, "char_count": len(core), "db_core_chunks": db_core, "db_core_count": len(db_core)})
    return JsonResponse({"status": "error"}, status=405)


# ---- CONCEPT LINKS ----

@csrf_exempt
def create_concept_link(request):
    if request.method == "POST":
        data = json.loads(request.body)
        cls = ConceptLinkService()
        link = cls.create_link(source_chunk_id=data.get("source_chunk_id"), target_chunk_id=data.get("target_chunk_id"), link_type=data.get("link_type", "related"), label=data.get("label", ""), metadata=data.get("metadata"))
        if link:
            return JsonResponse({"status": "created", "link_id": link.id})
        return JsonResponse({"status": "error", "message": "Invalid chunk IDs"}, status=400)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def get_chunk_links(request, chunk_id):
    if request.method == "GET":
        cls = ConceptLinkService()
        link_type = request.GET.get("link_type", None)
        links = cls.get_links_for_chunk(chunk_id, link_type=link_type)
        data = [{"id": l.id, "source_chunk_id": l.source_chunk_id, "target_chunk_id": l.target_chunk_id, "link_type": l.link_type, "label": l.label} for l in links]
        return JsonResponse({"links": data})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def get_related_chunks(request, chunk_id):
    if request.method == "GET":
        cls = ConceptLinkService()
        max_depth = int(request.GET.get("max_depth", 1))
        related = cls.get_related_chunks(chunk_id, max_depth=max_depth)
        return JsonResponse({"related": related})
    return JsonResponse({"status": "error"}, status=405)


# ---- KNOWLEDGE MAINTENANCE ----

@csrf_exempt
def trigger_knowledge_maintenance(request):
    if request.method == "POST":
        from .tasks import run_knowledge_maintenance
        result = run_knowledge_maintenance()
        return JsonResponse({"status": "complete", "result": result})
    return JsonResponse({"status": "error"}, status=405)


# ---- DECISION RECORDS ----

@csrf_exempt
def list_decisions(request):
    if request.method == "GET":
        from .services.decision_service import DecisionService
        ds = DecisionService()
        project = request.GET.get("project", None)
        status = request.GET.get("status", None)
        decisions = ds.get_decisions(project=project, status=status)
        data = [{"id": d.id, "project": d.project, "title": d.title, "status": d.status, "rationale": d.rationale[:300], "alternatives": d.alternatives, "context": d.context[:200], "tags": d.tags, "created_at": d.created_at.isoformat(), "superseded_by": d.superseded_by_id} for d in decisions]
        return JsonResponse({"decisions": data})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def create_decision(request):
    if request.method == "POST":
        from .services.decision_service import DecisionService
        data = json.loads(request.body)
        ds = DecisionService()
        decision = ds.create_decision(project=data.get("project", "general"), title=data.get("title", ""), rationale=data.get("rationale", ""), alternatives=data.get("alternatives", []), context=data.get("context", ""), tags=data.get("tags", []))
        return JsonResponse({"status": "created", "decision_id": decision.id})
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def update_decision_status(request, decision_id):
    if request.method == "POST":
        from .services.decision_service import DecisionService
        data = json.loads(request.body)
        ds = DecisionService()
        success = ds.update_status(decision_id, data.get("status", ""), superseded_by_id=data.get("superseded_by_id"))
        if success:
            return JsonResponse({"status": "updated"})
        return JsonResponse({"status": "error", "message": "Decision not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


# ---- AUDIT LOG ----

@csrf_exempt
def audit_log_view(request):
    if request.method == "GET":
        audit = AuditService()
        target_model = request.GET.get("model", None)
        with_diff = request.GET.get("diff", "0") == "1"
        if target_model:
            entries = audit.get_by_model(target_model)
        else:
            entries = audit.get_recent(limit=50)
        data = []
        for e in entries:
            entry = {"id": e.id, "action_type": e.action_type, "target_model": e.target_model, "summary": e.summary, "approved": e.approved, "created_at": e.created_at.isoformat()}
            if with_diff and e.previous_state and e.new_state:
                import difflib
                old = json.dumps(e.previous_state, indent=2)
                new = json.dumps(e.new_state, indent=2)
                diff = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), n=2)
                entry["diff"] = "".join(diff)
            data.append(entry)
        return JsonResponse({"audit_log": data, "count": len(data)})
    return JsonResponse({"status": "error"}, status=405)


# ---- CHAT DEBUG ----

def chat_debug(request, session_id=None):
    try:
        session = ChatSession.objects.get(id=session_id or 1)
        prompts = PromptLog.objects.filter(session=session).order_by('-created_at')
        memories = MemoryChunk.objects.filter(source_message__session=session).order_by('-created_at')
    except ChatSession.DoesNotExist:
        session = None
        prompts = PromptLog.objects.filter().order_by('-created_at')
        memories = MemoryChunk.objects.filter().order_by('-created_at')[:50]
    context = {"session": session, "prompts": prompts, "memories": memories}
    return render(request, "core/debug.html", context)
