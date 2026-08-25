# Felix — AI Co-Pilot

> [!WARNING]
> **Project Status: Experimental / In-Work Research Prototype**
>
> This project is a rough, active **work-in-progress** and is not in any way a finished or near-finished product. 
>
> It is a **dual-purpose research project**:
> 1. **Designing an autonomous, self-healing memory architecture for personal AI agents** (vector storage, multi-tier lifecycles, structured user modeling, automatic consolidation, and graph linking).
> 2. **Stress-testing local, quantized SLMs** (Small Language Models) on complex instruction adherence, structured extraction, and supervised code synthesis against rigid system specifications.

---

## What Felix Can Do

### Chat & Conversation
- Continuous chat with SSE (Server-Sent Events) streaming responses
- Simple query detection (greetings, short questions respond directly without heavy retrieval overhead)
- Context-aware responses using synthesized memory and profile data

### Memory System
- **Vector-based long-term memory** using `pgvector` (cosine similarity search)
- **Three-tier lifecycle**: `inbox` → `active` → `archival` → `stale` → `cleanup` (auto-promoted via periodic maintenance)
- **Core memory** (always in context): personality + user profile + pinned core knowledge chunks
- **Auto-resolution** of `doc_pointer` chunks to physical knowledge markdown files
- **Importance-weighted** retrieval prioritization

### User Modeling
- Structured profile: identity, communication fingerprint, knowledge/expertise, goals, preferences, role expectations
- User facts database (confidence-weighted, searchable by category)
- Onboarding system that gradually populates profile gaps through natural dialogue

### Persona Evolution
- Identity Statement, Voice & Manner, Core Drives, Behavioral Principles
- Evolution events tracked chronologically
- Automatic compression at 10KB thresholds, evolution entry capping at 15 entries
- Version snapshots for rollback and history diffing

### Project Knowledge Management
- Six document types: `vision`, `architecture`, `schemas`, `decisions`, `roadmap`, `operations`
- Vector-based search within project documentation
- Contradiction detection across documents
- Knowledge gap analysis and auto-suggestions

### Concept Linking
- Auto-generated relationships between memory chunks
- Graph traversal for related knowledge retrieval
- Link types: `related`, `depends_on`, `implements`, `contradicts`, `refines`, `supersedes`, `references`

### File Operations
- Browse, read, write knowledge files under the `knowledge/` directory
- Protected paths for core identity and user profiles
- Deduplicated appending and category classification

### Maintenance & Evolution
- Automatic lifecycle stage promotion (`inbox` → `active` → `archived`)
- Personality and profile compression
- Scribe consolidation (groups raw chunks → writes master knowledge documents)
- Empty file cleanup and orphaned chunk pruning
- Version snapshots with diff/restore capability

### Decision Tracking
- Create/update decisions with rationale, alternatives, context, and tags

---

## How Felix Works

### Tech Stack
- **Django 5.0+** — Web backend and REST/SSE endpoints
- **PostgreSQL + pgvector** — Relational storage + vector embedding index
- **Redis** — Message broker and Celery result backend
- **Celery & Celery Beat** — Asynchronous workers for memory extraction and scheduled maintenance loops
- **Local / OpenAI-compatible LLM** — e.g. LM Studio, Ollama, or vLLM providing chat completions and embeddings

### Architecture & Data Flow
```
User message → chat_api view → ContextManager gathers context → LLM generates stream → 
Messages saved → Celery tasks process asynchronously (memory extraction, file ops, project classification)
```

### Background Processing (Celery Tasks)
| Task | Purpose |
|------|---------|
| `process_message_for_memory` | Extracts structured memory chunks from conversation turns |
| `perform_file_operations` | Writes/updates knowledge files based on LLM-detected actions |
| `classify_project_content` | Routes project-related content to appropriate doc types |
| `run_scribe_consolidation` | Groups raw chunks into master knowledge documents |
| `run_memory_maintenance` | Full maintenance cycle: lifecycle promotion, pruning, cleanup |
| `run_knowledge_maintenance` | Analyzes knowledge gaps and detects contradictions |
| `auto_link_new_chunk` | Discovers relationships and creates concept links between chunks |

---

## Quick Start (Docker)

You **do not** need to manually install or configure PostgreSQL, pgvector, or Redis. Everything is containerized and orchestrated with Docker Compose. The only external requirement is having **Docker** and your **local LLM** running.

### 1. Prerequisites
- [Docker Desktop](https://www.docker.com/) (or Docker Engine + Docker Compose)
- A local LLM server (e.g., [LM Studio](https://lmstudio.ai/), Ollama, or vLLM) exposing an OpenAI-compatible API endpoint (default: `http://localhost:1234/v1`).

### 2. Configure Environment
Check or copy `.env`:
```env
# Point to your local LLM host from inside Docker containers
LM_STUDIO_API_BASE="http://host.docker.internal:1234/v1"
LM_STUDIO_API_KEY="lm-studio"
```

### 3. Launch Services
Start all containers (Postgres + pgvector, Redis, Django Web, Celery Worker, Celery Beat):
```bash
docker compose up --build
```

### 4. Apply Database Migrations
In a separate terminal, apply the Django migrations inside the running web container:
```bash
docker compose exec web python manage.py migrate
```

### 5. Access Felix
Open your browser and navigate to:
- **Chat & Web UI**: [http://localhost:8081](http://localhost:8081)
- **Django Admin**: [http://localhost:8081/admin](http://localhost:8081/admin)

---

## Key Configuration

Settings can be customized in `.env` or `Felix/settings.py`:
- `LM_STUDIO_API_BASE`: Base URL for the LLM endpoint (default: `http://host.docker.internal:1234/v1`)
- `LM_STUDIO_API_KEY`: API key for the endpoint (default: `lm-studio`)
- `LLM_MODEL_NAME`: Target generation model name (default: `gemma-4-e2b-it`)
- `EMBEDDING_MODEL_NAME`: Embedding model name (default: `text-embedding-embeddinggemma-300m-qat`)

---
