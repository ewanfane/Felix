from datetime import datetime
from ..services.filesystem import FileSystemService

PROFILE_FILE = "user/profile.md"
MAX_FILE_SIZE = 10240

DEFAULT_PROFILE = """# User Profile

## Identity
_Not yet known._

## Communication Fingerprint
_Not yet observed._

## Knowledge & Expertise
_Not yet mapped._

## Goals
_Not yet discovered._

## Preferences
_Not yet learned._

## Role Expectations
_Not yet established._

## Metadata
- First met: {first_met}
- Last interaction: {last_interaction}
- Total interactions: {interaction_count}
"""

TEXT_SIMILARITY_THRESHOLD = 0.6


def _texts_overlap(a, b, threshold=TEXT_SIMILARITY_THRESHOLD):
    a_lower = a.lower()
    b_lower = b.lower()
    a_words = set(a_lower.split())
    b_words = set(b_lower.split())
    if not a_words or not b_words:
        return False
    intersection = a_words & b_words
    smaller = min(len(a_words), len(b_words))
    return len(intersection) / smaller >= threshold


def _is_substantially_new(existing_text, new_line):
    existing_lower = existing_text.lower()
    new_lower = new_line.strip().lower().lstrip("- ").strip()
    if not new_lower:
        return False
    for existing_line in existing_text.split("\n"):
        el = existing_line.strip().lower().lstrip("- ").strip()
        if el and _texts_overlap(el, new_lower):
            return False
    return new_lower not in existing_lower


class UserModelService:
    def __init__(self):
        self.fs = FileSystemService()
        self._profile_text = None
        self._sections = None
        self._metadata = {
            "first_met": "",
            "last_interaction": "",
            "interaction_count": 0,
        }

    def _load_profile(self):
        raw = self.fs.read_file(PROFILE_FILE)
        if not raw or raw.startswith("Error"):
            now = datetime.now().isoformat()
            self._profile_text = DEFAULT_PROFILE.format(
                first_met=now,
                last_interaction=now,
                interaction_count=0,
            )
            self._sections = self._parse_sections(self._profile_text)
            self._metadata = self._parse_metadata(self._profile_text)
            self._metadata["first_met"] = now
            self._metadata["last_interaction"] = now
            self._metadata["interaction_count"] = 0
            self._save_profile()
        else:
            self._profile_text = raw
            self._sections = self._parse_sections(raw)
            self._metadata = self._parse_metadata(raw)

    def get_profile_text(self):
        if self._profile_text is None:
            self._load_profile()
        return self._profile_text

    def get_context(self):
        return self.get_profile_text()

    def get_sections(self):
        if self._sections is None:
            self._load_profile()
        return self._sections

    def get_metadata(self):
        if self._metadata is None:
            self._load_profile()
        return self._metadata

    def get_name(self):
        identity = self.get_sections().get("Identity", "")
        for line in identity.split("\n"):
            line = line.strip()
            if line.lower().startswith("name"):
                return line.split(":", 1)[1].strip()
        return ""

    def get_gaps(self):
        gaps = []
        for key, section in self.get_sections().items():
            content = section.strip()
            if content.startswith("_Not yet") or content.startswith("Not yet"):
                gaps.append(key.lower().replace(" & ", "_").replace(" ", "_"))
        return gaps

    def update_from_insight(self, insight_data):
        if insight_data.get("skip"):
            return

        sections = dict(self.get_sections())
        metadata = dict(self.get_metadata())
        now = datetime.now().isoformat()
        evolving = False

        narrative = insight_data.get("narrative", "").strip()
        facts_text = insight_data.get("facts", "").strip()

        if narrative:
            sections["Last Conversation Insight"] = narrative
            evolving = True

        if facts_text:
            for line in facts_text.split("\n"):
                line = line.strip()
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip()
                if not value:
                    continue

                if key == "name":
                    current = sections.get("Identity", "")
                    if current == "_Not yet known._":
                        sections["Identity"] = f"Name: {value}"
                        evolving = True
                    elif "Name:" not in current:
                        sections["Identity"] = f"Name: {value}\n" + current
                        evolving = True

                elif key == "communication_style":
                    current = sections.get("Communication Fingerprint", "")
                    if current == "_Not yet observed._":
                        sections["Communication Fingerprint"] = value
                        evolving = True
                    elif _is_substantially_new(current, value):
                        sections["Communication Fingerprint"] = current + "\n- " + value
                        evolving = True

                elif key == "expertise":
                    current = sections.get("Knowledge & Expertise", "")
                    if current == "_Not yet mapped._":
                        sections["Knowledge & Expertise"] = value
                        evolving = True
                    elif _is_substantially_new(current, value):
                        sections["Knowledge & Expertise"] = current + "\n- " + value
                        evolving = True

                elif key == "goals":
                    current = sections.get("Goals", "")
                    if current == "_Not yet discovered._":
                        sections["Goals"] = value
                        evolving = True
                    elif _is_substantially_new(current, value):
                        sections["Goals"] = current + "\n- " + value
                        evolving = True

                elif key == "preferences":
                    current = sections.get("Preferences", "")
                    if current == "_Not yet learned._":
                        sections["Preferences"] = value
                        evolving = True
                    elif _is_substantially_new(current, value):
                        sections["Preferences"] = current + "\n- " + value
                        evolving = True

                elif key == "role_expectations":
                    current = sections.get("Role Expectations", "")
                    if current == "_Not yet established._":
                        sections["Role Expectations"] = value
                        evolving = True
                    elif _is_substantially_new(current, value):
                        sections["Role Expectations"] = current + "\n- " + value
                        evolving = True

        if evolving:
            metadata["last_interaction"] = now
            metadata["interaction_count"] = metadata.get("interaction_count", 0) + 1
            self._sections = sections
            self._metadata = metadata
            self._profile_text = self._build_document(sections, metadata)
            self._save_profile()
            self._check_size()

    def ensure_capacity(self):
        self.get_profile_text()
        return self._check_size()

    def _check_size(self):
        if len(self._profile_text) > MAX_FILE_SIZE:
            self._compress_profile()
            return True
        return False

    def _compress_profile(self):
        sections = dict(self.get_sections())
        insight = sections.get("Last Conversation Insight", "")
        if insight:
            lines = insight.split("\n")
            if len(lines) > 5:
                sections["Last Conversation Insight"] = "\n".join(lines[:3]) + "\n\n_[Full insight compressed. See conversation history for details.]_"
                self._sections = sections
                self._profile_text = self._build_document(sections, self._metadata)
                self._save_profile()

    def is_onboarding_complete(self):
        sections = self.get_sections()
        filled = 0
        total = 0
        for key in ["Identity", "Communication Fingerprint", "Knowledge & Expertise", "Goals", "Preferences", "Role Expectations"]:
            content = sections.get(key, "").strip()
            total += 1
            if content and not content.startswith("_Not yet") and not content.startswith("Not yet"):
                filled += 1
        return filled >= 3

    def fill_placeholder_count(self):
        sections = self.get_sections()
        count = 0
        for key in ["Identity", "Communication Fingerprint", "Knowledge & Expertise", "Goals", "Preferences", "Role Expectations"]:
            content = sections.get(key, "").strip()
            if content.startswith("_Not yet") or content.startswith("Not yet"):
                count += 1
        return count

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

    def _parse_metadata(self, text):
        metadata = {"first_met": "", "last_interaction": "", "interaction_count": 0}
        for line in text.split("\n"):
            line = line.strip().lstrip("-").strip()
            if line.lower().startswith("first met"):
                metadata["first_met"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line.lower().startswith("last interaction"):
                metadata["last_interaction"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line.lower().startswith("total interactions"):
                try:
                    metadata["interaction_count"] = int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    metadata["interaction_count"] = 0
        return metadata

    def _build_document(self, sections, metadata):
        lines = ["# User Profile", ""]
        for heading, content in sections.items():
            if heading == "Metadata" or heading == "Last Conversation Insight":
                continue
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(content)
            lines.append("")

        if sections.get("Last Conversation Insight"):
            lines.append("## Last Conversation Insight")
            lines.append("")
            lines.append(sections["Last Conversation Insight"])
            lines.append("")

        lines.append("## Metadata")
        lines.append("")
        lines.append(f"- First met: {metadata.get('first_met', '')}")
        lines.append(f"- Last interaction: {metadata.get('last_interaction', '')}")
        lines.append(f"- Total interactions: {metadata.get('interaction_count', 0)}")

        return "\n".join(lines)

    def _save_profile(self):
        self.fs.write_file(PROFILE_FILE, self._profile_text)
