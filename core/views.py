from django.shortcuts import render
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json
import re
import threading
import time

from .ai_engine.prompts import (
    FINAL_RESPONSE_PROMPT, SYSTEM_IDENTITY,
    USER_INSIGHT_PROMPT, IDENTITY_EVOLUTION_PROMPT,
)

from .models import ChatSession, ChatMessage, PromptLog, MemoryChunk
from .services.llm import LLMService
from .services.filesystem import FileSystemService
from .ai_engine.context import ContextManager
from .tasks import process_message_for_memory, perform_file_operations, consolidate_knowledge_files
from .services.history_service import HistoryManager
from .services.personality_service import PersonalityService
from .services.user_model_service import UserModelService
from django.shortcuts import get_object_or_404
from .services.scribe import ScribeService


def _extract_xml_tag(text, tag):
    match = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_xml_skip(text):
    return bool(re.search(r'<skip>TRUE</skip>', text, re.DOTALL))


def _extract_json_between_braces(text):
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    return None


def _parse_llm_kv(text):
    result = {}
    for line in text.split("\n"):
        line = line.strip().strip('",').strip()
        if ":" in line and not line.startswith("#") and not line.startswith("//"):
            key, _, value = line.partition(":")
            key = key.strip().strip('"').strip().lower().replace(" ", "_")
            value = value.strip().strip('"').strip().strip(",")
            if value and value != "{" and value != "}":
                if value.startswith("[") and value.endswith("]"):
                    items = [v.strip().strip('"') for v in value.strip("[]").split(",") if v.strip()]
                    result[key] = items
                else:
                    result[key] = value
    return result


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


def _update_profiles_async(llm, user_input, ai_response, user_model_service, personality_service):
    if len(user_input.strip()) < 3:
        return

    current_personality = personality_service.get_personality_text()
    current_profile = user_model_service.get_profile_text()

    # 1. Identity evolution
    try:
        identity_msgs = [
            {"role": "system", "content": "You are Felix's Identity Architect. Analyze the conversation and return structured XML about identity evolution."},
            {"role": "user", "content": IDENTITY_EVOLUTION_PROMPT.format(
                current_personality=current_personality,
                user_input=user_input,
                ai_response=ai_response or "",
            )}
        ]
        raw = _safe_llm_call(llm, identity_msgs)
        if raw:
            evolution_data = {
                "reflection": _extract_xml_tag(raw, "reflection"),
                "identity_statement": _extract_xml_tag(raw, "identity_statement"),
                "voice": _extract_xml_tag(raw, "voice"),
                "drives": _extract_xml_tag(raw, "drives"),
                "principles": _extract_xml_tag(raw, "principles"),
            }
            if evolution_data.get("reflection"):
                personality_service.update_from_evolution(evolution_data)
    except Exception as e:
        import traceback
        print(f"Identity evolution error: {e}\n{traceback.format_exc()}")

    time.sleep(1)

    # 2. User insight extraction
    try:
        insight_msgs = [
            {"role": "system", "content": "You are Felix's User Insight Extractor. Analyze the conversation and return structured XML about the user."},
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
    except Exception as e:
        import traceback
        print(f"User insight error: {e}\n{traceback.format_exc()}")


def chat_interface(request):
    if not request.session.get('chat_id'):
        new_session = ChatSession.objects.create()
        request.session['chat_id'] = new_session.id
    return render(request, "core/chat.html")


@csrf_exempt
def chat_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_input = data.get("message", "").strip()

            if not user_input:
                return StreamingHttpResponse("Empty message", status=400)

            session_id = request.session.get('chat_id')
            try:
                chat_session = ChatSession.objects.get(id=session_id)
            except (ChatSession.DoesNotExist, ValueError):
                chat_session = ChatSession.objects.create()
                request.session['chat_id'] = chat_session.id

            llm = LLMService()
            context_man = ContextManager()

            personality_service = PersonalityService()
            user_model_service = UserModelService()

            personality_text = personality_service.get_profile_text()
            user_profile_text = user_model_service.get_context()

            is_simple = context_man.is_simple_query(user_input)

            if is_simple:
                knowledge_context = ""
                history_summary = ""
                recent_messages = []
            else:
                knowledge_context = context_man.gather_context(user_input)
                hist_man = HistoryManager(session_id=chat_session.id)
                history_summary, recent_messages = hist_man.get_optimized_history()

            final_prompt = FINAL_RESPONSE_PROMPT.format(
                personality=personality_text,
                user_profile=user_profile_text,
                knowledge_context=knowledge_context if knowledge_context else "No additional context.",
                history_summary=history_summary if history_summary else "No prior history this session.",
                recent_messages=json.dumps(recent_messages if not is_simple else [], indent=2),
                user_input=user_input
            )

            final_messages = [
                {"role": "system", "content": SYSTEM_IDENTITY},
                {"role": "user", "content": final_prompt}
            ]

            response_stream = llm.get_response(final_messages, stream=True)

            user_msg = ChatMessage.objects.create(
                session=chat_session,
                role='user',
                content=user_input
            )
            process_message_for_memory.delay(user_msg.id)

            PromptLog.objects.create(
                session=chat_session,
                full_prompt=json.dumps({
                    "personality": personality_text,
                    "user_profile": user_profile_text,
                    "knowledge_context": knowledge_context,
                    "final_instructions": final_prompt
                }, indent=2)
            )

            def stream_wrapper():
                ai_content_accumulator = ""
                try:
                    for chunk in response_stream:
                        if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            ai_content_accumulator += content
                            yield content

                    if ai_content_accumulator.strip():
                        ai_msg = ChatMessage.objects.create(
                            session=chat_session,
                            role='assistant',
                            content=ai_content_accumulator
                        )
                        process_message_for_memory.delay(ai_msg.id)
                        perform_file_operations.delay(user_msg.content, ai_msg.content)

                    if not is_simple and len(user_input) > 10:
                        t = threading.Thread(
                            target=_update_profiles_async,
                            args=(LLMService(), user_input, ai_content_accumulator,
                                  user_model_service, personality_service)
                        )
                        t.start()

                except Exception as stream_err:
                    print(f"Streaming break: {stream_err}")

            return StreamingHttpResponse(stream_wrapper(), content_type="text/plain")

        except Exception as e:
            print(f"Chat API Critical Error: {e}")
            import traceback
            traceback.print_exc()
            return StreamingHttpResponse(f"Error: {str(e)}", status=500)


@csrf_exempt
def delete_chat(request, session_id):
    if request.method == "DELETE":
        try:
            session = ChatSession.objects.get(id=session_id)
            session.delete()
            if request.session.get('chat_id') == session_id:
                del request.session['chat_id']
            return JsonResponse({"status": "success", "message": f"Chat {session_id} deleted."})
        except ChatSession.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Chat not found."}, status=404)
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
def delete_all_chats(request):
    if request.method == "POST":
        count = ChatSession.objects.all().count()
        ChatSession.objects.all().delete()
        request.session.flush()
        return JsonResponse({"status": "success", "message": f"Purged {count} sessions."})
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
def system_purge(request):
    if request.method == "POST":
        from .services.memory_maintenance import MemoryMaintenanceService
        mm = MemoryMaintenanceService()
        mm.wipe_data_folder()
        ChatSession.objects.all().delete()
        MemoryChunk.objects.all().delete()
        PromptLog.objects.all().delete()
        request.session.flush()
        return JsonResponse({
            "status": "success",
            "message": "Full factory reset complete. All data wiped."
        })
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
def system_status(request):
    from .services.memory_maintenance import MemoryMaintenanceService
    mm = MemoryMaintenanceService()
    status = mm.get_boarding_status()
    return JsonResponse(status)


@csrf_exempt
def trigger_maintenance(request):
    if request.method == "POST":
        from .services.memory_maintenance import MemoryMaintenanceService
        mm = MemoryMaintenanceService()
        results = mm.run_full_maintenance()
        return JsonResponse({"status": "complete", "results": results})
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


def list_chats(request):
    sessions = ChatSession.objects.all().order_by('-started_at')
    data = [
        {"id": s.id, "title": s.title, "started_at": s.started_at.strftime("%Y-%m-%d %H:%M")}
        for s in sessions
    ]
    return JsonResponse({"chats": data})


def load_chat(request, session_id):
    chat = get_object_or_404(ChatSession, id=session_id)
    request.session['chat_id'] = chat.id
    messages = chat.messages.all().order_by('created_at')
    data = [
        {"role": m.role, "content": m.content, "created_at": m.created_at.strftime("%H:%M")}
        for m in messages
    ]
    return JsonResponse({"session_id": chat.id, "messages": data})


def new_chat(request):
    if 'chat_id' in request.session:
        del request.session['chat_id']
    return JsonResponse({"status": "success"})


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
    return JsonResponse({
        "status": "complete",
        "cleaned": empty_removed,
        "consolidated": consolidated
    })


def chat_debug(request, session_id=None):
    try:
        session = ChatSession.objects.get(id=session_id)
        prompts = PromptLog.objects.filter(session=session).order_by('-created_at')
        memories = MemoryChunk.objects.filter(source_message__session=session).order_by('-created_at')
    except ChatSession.DoesNotExist:
        session = None
        prompts = PromptLog.objects.filter().order_by('-created_at')
        memories = MemoryChunk.objects.filter().order_by('-created_at')
    context = {"session": session, "prompts": prompts, "memories": memories}
    return render(request, "core/debug.html", context)
