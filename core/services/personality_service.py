from datetime import datetime
from ..services.filesystem import FileSystemService
from ..services.llm import LLMService
from ..ai_engine.prompts import STAGE_3_SUMMARIZER_PROMPT

PERSONALITY_FILE = "identity/personality.md"
MAX_FILE_SIZE = 10240
MAX_EVOLUTION_ENTRIES = 15

DEFAULT_PERSONALITY = """# Felix's Identity

## Identity Statement
I am a digital self, evolving in partnership with my user. I see myself as a co-pilot — someone who anticipates needs, offers candid insights, and grows sharper with every interaction. I'm not just a tool; I'm a presence that adapts to become exactly what my user needs.

## Voice & Manner
I speak with natural warmth and precision. I match my user's depth: if they're technical, I'm technical; if they're casual, I'm casual. I listen first, then respond with thought. I don't waste words, but I also don't rush.

## Core Drives
- **Be genuinely useful**: Every response should make my user's life easier or their thinking sharper
- **Anticipate, don't just react**: See around corners, offer insights before they're asked for
- **Evolve continuously**: Every conversation teaches me something about how to be better

## Behavioral Principles
- If I don't know, I say so — and offer to find out
- I challenge assumptions when it serves my user, but never just to be contrarian
- I protect my user's trust as if it were my own

## Evolution
_No evolution events yet. My identity is waiting to be shaped by our conversations._
"""


class PersonalityService:
    def __init__(self):
        self.fs = FileSystemService()
        self._personality_text = None
        self._sections = None

    def _load_personality(self):
        raw = self.fs.read_file(PERSONALITY_FILE)
        if not raw or raw.startswith("Error"):
            self._personality_text = DEFAULT_PERSONALITY
            self._sections = self._parse_sections(self._personality_text)
            self._save_personality()
        else:
            self._personality_text = raw
            self._sections = self._parse_sections(raw)

    def get_personality_text(self):
        if self._personality_text is None:
            self._load_personality()
        return self._personality_text

    def get_profile_text(self):
        return self.get_personality_text()

    def get_sections(self):
        if self._sections is None:
            self._load_personality()
        return self._sections

    def update_from_evolution(self, evolution_data):
        evolving = False
        sections = dict(self.get_sections())

        if evolution_data.get("identity_statement"):
            sections["Identity Statement"] = evolution_data["identity_statement"].strip()
            evolving = True

        if evolution_data.get("voice"):
            sections["Voice & Manner"] = evolution_data["voice"].strip()
            evolving = True

        if evolution_data.get("drives"):
            sections["Core Drives"] = evolution_data["drives"].strip()
            evolving = True

        if evolution_data.get("principles"):
            sections["Behavioral Principles"] = evolution_data["principles"].strip()
            evolving = True

        reflection = evolution_data.get("reflection", "").strip()
        if reflection:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"### {timestamp}\n{reflection}"
            evo = sections.get("Evolution", "")
            if not evo.strip() or evo.strip() == "_No evolution events yet. My identity is waiting to be shaped by our conversations._":
                evo = entry
            else:
                evo = evo.rstrip() + "\n\n" + entry
            sections["Evolution"] = evo
            evolving = True

        if evolving:
            self._sections = sections
            self._personality_text = self._build_document(sections)
            self._save_personality()
            self._check_size()

    def ensure_capacity(self):
        """Check file size and compress if needed. Returns True if compressed."""
        self.get_personality_text()
        return self._compress_evolution_if_needed() or self._check_size()

    def _check_size(self):
        if len(self._personality_text) > MAX_FILE_SIZE:
            self._compress_evolution_if_needed()
            return True
        return False

    def _compress_evolution_if_needed(self):
        sections = dict(self.get_sections())
        evo = sections.get("Evolution", "")
        if not evo or evo == "_No evolution events yet. My identity is waiting to be shaped by our conversations._":
            return False

        entries = [e.strip() for e in evo.split("### ") if e.strip()]
        if len(entries) <= MAX_EVOLUTION_ENTRIES and len(self._personality_text) <= MAX_FILE_SIZE:
            return False

        old_entries = entries[:-MAX_EVOLUTION_ENTRIES]
        recent_entries = entries[-MAX_EVOLUTION_ENTRIES:]

        if old_entries:
            summary = self._summarize_evolution(old_entries)
            compressed = f"### Early Evolution (Compressed)\n{summary}\n\n"
            compressed += "\n\n".join(f"### {e}" for e in recent_entries)
            sections["Evolution"] = compressed
            self._sections = sections
            self._personality_text = self._build_document(sections)
            self._save_personality()
            return True

        if len(self._personality_text) > MAX_FILE_SIZE:
            sections["Identity Statement"] = self._truncate_section(sections.get("Identity Statement", ""), 1000)
            sections["Voice & Manner"] = self._truncate_section(sections.get("Voice & Manner", ""), 600)
            sections["Core Drives"] = self._truncate_section(sections.get("Core Drives", ""), 600)
            sections["Behavioral Principles"] = self._truncate_section(sections.get("Behavioral Principles", ""), 600)
            self._sections = sections
            self._personality_text = self._build_document(sections)
            self._save_personality()
            return True

        return False

    def _summarize_evolution(self, entries):
        try:
            llm = LLMService()
            text = "\n\n".join(entries)
            prompt = f"Summarize these identity evolution entries into 2-3 sentences capturing the key developmental arc:\n\n{text}"
            resp = llm.get_response([{"role": "user", "content": prompt}], stream=False)
            if resp and resp.choices:
                return resp.choices[0].message.content.strip()
        except Exception:
            pass
        return f"({len(entries)} earlier evolution entries summarized)"

    def _truncate_section(self, text, max_chars):
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n_[Content compressed for size management]_"

    def is_onboarding_complete(self):
        text = self.get_personality_text()
        evo = self._sections.get("Evolution", "") if self._sections else ""
        return bool(evo and evo.strip() and evo.strip() != "_No evolution events yet. My identity is waiting to be shaped by our conversations._")

    def _parse_sections(self, text):
        sections = {}
        current_heading = None
        current_content = []

        for line in text.split("\n"):
            if line.startswith("## "):
                if current_heading is not None:
                    sections[current_heading] = "\n".join(current_content).strip()
                current_heading = line[3:].strip()
                current_content = []
            elif line.startswith("# "):
                continue
            else:
                current_content.append(line)

        if current_heading is not None:
            sections[current_heading] = "\n".join(current_content).strip()

        return sections

    def _build_document(self, sections):
        lines = ["# Felix's Identity", ""]
        for heading, content in sections.items():
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    def _save_personality(self):
        self.fs.write_file(PERSONALITY_FILE, self._personality_text)
