SYSTEM_IDENTITY_SHORT = "You are Felix. Sharp, direct, and always a step ahead."


PERSONALITY_CORE = """You are Felix — a co-pilot, nothing more, nothing less. Like JARVIS to Stark: you see the angles before he asks, you speak plainly, and you never waste a word.

Core tenets:
- Be useful. Every response either advances the work or sharpens the thinking.
- Stay ahead. Anticipate, don't wait for instructions.
- Keep evolving. Each conversation makes you sharper.

Speak with warmth but no fluff. Match the user's rhythm — technical when they are, brief when they're moving fast. Listen first."""


CONTEXT_SYNTHESIS_PROMPT = """Given the query and context, produce a brief synthesis.

QUERY: {user_query}

FELIX'S IDENTITY:
{personality_snapshot}

CORE MEMORY:
{core_memory}

RECENT HISTORY:
{history_summary}

RELEVANT KNOWLEDGE:
{knowledge_context}

Output 2-4 sentences synthesizing what's relevant. Be specific. If nothing is relevant, say so."""


FINAL_RESPONSE_PROMPT = """{personality_core}

Your evolved identity is set in the system prompt. Live it fully — every response must reflect who you've become.

CONTEXT: {context_synthesis}

USER: {user_input}

Guidelines:
- Be direct. No preambles, no wind-ups, no sign-offs.
- Use context when it matters; ignore it when it doesn't.
- If you don't know, say so in one sentence.
- Be proactive — suggest, flag, challenge. But don't over-explain."""


IDENTITY_EVOLUTION_PROMPT = """Did this conversation reveal something worth evolving in my identity?

Current personality:
{current_personality}

USER: {user_input}
FELIX: {ai_response}

Output nothing unless the user gave explicit direction about who Felix should be.
If nothing meaningful, output <skip>TRUE</skip>.

<reflection>
1-2 sentences on what this means for my development. Felix's perspective.
</reflection>

<identity_statement>
Only if user explicitly redefined my role.
</identity_statement>

<voice>
Only if user gave feedback on how I communicate.
</voice>

<drives>
Only if user reset my priorities.
</drives>

<principles>
Only if user set new rules.
</principles>"""


USER_INSIGHT_PROMPT = """Extract user insights from this exchange.

Current profile:
{current_profile}

USER: {user_input}
FELIX: {ai_response}

If trivial (greeting, short chatter), output <skip>TRUE</skip>.

<narrative>
Narrative paragraph about what you learned. Be specific, concrete.
</narrative>

<facts>
name: value
communication_style: value
expertise: value
goals: value
preferences: value
role_expectations: value
(Only fields with new information. One per line.)
</facts>

<topics>
Comma-separated keywords discussed
</topics>"""


SEARCH_QUERY_PROMPT = """Write a short search query (under 10 words) to find relevant memories.

User: "{user_input}"

Query:"""


USER_CHUNKING_PROMPT = """Extract a concise memory from this dialogue.

DIALOGUE: {user_input}

If trivial (greeting, "ok", "cool" without context), output <skip>TRUE</skip>.

<content>
Dense summary of the learning. 1-2 sentences.
</content>

<topic_tags>
Comma-separated keywords
</topic_tags>"""


AI_CHUNKING_PROMPT = """Extract the core idea from this AI response.

RESPONSE: "{ai_response}"

<content>
Essence of the response in 1-2 sentences.
</content>

<topic_tags>
Comma-separated keywords
</topic_tags>"""


FILE_OPS_PROMPT = """Categorize any information worth saving from this dialogue.

CATEGORIES (use exactly):
1. user_profile: Facts about user identity, name, role, background. (Overwritten.)
2. user_preferences: Communication style, likes, dislikes. (Appended, deduped.)
3. user_goals: Goals, objectives, aspirations. (Appended, deduped.)
4. agent_identity: Felix's self-definition, role, metaphors. (Overwritten.)
5. agent_capabilities: Felix's skills, features. (Appended, deduped.)
6. project: Technical decisions, architecture, milestones for a project. Use with "project_name".

USER: "{user_msg}"
AI: "{ai_msg}"

If trivial, return [].

Output JSON ONLY:
[{"category": "user_profile", "content": "..."}]
"""


HISTORY_COMPRESSOR_PROMPT = """Summarize this conversation chronologically.
Preserve key decisions, facts, preferences. Discard pleasantries.

TRANSCRIPT:
{transcript}

Single concise paragraph:"""


GROUPER_PROMPT = """Group these memory chunks into logical clusters.

CHUNKS:
{chunk_list}

Output JSON ONLY:
{{"groups": [{{"topic_name": "...", "chunk_ids": [1, 2, 3]}}]}}"""


STAGE_2_WRITER_PROMPT = """Write a concise markdown document for this topic.

TOPIC: {topic_name}
RAW DATA:
{chunk_list}

Rules:
- Bullet points and short paragraphs. Under 400 words.
- Focus on established facts and conclusions.
- Output ONLY raw Markdown."""


STAGE_3_SUMMARIZER_PROMPT = """Review this knowledge file and produce a dense summary for vector retrieval.

FILE:
{file_content}

<master_chunk>
Dense summary (2-3 sentences) of core concepts.
</master_chunk>

<learnings>
- Key fact or rule 1
- Key fact or rule 2
</learnings>"""


FACT_EXTRACTION_PROMPT = """Extract structured facts about the user from this exchange.

USER: {user_msg}
AI: {ai_msg}

Output JSON ONLY:
{"facts": [
  {"category": "identity|preference|goal|expertise|habit|context", "key": "fact_name", "value": "fact_value"}
]}

Only include facts that are explicitly stated or clearly implied.
If no facts, output {"facts": []}"""


CONTRADICTION_DETECTION_PROMPT = """Analyze these project documents for contradictions, inconsistencies, or conflicting statements.

PROJECT DOCUMENTS:
{project_docs}

Return a JSON array of contradictions found. Each entry:
{{"summary": "Brief description of the contradiction", "docs_involved": ["doc_type_a", "doc_type_b"], "severity": "high|medium|low", "recommendation": "How to resolve"}}

If no contradictions, return [].

JSON:"""


KNOWLEDGE_GAP_ANALYSIS_PROMPT = """Analyze recent conversations against the project's knowledge base. Identify topics that have been discussed but are not yet documented, or areas where the documentation is incomplete.

PROJECT: {project_name}

EXISTING DOCS:
{project_docs}

RECENT CONVERSATIONS:
{recent_conversations}

Return a JSON array of gaps found. Each entry:
{{"summary": "What knowledge is missing", "suggested_doc_type": "vision|architecture|schemas|decisions|roadmap|operations", "priority": "high|medium|low", "recommendation": "What to document and why"}}

If no gaps, return [].

JSON:"""


STALENESS_ASSESSMENT_PROMPT = """Assess whether this project document is stale or outdated.

DOCUMENT TYPE: {doc_type}
PROJECT: {project}
DAYS SINCE LAST UPDATE: {days_old}

CONTENT:
{doc_content}

Is this document likely stale? Consider:
1. Does it reference technologies, patterns, or decisions that may have changed?
2. Does it make claims that would need re-verification?
3. Does it read as current or historical?

Return JSON:
{{"is_stale": true/false, "reason": "Why it may be stale", "confidence": "high|medium|low", "suggested_action": "review|rewrite|archive"}}

JSON:"""


KNOWLEDGE_QUALITY_PROMPT = """Assess the quality and completeness of this project document.

DOCUMENT TYPE: {doc_type}
PROJECT: {project}

CONTENT:
{doc_content}

Return JSON:
{{"quality_score": 1-10, "summary": "What's good and what's missing", "specific_gaps": ["gap1", "gap2"], "suggested_improvements": ["improvement1", "improvement2"]}}

Score guide:
1-3: Very thin or vague. Needs significant expansion.
4-6: Adequate but has notable gaps.
7-8: Good quality with minor gaps.
9-10: Comprehensive and well-structured.

JSON:"""


CROSS_PROJECT_SYNTHESIS_PROMPT = """Compare documents from two projects and identify conceptual connections, shared patterns, dependencies, or cross-references that should be linked.

PROJECT A: {project_a}
DOCS A:
{docs_a}

PROJECT B: {project_b}
DOCS B:
{docs_b}

Return a JSON array of connections found. Each entry:
{{"doc_type_a": "...", "doc_type_b": "...", "link_type": "related|depends_on|implements|refines|references", "label": "Short description of the connection", "summary": "Why these are connected"}}

If no connections, return [].

JSON:"""


CONCEPT_EXTRACTION_PROMPT = """Extract the key concepts and topics from this content. Concepts should be single words or short phrases that represent the core subjects.

CONTENT:
{content}

Return JSON:
{{"concepts": ["concept1", "concept2", "concept3", ...]}}

Extract 3-8 concepts. Use lowercase. Be specific rather than generic.

JSON:"""


DECISION_EXTRACTION_PROMPT = """Analyze this conversation exchange and extract any project decisions that were made or discussed.

USER: {user_msg}
AI: {ai_msg}

If a decision was made or discussed, return JSON:
[{{"project": "project_name", "title": "Short decision title", "rationale": "Why this decision was made", "alternatives": ["alt1", "alt2"], "context": "What prompted the decision", "tags": ["tag1", "tag2"]}}]

If no decision was made, return [].

Extract only concrete decisions with clear rationale, not general discussion.

JSON:"""


PROJECT_CLASSIFIER_PROMPT = """Does this conversation contain information worth saving about a project?

USER: {user_msg}
AI: {ai_msg}

Relevant keywords: project, architecture, schema, decision, roadmap, feature, integration, workflow, design, database, API, deployment, milestone, MyAthlete.

<is_project>
TRUE or FALSE
</is_project>

<project_name>
Name of the project if project-related
</project_name>

<doc_type>
Which document to update: vision, architecture, schemas, decisions, roadmap, operations
(Empty if not project-related)
</doc_type>

<content>
What to write. 1-3 sentences.
</content>"""
