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

# Event Log
EVENT_LOG_MAXLEN = 100  # Max events kept in ring buffer

# Qdrant
QDRANT_COLLECTION_NAME = "obsidian_chunks"
QDRANT_LINK_COLLECTION_NAME = "obsidian_links"
EMBEDDING_DIM = 384  # Dimension of all-MiniLM-L6-v2
