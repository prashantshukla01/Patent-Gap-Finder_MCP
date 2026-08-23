"""AI layer — instruct-then-save architecture.

This server does NOT call any external AI API.
All reasoning (claim extraction, IPC classification, novelty assessment,
claim drafting) is performed by the host LLM (Claude Desktop).

The tools return structured ai_instructions that tell the host LLM
what to do, then expose save_* tools to persist the LLM's output.
"""
