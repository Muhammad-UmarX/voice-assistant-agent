"""
Fixtures for integration-testing the agentic workflow.

Design choice: we mock the LLM and the risky tools, but use the REAL
build_workflow / agent_node / tool_node / build_agent code. That way
we're testing the actual orchestration (routing, interrupts, state
passing) rather than re-implementing it in the test.

NOTE: FakeLLM below assumes `build_agent` ultimately calls something
like `llm.bind_tools(tools)` and then `.invoke(messages)` on the
result, which is the standard LangChain pattern. If agent_setup.py
does something more custom (e.g. wraps the LLM further), adjust
FakeLLM's method signatures to match - the important part is that
`.invoke(...)` returns an AIMessage, optionally with `.tool_calls` set.
"""
import pytest


@pytest.fixture
def thread_id_counter():
    # Ensures every test gets its own thread_id, so MemorySaver state
    # from one test can't leak into another (the original code hardcoded
    # thread_id=123 everywhere, which is a shared-state footgun in tests).
    counter = {"n": 0}

    def _next():
        counter["n"] += 1
        return f"test-thread-{counter['n']}"

    return _next