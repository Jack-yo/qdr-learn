"""Public compatibility entry point for the loopback-only QDR console."""

from .app.server import Console, ThreadingHTTPServer, handler, main
from .app.services.data_queries import action_commands, allowed_artifact, feature_evidence, market_research, snapshot

__all__ = [
    "Console",
    "ThreadingHTTPServer",
    "action_commands",
    "allowed_artifact",
    "feature_evidence",
    "handler",
    "main",
    "market_research",
    "snapshot",
]


if __name__ == "__main__":
    main()
