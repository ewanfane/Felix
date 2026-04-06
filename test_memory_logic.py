import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Felix.settings')
django.setup()

from core.models import ChatSession, ChatMessage

def test_context_logic():
    # Create a dummy session
    session = ChatSession.objects.create(title="Test Session")
    
    # AI Message
    ai_msg = ChatMessage.objects.create(
        session=session,
        role='assistant',
        content="I recommend using a vector database for long-term memory."
    )
    
    # User Message (The one we'll process)
    user_msg = ChatMessage.objects.create(
        session=session,
        role='user',
        content="Yes, that sounds perfect."
    )
    
    # Logic from tasks.py
    prev_ai = ChatMessage.objects.filter(
        session=user_msg.session,
        role='assistant',
        created_at__lt=user_msg.created_at
    ).order_by('-created_at').first()
    
    print(f"User Message: {user_msg.content}")
    if prev_ai:
        print(f"Found Prev AI: {prev_ai.content}")
        context_payload = f"AI PREVIOUS RESPONSE: \"{prev_ai.content}\"\nUSER REPLY: \"{user_msg.content}\""
        print(f"Final Payload to LLM:\n{context_payload}")
    else:
        print("No Prev AI found!")

if __name__ == "__main__":
    test_context_logic()
