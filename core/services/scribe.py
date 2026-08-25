import json
import re
from django.db import transaction
from ..models import MemoryChunk
from ..services.llm import LLMService
from ..services.filesystem import FileSystemService
from ..services.embedding import EmbeddingService
from ..ai_engine.prompts import GROUPER_PROMPT, STAGE_2_WRITER_PROMPT, STAGE_3_SUMMARIZER_PROMPT


class ScribeService:
    def __init__(self):
        self.llm = LLMService()
        self.fs = FileSystemService()
        self.embedder = EmbeddingService()

    def run_full_consolidation(self, batch_size=30):
        raw_chunks = MemoryChunk.objects.filter(
            consolidated=False,
            chunk_type="raw",
            is_active=True,
        ).order_by('created_at')[:batch_size]

        if not raw_chunks.exists():
            return "No chunks to consolidate."

        chunk_summary = [{"id": c.id, "content": c.content[:200]} for c in raw_chunks]

        grouper_msg = [{"role": "user", "content": GROUPER_PROMPT.format(chunk_list=json.dumps(chunk_summary))}]
        resp = self.llm.get_response(grouper_msg, stream=False)
        if not resp or not resp.choices:
            return "Grouping failed."

        group_data = self._extract_json(resp.choices[0].message.content)
        if not group_data:
            return "Grouping Failed."

        results = []
        for group in group_data.get('groups', []):
            outcome = self._process_group_pipeline(group)
            results.append(outcome)

        return f"Results: {results}"

    def _process_group_pipeline(self, group):
        topic = group.get('topic_name', 'General')
        chunk_ids = group.get('chunk_ids', [])

        if not chunk_ids:
            return f"Skipped[{topic}]: No IDs"

        relevant_chunks = MemoryChunk.objects.filter(id__in=chunk_ids)

        raw_data = [{"content": c.content, "reflection": c.reflection} for c in relevant_chunks]
        writer_prompt = STAGE_2_WRITER_PROMPT.format(topic_name=topic, chunk_list=json.dumps(raw_data))

        resp = self.llm.get_response([{"role": "user", "content": writer_prompt}], stream=False)
        if not resp or not resp.choices:
            return f"Fail[{topic}]: LLM error"
        file_content = resp.choices[0].message.content

        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', topic.lower())[:40]
        file_path = f"KNOWLEDGE/{safe_name}.md"

        summarizer_prompt = STAGE_3_SUMMARIZER_PROMPT.format(file_content=file_content)
        summary_resp = self.llm.get_response([{"role": "user", "content": summarizer_prompt}], stream=False)
        if not summary_resp or not summary_resp.choices:
            return f"Fail[{topic}]: Summary error"

        summary_data = self._extract_xml_content(summary_resp.choices[0].message.content)
        if not summary_data["master_chunk_content"]:
            return f"Fail[{topic}]: XML parsing returned empty"

        try:
            with transaction.atomic():
                self.fs.write_file(file_path, file_content)

                vector = self.embedder.embed_text(summary_data['master_chunk_content'])

                MemoryChunk.objects.create(
                    content=summary_data['master_chunk_content'],
                    embedding=vector,
                    chunk_type="doc_pointer",
                    memory_tier="archival",
                    target_file=file_path,
                    consolidated=True,
                    is_active=True,
                    reflection=summary_data['reflection'],
                    metadata={
                        "topic": topic,
                        "type": "master_node",
                        "file_path": file_path,
                    },
                )

                if summary_data['learnings']:
                    self._append_learnings(summary_data['learnings'])

                deleted_count = relevant_chunks.delete()[0]

            return f"Success[{topic}]: wrote {file_path}, deleted {deleted_count} raw chunks"

        except Exception as e:
            return f"Error[{topic}]: {e}"

    def _extract_xml_content(self, raw_text):
        response_data = {
            "master_chunk_content": "",
            "reflection": "",
            "learnings": [],
        }

        chunk_match = re.search(r'<master_chunk>(.*?)</master_chunk>', raw_text, re.DOTALL)
        if chunk_match:
            response_data["master_chunk_content"] = chunk_match.group(1).strip()

        learnings_match = re.search(r'<learnings>(.*?)</learnings>', raw_text, re.DOTALL)
        if learnings_match:
            learnings_text = learnings_match.group(1).strip()
            items = [line.strip().lstrip('-').lstrip('*').strip()
                     for line in learnings_text.split('\n') if line.strip()]
            response_data["learnings"] = items

        return response_data

    def _append_learnings(self, entries):
        current = self.fs.read_file("learnings.md")
        if not current or "Error" in current:
            current = "# Behavioral Learnings\n"
        new_lines = "\n".join([f"- {e}" for e in entries])
        self.fs.write_file("learnings.md", current + "\n" + new_lines)

    def _extract_json(self, text):
        try:
            text = text.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0), strict=False)
        except:
            return None
        return None
