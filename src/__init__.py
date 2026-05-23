"""AccessBank AI customer-support agent."""
import logging
import os

# Disable chromadb's anonymous telemetry up-front — the bundled posthog client
# is incompatible with our pinned version and floods stderr with harmless warnings.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("POSTHOG_DISABLED", "1")

# Belt-and-suspenders: silence the chromadb telemetry logger directly. The
# library logs "Failed to send telemetry event ..." even when env vars are set.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
