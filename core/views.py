from django.shortcuts import render
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json

from .ai_engine.prompts import ANSWER_PLANNER_PROMPT, FINAL_RESPONSE_PROMPT, SYSTEM_IDENTITY

# Internal imports
from .models import ChatSession, ChatMessage, PromptLog, MemoryChunk
from .services.llm import LLMService
from .services.filesystem import FileSystemService
from .ai_engine.context import ContextManager
from .tasks import process_message_for_memory, perform_file_operations
from .services.history_service import HistoryManager
from django.shortcuts import get_object_or_404
from .services.scribe import ScribeService

def chat_interface(request):
    """Renders the main chat UI."""
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

            # --- 1. Session Management ---
            session_id = request.session.get('chat_id')
            try:
                chat_session = ChatSession.objects.get(id=session_id)
            except (ChatSession.DoesNotExist, ValueError):
                chat_session = ChatSession.objects.create()
                request.session['chat_id'] = chat_session.id

            # --- 2. Context & History Gathering ---
            context_man = ContextManager()
            # This now includes the "Verified Knowledge Brief" and "Behavioral Directive"
            augmented_context = context_man.gather_context(user_input)

            hist_man = HistoryManager(session_id=chat_session.id)
            history_summary, recent_messages = hist_man.get_optimized_history()

            # --- 3. STAGE 1: THE PLANNER ---
            # We use a non-streaming call for the plan to ensure the strategy is complete.
            llm = LLMService()
            fs = FileSystemService()
            
            planner_input = f"""
            KNOWLEDGE & BEHAVIOR BRIEF:
            {augmented_context}

            HISTORY SUMMARY:
            {history_summary}

            RECENT DIALOGUE:
            {json.dumps(recent_messages, indent=2)}

            USER QUERY:
            {user_input}
            """

            planner_messages = [
                {"role": "system", "content": f"{SYSTEM_IDENTITY}\n{ANSWER_PLANNER_PROMPT}"},
                {"role": "user", "content": planner_input}
            ]
            
            # Get the plan
            plan_response = llm.get_response(planner_messages, stream=False)
            answer_plan = plan_response.choices[0].message.content

            # --- 4. STAGE 2: THE SYNTHESIZER (Streaming) ---
            # Load the personality from the filesystem
            try:
                personality_md = fs.read_file("personality.md")
            except:
                personality_md = "You are Felix, a loyal and professional digital assistant."

            final_system_prompt = FINAL_RESPONSE_PROMPT.format(
                personality_md=personality_md,
                answer_plan=answer_plan,
                user_input=user_input
            )

            # Final payload for the persona
            final_messages = [
                {"role": "system", "content": final_system_prompt}
            ]

            # We stream this part so the user gets that "lifelike" immediate response
            response_stream = llm.get_response(final_messages, stream=True)

            # --- 5. Commit User Message ---
            user_msg = ChatMessage.objects.create(
                session=chat_session, 
                role='user', 
                content=user_input
            )
            process_message_for_memory.delay(user_msg.id)

            # --- 6. Stream Wrapper ---
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
                        # We removed perform_file_operations.delay
                        # Background task only for vector memory chunking
                        process_message_for_memory.delay(ai_msg.id)
                        
                except Exception as stream_err:
                    print(f"Streaming break: {stream_err}")

            # Log the plan and the final instructions for debugging
            PromptLog.objects.create(
                session=chat_session,
                full_prompt=json.dumps({
                    "plan": answer_plan,
                    "final_instructions": final_system_prompt
                }, indent=2)
            )

            return StreamingHttpResponse(stream_wrapper(), content_type="text/plain")

        except Exception as e:
            print(f"Chat API Critical Error: {e}")
            return StreamingHttpResponse(f"Error: {str(e)}", status=500)



@csrf_exempt
def delete_chat(request, session_id):
    """Deletes a specific chat session and all cascading data."""
    if request.method == "DELETE":
        try:
            session = ChatSession.objects.get(id=session_id)
            session.delete() # CASCADE handles messages and logs
            
            # If this was the active session in the browser, clear it
            if request.session.get('chat_id') == session_id:
                del request.session['chat_id']
                
            return JsonResponse({"status": "success", "message": f"Chat {session_id} deleted."})
        except ChatSession.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Chat not found."}, status=404)
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

@csrf_exempt
def delete_all_chats(request):
    """Deletes all chat sessions, messages, and logs. Keeps MemoryChunks."""
    if request.method == "POST":
        count = ChatSession.objects.all().count()
        ChatSession.objects.all().delete() 
        request.session.flush() # Clear the user's session entirely
        return JsonResponse({"status": "success", "message": f"Purged {count} sessions."})
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

@csrf_exempt
def system_purge(request):
    """The 'Nuclear Option': Deletes EVERYTHING."""
    if request.method == "POST":
        # Delete all sessions (cascades to messages and logs)
        ChatSession.objects.all().delete()
        # Delete all semantic memories
        MemoryChunk.objects.all().delete()
        
        request.session.flush()
        
        return JsonResponse({
            "status": "success", 
            "message": "System purged. All chats and semantic memories have been wiped."
        })
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


def list_chats(request):
    """Returns a JSON list of all chat sessions for the sidebar."""
    sessions = ChatSession.objects.all().order_by('-started_at')
    data = [
        {
            "id": s.id, 
            "title": s.title, 
            "started_at": s.started_at.strftime("%Y-%m-%d %H:%M")
        } 
        for s in sessions
    ]
    return JsonResponse({"chats": data})

def load_chat(request, session_id):
    """
    1. Sets the current Django session to this chat_id (so the next API call appends here).
    2. Returns all messages for this chat to render the history.
    """
    chat = get_object_or_404(ChatSession, id=session_id)
    request.session['chat_id'] = chat.id  # <--- CRITICAL: Updates context for chat_api
    
    messages = chat.messages.all().order_by('created_at')
    data = [
        {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.strftime("%H:%M")
        }
        for m in messages
    ]
    return JsonResponse({"session_id": chat.id, "messages": data})

def new_chat(request):
    """Clears the session ID to force a new chat on next message."""
    if 'chat_id' in request.session:
        del request.session['chat_id']
    return JsonResponse({"status": "success"})


@csrf_exempt 
def trigger_scribe(request):
    """
    Manual trigger to run the Scribe consolidation.
    Useful for testing the logic without waiting for a Celery beat.
    """
    scribe = ScribeService()
    # Let's process the first 50 chunks for the test
    result_message = scribe.run_full_consolidation(batch_size=30)
    
    return JsonResponse({
        "status": "complete",
        "result": result_message
    })

def chat_debug(request, session_id=None):
    """Renders the 'Behind the Curtain' view for a specific session."""
    try:
        session = ChatSession.objects.get(id=session_id)
        prompts = PromptLog.objects.filter(session=session).order_by('-created_at')
        memories = MemoryChunk.objects.filter(
            source_message__session=session
        ).order_by('-created_at')
    except ChatSession.DoesNotExist:
        session = None
        prompts = PromptLog.objects.filter().order_by('-created_at')
        memories = MemoryChunk.objects.filter().order_by('-created_at')
    
    context = {
        "session": session,
        "prompts": prompts,
        "memories": memories
    }
    return render(request, "core/debug.html", context)