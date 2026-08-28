"""baize.ext.providers — thin adapters for non-OpenAI-compatible vendors (V26).

Part of ``baize.ext`` (imported lazily; never at core import time, so the
zero-dependency red line A and the fail-closed red line C both hold).

W2/F5 scope: the core ``baize.llm`` already covers the three built-in adapters
(openai / anthropic / ollama) with real request shaping, real Anthropic SSE
streaming, and DeepSeek ``reasoning_content`` surfacing. This package is the
intended home for *additional* vendor adapters that do NOT speak the OpenAI
chat-completions dialect (e.g. a vendor that only exposes a gRPC or a bespoke
REST surface). They stay here, behind the lazy-import boundary, so adding them
can never break the core build or inflate the dependency surface.

Nothing in this package is loaded by ``baize/`` at import time.
"""
