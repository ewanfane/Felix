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
        # --- STAGE 1: GROUPING (JSON is fine here for simple lists) ---
        raw_chunks = MemoryChunk.objects.filter(consolidated=False).order_by('created_at')[:batch_size]
        if not raw_chunks.exists(): return "No chunks."

        # Prepare simple summary for the LLM to group
        chunk_summary = [{"id": c.id, "content": c.content[:200]} for c in raw_chunks]
        
        grouper_msg = [{"role": "user", "content": GROUPER_PROMPT.format(chunk_list=json.dumps(chunk_summary))}]
        resp = self.llm.get_response(grouper_msg, stream=False)
        
        # We use strict=False to allow for minor LLM formatting errors
        group_data = self._extract_json(resp.choices[0].message.content)
        
        if not group_data: return "Grouping Failed."

        results = []
        for group in group_data.get('groups', []):
            outcome = self._process_group_pipeline(group)
            results.append(outcome)
            
        return f"Results: {results}"

    def _process_group_pipeline(self, group):
        topic = group.get('topic_name', 'General')
        chunk_ids = group.get('chunk_ids', [])
        
        if not chunk_ids: return f"Skipped[{topic}]: No IDs"

        relevant_chunks = MemoryChunk.objects.filter(id__in=chunk_ids)

        # --- STAGE 2: WRITING (Raw Markdown) ---
        # The LLM writes a full markdown file here.
        raw_data = [{"content": c.content, "reflection": c.reflection} for c in relevant_chunks]
        writer_prompt = STAGE_2_WRITER_PROMPT.format(topic_name=topic, chunk_list=json.dumps(raw_data))
        
        # Direct content extraction - no parsing needed for pure markdown
        file_content = self.llm.get_response([{"role": "user", "content": writer_prompt}], stream=False).choices[0].message.content

        # Generate a clean filename for the Knowledge Graph
        # e.g., "KNOWLEDGE/relational_ontology.md"
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', topic.lower())[:40]
        file_path = f"KNOWLEDGE/{safe_name}.md"

        # --- STAGE 3: SUMMARIZING (XML/TAG PARSING) ---
        # This is where we switched from JSON to XML tags to prevent parsing crashes
        summarizer_prompt = STAGE_3_SUMMARIZER_PROMPT.format(file_content=file_content)
        summary_resp = self.llm.get_response([{"role": "user", "content": summarizer_prompt}], stream=False).choices[0].message.content
        
        # USE NEW PARSER
        summary_data = self._extract_xml_content(summary_resp)

        if not summary_data["master_chunk_content"]: 
            return f"Fail[{topic}]: XML Parsing returned empty content"

        # --- FINAL COMMIT ---
        try:
            with transaction.atomic():
                # 1. Write the full markdown file to disk
                self.fs.write_file(file_path, file_content)
                
                # 2. Create the Master Chunk in Vector DB
                # This serves as the "Index" pointing to the file
                vector = self.embedder.embed_text(summary_data['master_chunk_content'])
                
                MemoryChunk.objects.create(
                    content=summary_data['master_chunk_content'],
                    embedding=vector,
                    reflection=summary_data['reflection'], # <--- SAVING THE REFLECTION
                    consolidated=True, # Mark as safe
                    metadata={
                        "topic": topic, 
                        "type": "master_node",
                        "file_path": file_path 
                    }
                )

                # 3. Append Behavioral Learnings
                if summary_data['learnings']:
                    self._append_learnings(summary_data['learnings'])

                # 4. Cleanup: Delete the raw thoughts now that they are consolidated
                relevant_chunks.delete()

            return f"Success[{topic}]"
            
        except Exception as e:
            return f"Error[{topic}]: {e}"

    def _extract_xml_content(self, raw_text):
        """
        Robustly extracts content from XML-style tags.
        Safe for newlines, quotes, and long-form text.
        """
        response_data = {
            "master_chunk_content": "",
            "reflection": "", # <--- ADDED FIELD
            "learnings": []
        }

        # 1. Extract Master Chunk
        # DOTALL is crucial: it allows (.) to match newlines (\n)
        chunk_match = re.search(r'<master_chunk>(.*?)</master_chunk>', raw_text, re.DOTALL)
        if chunk_match:
            response_data["master_chunk_content"] = chunk_match.group(1).strip()

        # 3. Extract Learnings
        learnings_match = re.search(r'<learnings>(.*?)</learnings>', raw_text, re.DOTALL)
        if learnings_match:
            learnings_text = learnings_match.group(1).strip()
            # Convert bullet points or newlines to list items
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
        """
        Simple JSON extractor for the Grouping Stage.
        """
        try:
            text = text.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0), strict=False)
        except:
            return None
        return None