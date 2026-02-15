# OpenClaw-Obsidian Knowledge Bridge

**Second Brain Interface** is a local RAG middleware that grants OpenClaw (AI Agent) semantic understanding and retrieval capabilities over your Obsidian vault. It enables the agent to cite personal knowledge, past decisions, and technical documentation without manual context switching. Includes a built-in monitoring dashboard (`/dashboard`) for service health, index stats, search playground, and vault browsing.

## Tech Stack
- **Backend:** FastAPI (Python 3.12+)
- **Search Engine:** Qdrant (unified vector + keyword + hybrid search)
- **Embedding Model:** fastembed (`all-MiniLM-L6-v2`, local, 384 dims)
- **File Watcher:** watchdog
- **Infrastructure:** Docker Compose (multi-container)
- **Testing:** pytest

## Critical Rules
- **Language:** All code, logs, and documentation MUST be in **English**
- **Clean Architecture:** Backend follows strict layering (domain → application → infrastructure → api)
- **AI Agent-First:** Every API endpoint must be machine-readable and self-documenting
- **Local First:** No external API calls; all processing happens on the user's machine
- **Read-Only Vault:** The middleware never modifies Obsidian notes

---

# Project Rules

Always read and follow the cursor rules at the start of every task:

- `.cursor/rules/project-core.mdc` — Project role, RAG philosophy, tech stack
- `.cursor/rules/coding-standards.mdc` — Clean Architecture, Clean Code principles
- `.cursor/rules/python-tooling.mdc` — Python, ruff, logging (auto-attached for backend)
- `.cursor/rules/testing.mdc` — pytest standards (auto-attached for tests)
- `.cursor/rules/docker.mdc` — Container best practices (auto-attached for Docker files)
- `.cursor/rules/security.mdc` — Secrets management (agent-requested)
- `.cursor/rules/git-conventions.mdc` — Commit format, branch naming, branch workflow
- `.cursor/rules/ai-agent-friendly.mdc` — AI agent API design, OpenAPI, search endpoints
- `.cursor/rules/rule-creation.mdc` — Meta-rule for creating new rules (agent-requested)

---

# Key Documents

- `second-brain.md` — Product Requirement Document (PRD)
- `docs/design.md` — Technical design document with phased implementation plan
- `README.md` — Setup instructions and API reference (created in Phase 6)
