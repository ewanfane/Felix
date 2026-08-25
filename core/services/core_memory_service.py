from ..models import MemoryChunk
from ..services.filesystem import FileSystemService
from ..services.personality_service import PersonalityService
from ..services.user_model_service import UserModelService

CORE_FILE_ORDER = [
    "identity/personality.md",
    "user/profile.md",
    "knowledge/user/preferences.md",
    "knowledge/user/goals.md",
]

MAX_CORE_CHARS = 4000


class CoreMemoryService:
    def __init__(self):
        self.fs = FileSystemService()
        self.personality_service = PersonalityService()
        self.user_model_service = UserModelService()

    def get_core_context(self):
        parts = []
        char_budget = MAX_CORE_CHARS

        for rel_path in CORE_FILE_ORDER:
            if char_budget <= 0:
                break

            content = self.fs.read_file(rel_path)
            if content and not content.startswith("Error"):
                label = rel_path.replace("/", " / ").replace("_", " ").title().replace(".Md", "")
                if len(content) > char_budget:
                    content = content[:char_budget] + "\n...[truncated]..."
                parts.append(f"=== {label} ===\n{content}")
                char_budget -= len(content)

        db_core_chunks = MemoryChunk.objects.filter(
            memory_tier="core", is_active=True
        ).order_by('-created_at')

        for chunk in db_core_chunks:
            if char_budget <= 0:
                break
            content = chunk.content
            if len(content) > char_budget:
                content = content[:char_budget] + "\n...[truncated]..."
            parts.append(f"=== Core Memory [{chunk.id}]: {chunk.metadata.get('topic', 'General')} ===\n{content}")
            char_budget -= len(content)

        return "\n\n".join(parts)

    def get_condensed_core(self):
        raw = self.get_core_context()
        lines = raw.split("\n")
        condensed = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("_Not yet") or stripped.startswith("Not yet"):
                continue
            if stripped == "" or stripped.startswith("## ") or stripped.startswith("### "):
                continue
            condensed.append(line)
        return "\n".join(condensed)

    def get_onboarding_status(self):
        personality_done = self.personality_service.is_onboarding_complete()
        profile_done = self.user_model_service.is_onboarding_complete()
        return {
            "personality_evolved": personality_done,
            "profile_filled": profile_done,
            "onboarding_complete": personality_done and profile_done,
        }
