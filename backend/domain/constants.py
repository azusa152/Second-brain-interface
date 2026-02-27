# Chunking
CHUNK_SIZE = 512  # Characters per chunk
CHUNK_OVERLAP = 128  # Overlap between chunks (for context continuity)

# Search
SIMILARITY_THRESHOLD = 0.3  # Min cosine similarity to include in results
TOP_K_DEFAULT = 5  # Default number of results
MAX_TOP_K = 20  # Maximum allowed top_k

# File Watcher
DEBOUNCE_SECONDS = 2.0  # Wait time before triggering index after file change
WATCH_EXTENSIONS = [".md"]  # File types to monitor
POLLING_INTERVAL_SECONDS = 3.0  # PollingObserver check interval (seconds)
POLLING_INTERVAL_MIN_SECONDS = 0.5  # Minimum allowed polling interval to avoid busy-loop

# Scheduler / Incremental Rebuild
REBUILD_CRON_HOUR = 3  # Daily rebuild at 03:00 UTC
REBUILD_CRON_MINUTE = 0
HASH_REGISTRY_FILENAME = "hash_registry.json"

# Intent Classification
INTENT_THRESHOLD = 0.5              # Min composite score to trigger personal context retrieval
INTENT_RULE_WEIGHT = 0.4            # Weight for keyword signal
INTENT_SEMANTIC_WEIGHT = 0.4        # Weight for embedding similarity signal
INTENT_TEMPORAL_WEIGHT = 0.2        # Weight for temporal heuristic signal
# Min cosine similarity for semantic signal to contribute (all-MiniLM-L6-v2 scores are lower
# than intuition suggests; most semantically-similar pairs fall in the 0.3-0.7 range)
INTENT_SEMANTIC_SIMILARITY_MIN = 0.3

# Default personal-domain keywords. All matching uses word boundaries (\b) to avoid false
# positives. Overly broad single words ("my", "review", "past", "history") are excluded.
INTENT_DEFAULT_KEYWORDS: list[str] = [
    "investment", "portfolio", "career", "job interview",
    "journal", "diary", "meeting notes", "retrospective",
    "my notes", "my decision", "my plan",
    "past decision",
    "obsidian", "vault", "knowledge base",
    # "last year" excluded: covered by temporal signal to avoid double-scoring
    # "personal" excluded: too broad (matches "personal computer", "personal trainer", etc.)
]

# Default domain anchor sentences for the semantic signal. These are embedded once at
# startup and compared against each incoming query embedding via cosine similarity.
INTENT_DEFAULT_DOMAIN_ANCHORS: list[str] = [
    "personal finance and investment portfolio decisions",
    "career planning job history and professional development",
    "meeting notes team discussions and project retrospectives",
    "personal journal diary daily notes",
    "technical decisions architecture choices made in the past",
    "goals and personal objectives review",
]

# Suggest Links
SUGGEST_LINKS_MAX_SUGGESTIONS_DEFAULT = 5  # Default max wikilink suggestions
SUGGEST_LINKS_QUERY_MAX_CHARS = 400        # Max chars extracted from content for embedding query

# Context Augmentation
# Default top-k for augment is lower than search to stay within the LLM context budget
AUGMENT_TOP_K_DEFAULT = 3
# Max characters of note content placed inside <context>...</context>.
# At ~4 chars/token this is roughly 1 500 tokens — conservative enough for most LLMs.
AUGMENT_CONTEXT_MAX_CHARS = 6000

# Event Log
EVENT_LOG_MAXLEN = 100  # Max events kept in ring buffer

# Qdrant
QDRANT_COLLECTION_NAME = "obsidian_chunks"
QDRANT_LINK_COLLECTION_NAME = "obsidian_links"
EMBEDDING_DIM = 384  # Dimension of all-MiniLM-L6-v2
