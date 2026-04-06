import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Felix.settings')
django.setup()

from core.models import PromptLog, MemoryChunk

def get_last_run_details():
    last_prompt = PromptLog.objects.order_by('-created_at').first()
    if not last_prompt:
        print("No prompt logs found.")
        return

    print("--- LAST PROMPT (Plan+Final Prompt) ---")
    try:
        data = json.loads(last_prompt.full_prompt)
        print(f"PLAN:\n{data.get('plan')}")
        print("\n--- FINAL SYSTEM PROMPT ---")
        print(data.get('final_instructions'))
    except:
        print(last_prompt.full_prompt)

    print("\n--- RECENT MEMORY CHUNKS ---")
    chunks = MemoryChunk.objects.order_by('-created_at')[:5]
    for c in chunks:
        print(f"ID: {c.id} | Content: {c.content[:100]} | Created: {c.created_at}")

if __name__ == "__main__":
    get_last_run_details()
