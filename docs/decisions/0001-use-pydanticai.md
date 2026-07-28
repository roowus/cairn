# ADR 0001 — Use PydanticAI as the agent framework

**Status:** Accepted (Phase 1)

## Context
We need an LLM orchestration layer that: enforces strongly-typed tool
arguments, minimizes token overhead, keeps the agent loop under our control,
and stays provider-agnostic. Candidates evaluated in the research: LangGraph,
PydanticAI, Mastra, custom ReAct loops.

## Decision
Use **PydanticAI**.

## Rationale
- Tool arguments are validated against Pydantic schemas — the model cannot
  call a tool with malformed args; Layer 2 retries on validation failure. This
  directly serves the hard-stop-execution guarantee.
- Low abstraction overhead and a small token footprint.
- Provider-agnostic: the same `Agent` targets Anthropic, OpenAI, or any
  OpenAI-compatible endpoint (Ollama) by swapping the model instance — exactly
  the provider-agnostic requirement.
- We retain full control of the loop; we are not locked into a heavy graph
  framework for Phase 1.

## Consequences
- No built-in graph visualizer / multi-agent orchestration (LangGraph would
  provide those). Multi-agent coordination is deferred; when needed it will be
  additional PydanticAI `Agent`s composed in a new `reasoning/coordinator.py`.
- The exact API (`agent.tool`, model-instance constructors) is still moving;
  it is isolated to `reasoning/agent.py` and `orchestration/tool_adapter.py`
  so a signature change is a localized fix.
