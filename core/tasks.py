import json
from celery import shared_task
from .models import ChatMessage, MemoryChunk
from .services.llm import LLMService
from .services.embedding import EmbeddingService
from .services.filesystem import FileSystemService
from .services.scribe import ScribeService
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
            # === NEW: Load Personality for Audit ===
            try:
                personality_text = fs.read_file("personality.md")
            except:
                personality_text = "Standard Professional Assistant."

            prompt = AI_CHUNKING_PROMPT.format(
                ai_response=message.content,
                personality_profile=personality_text
            )
            system_role = "You are an AI Persona and Metacognition Auditor."

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
            reflection=chunk_data['reflection'],  # The Private Audit
            metadata=chunk_data['metadata'],      # Tags + Evolution Stage
            source_message=message
        )

        message.processed = True
        message.save()
        return "Success: Created 1 Structured Chunk"

    except Exception as e:
        return f"Memory Task Error: {str(e)}"


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

        fs = FileSystemService()
        results = []
        for act in actions:
            if act.get('action') == 'write' and 'path' in act:
                res = fs.write_file(act['path'], act['content'])
                results.append(f"Wrote {act['path']}")
        
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
    # Batch size controls how much memory/tokens we use per run.
    result = scribe.run_full_consolidation(batch_size=50)
    return result