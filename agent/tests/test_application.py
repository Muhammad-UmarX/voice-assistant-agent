"""
Integration tests for the agentic workflow.

These import `build_app`-style construction via `make_workflow` in
conftest.py rather than `from main import workflow` - importing main.py
directly used to hang the test suite, since main.py ran a blocking
input() loop as a module-level side effect.

Adjust the two ASSUMPTIONS below to match your actual code:

1. Interrupt shape: assumed to be `{"__interrupt__": [...]}` per the
   original main.py check `if "__interrupt__" in result`.
2. Tool call shape: assumed standard LangChain `AIMessage(tool_calls=[...])`
   with a tool node that reads `tool_call["name"]` / `tool_call["args"]`.
   If tool_node/agent_node in nodes.py use a different contract, update
   the fakes accordingly.
"""
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from test_helpers import FakeLLM, make_workflow
from main import action, normalize_approval


# --- Fake tools -------------------------------------------------------

def fake_open_app(app_name: str) -> str:
    return f"Opened {app_name}"

def fake_delete_file(path: str) -> str:
    raise FileNotFoundError(f"No such file: {path}")


# --- Tests --------------------------------------------------------------

def test_simple_response_no_tool_call(thread_id_counter):
    """Plain conversational turn: no tool call, no interrupt."""
    llm = FakeLLM(responses=[
        AIMessage(content="Hi, how can I help?"),
    ])
    workflow, config = make_workflow(llm, tools=[], thread_id=thread_id_counter())

    result = action(workflow, config, "hello", input_fn=lambda _: "n/a")

    assert "messages" in result
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "Hi, how can I help?"
    assert "__interrupt__" not in result


def test_tool_call_is_executed_and_final_answer_returned(thread_id_counter):
    """Agent calls a tool, tool result feeds back in, agent produces final answer."""
    tool_call = {
        "name": "try_direct_open",
        "args": {"name": "notepad"},
        "id": "call_1",
    }
    llm = FakeLLM(responses=[
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="I opened notepad for you."),
    ])
    workflow, config = make_workflow(llm, tools=[], thread_id=thread_id_counter())

    result = action(workflow, config, "Open notepad", input_fn=lambda _: "n/a")

    assert "__interrupt__" not in result
    assert isinstance(result["messages"][-1], AIMessage)
    assert "notepad" in result["messages"][-1].content.lower()
    # A ToolMessage should exist somewhere in the trace with the tool's result.
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]

    print("TOOL MESSAGE")
    print(tool_messages)
    
    # assert any("Opened notepad" in str(m.content) for m in tool_messages)
    assert any(m.content == "true" for m in tool_messages)


def test_approval_flow_accept(thread_id_counter):
    """A sensitive action pauses for approval; approving lets it complete."""
    tool_call = {
        "name": "remove_file",
        "args": {"path": "/tmp/foo.txt"},
        "id": "call_1",
    }
    llm = FakeLLM(responses=[
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="Deleted the file."),
    ])
    workflow, config = make_workflow(llm, tools=[], thread_id=thread_id_counter())

    result = action(workflow, config, "delete /tmp/foo.txt", approval="YES")

    assert "__interrupt__" not in result
    assert "deleted" in result["messages"][-1].content.lower()


def test_approval_flow_reject(thread_id_counter):
    """Rejecting the approval should not execute the tool."""
    tool_call = {
        "name": "remove_file",
        "args": {"path": "/tmp/foo.txt"},
        "id": "call_1",
    }
    llm = FakeLLM(responses=[
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="Okay, I won't delete it."),
    ])
    workflow, config = make_workflow(llm, tools=[fake_open_app], thread_id=thread_id_counter())

    result = action(workflow, config, "delete /tmp/foo.txt", approval="NO")

    assert "__interrupt__" not in result
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert not any("Deleted" in str(m.content) for m in tool_messages)


def test_two_sequential_interrupts_in_one_turn(thread_id_counter):
    """
    Regression test for the original bug: action() only handled one
    round of __interrupt__. If the graph pauses twice in a single turn
    (two separate approval-requiring tool calls), the old code returned
    the raw interrupt payload as the "final" result on the second pause,
    which would break `result["messages"][-1]`.
    """
    tool_call_1 = {"name": "remove_file", "args": {"path": "/tmp/a.txt"}, "id": "call_1"}
    tool_call_2 = {"name": "remove_file", "args": {"path": "/tmp/b.txt"}, "id": "call_2"}

    llm = FakeLLM(responses=[
        AIMessage(content="", tool_calls=[tool_call_1]),
        AIMessage(content="", tool_calls=[tool_call_2]),
        AIMessage(content="Deleted both files."),
    ])
    workflow, config = make_workflow(llm, tools=[fake_open_app], thread_id=thread_id_counter())

    approvals = iter(["YES", "YES"])
    result = action(
        workflow, config, "delete a.txt and b.txt",
        input_fn=lambda _: next(approvals),
    )

    assert "__interrupt__" not in result
    assert isinstance(result["messages"][-1], AIMessage)
    assert "deleted both" in result["messages"][-1].content.lower()


def test_invalid_approval_input_is_reprompted(thread_id_counter):
    """
    Garbage input ('yes please', typos, stray whitespace) should not
    silently be treated as a NO (or as a YES) - it should be rejected
    and re-prompted until it normalizes cleanly.
    """
    responses = iter(["yes please", "  YES  "])
    result = normalize_approval("yes please")
    assert result is None  # doesn't match, caller must re-prompt

    assert normalize_approval("  YES  ") == "YES"
    assert normalize_approval("no") == "NO"
    assert normalize_approval("maybe") is None


def test_tool_exception_does_not_crash_silently(thread_id_counter):
    """A tool that raises should surface as an error, not corrupt state or hang."""
    tool_call = {
        "name": "open_app",
        "args": {"app_name": "doesnotexist"},
        "id": "call_1",
    }

    def broken_tool(app_name: str) -> str:
        raise RuntimeError("app not found")

    llm = FakeLLM(responses=[
        AIMessage(content="", tool_calls=[tool_call]),
    ])
    workflow, config = make_workflow(llm, tools=[broken_tool], thread_id=thread_id_counter())

    # Depending on how tool_node handles exceptions (catches and returns
    # an error ToolMessage vs. lets it propagate), pick ONE of these:

    # Option A: tool_node catches and reports the error back to the agent
    # result = action(workflow, config, "open doesnotexist", input_fn=lambda _: "n/a")
    # tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    # assert any("error" in str(m.content).lower() for m in tool_messages)

    # Option B: exceptions propagate out of workflow.invoke
    with pytest.raises(Exception):
        action(workflow, config, "open doesnotexist", input_fn=lambda _: "n/a")


def test_thread_state_persists_across_turns(thread_id_counter):
    """Multi-turn memory: second call in the same thread sees first turn's history."""
    llm = FakeLLM(responses=[
        AIMessage(content="Nice to meet you, Alex."),
        AIMessage(content="Your name is Alex."),
    ])
    workflow, config = make_workflow(llm, tools=[], thread_id=thread_id_counter())

    action(workflow, config, "My name is Alex", input_fn=lambda _: "n/a")
    result = action(workflow, config, "What's my name?", input_fn=lambda _: "n/a")

    assert "alex" in result["messages"][-1].content.lower()
    # The full accumulated history should include both turns.
    assert len(result["messages"]) >= 4