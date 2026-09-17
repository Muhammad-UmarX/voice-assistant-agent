import pytest
from unittest.mock import patch, MagicMock
import nodes
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

# Integration Test
def test_tool_node():
    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "try_direct_open",
                        "args": {"name": "notepad"},
                        "id": "test_call_1",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    result = nodes.tool_node(state)

    assert "messages" in result
    assert len(result["messages"]) == 1

    tool_message = result["messages"][0]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.name == "try_direct_open"
    assert tool_message.tool_call_id == "test_call_1"


def test_tool_node_multiple_calls():
    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "try_direct_open",
                        "args": {"name": "notepad"},
                        "id": "test_call_1",
                        "type": "tool_call"
                    },
                    {
                        "name": "list_drives",
                        "args": {},
                        "id": "test_call_2",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    result = nodes.tool_node(state)

    assert "messages" in result
    assert len(result["messages"]) == 2

    tool_message_1 = result["messages"][0]
    assert isinstance(tool_message_1, ToolMessage)
    assert tool_message_1.name == "try_direct_open"
    assert tool_message_1.tool_call_id == "test_call_1"

    tool_message_2 = result["messages"][1]
    assert isinstance(tool_message_2, ToolMessage)
    assert tool_message_2.name == "list_drives"
    assert tool_message_2.tool_call_id == "test_call_2"

# Unit tests
# ---------------------------------------------------------------------------
# Tool node - exception handling
# ---------------------------------------------------------------------------

def test_tool_node_raises_and_logs_on_unknown_tool():
    """A tool name that isn't in the registry should raise a KeyError,
    which the except block logs and re-raises."""
    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "does_not_exist",
                        "args": {},
                        "id": "test_call_x",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    with pytest.raises(KeyError):
        nodes.tool_node(state)


def test_tool_node_raises_when_tool_invoke_fails():
    """If the underlying tool raises during invoke, tool_node should
    log the exception and re-raise it rather than swallowing it."""
    failing_tool = MagicMock()
    failing_tool.invoke.side_effect = RuntimeError("boom")

    fake_registry = {
        "tool_map": {"try_direct_open": failing_tool},
        "interrupt_tools": set()
    }

    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "try_direct_open",
                        "args": {"name": "notepad"},
                        "id": "test_call_1",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    with patch("nodes.get_tools", return_value=fake_registry):
        with pytest.raises(RuntimeError):
            nodes.tool_node(state)


# ---------------------------------------------------------------------------
# Tool node - human-in-the-loop interrupt flow
# ---------------------------------------------------------------------------

def test_tool_node_interrupt_approved_executes_tool():
    mock_tool = MagicMock()
    mock_tool.invoke.return_value = {"status": "deleted"}

    fake_registry = {
        "tool_map": {"delete_file": mock_tool},
        "interrupt_tools": {"delete_file"}
    }

    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "delete_file",
                        "args": {"path": "/tmp/foo.txt"},
                        "id": "test_call_1",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    with patch("nodes.get_tools", return_value=fake_registry), \
         patch("nodes.interrupt", return_value="yes") as mock_interrupt:
        result = nodes.tool_node(state)

    mock_interrupt.assert_called_once()
    mock_tool.invoke.assert_called_once_with({"path": "/tmp/foo.txt"})

    assert len(result["messages"]) == 1
    tool_message = result["messages"][0]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.name == "delete_file"
    assert tool_message.tool_call_id == "test_call_1"


def test_tool_node_interrupt_rejected_short_circuits():
    mock_tool = MagicMock()

    fake_registry = {
        "tool_map": {"delete_file": mock_tool},
        "interrupt_tools": {"delete_file"}
    }

    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "delete_file",
                        "args": {"path": "/tmp/foo.txt"},
                        "id": "test_call_1",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    with patch("nodes.get_tools", return_value=fake_registry), \
         patch("nodes.interrupt", return_value="no"):
        result = nodes.tool_node(state)

    mock_tool.invoke.assert_not_called()

    assert len(result["messages"]) == 1
    tool_message = result["messages"][0]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.content == "Action not approved"
    assert tool_message.name == "delete_file"
    assert tool_message.tool_call_id == "test_call_1"


def test_tool_node_interrupt_approval_case_insensitive():
    """Approval check uses .lower(), so 'YES' should also pass."""
    mock_tool = MagicMock()
    mock_tool.invoke.return_value = {"status": "ok"}

    fake_registry = {
        "tool_map": {"delete_file": mock_tool},
        "interrupt_tools": {"delete_file"}
    }

    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "delete_file",
                        "args": {},
                        "id": "test_call_1",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    with patch("nodes.get_tools", return_value=fake_registry), \
         patch("nodes.interrupt", return_value="YES"):
        result = nodes.tool_node(state)

    mock_tool.invoke.assert_called_once()
    assert result["messages"][0].content != "Action not approved"


def test_tool_node_interrupt_only_processes_first_call_on_rejection():
    """If a batch has [interrupt_tool, other_tool] and the interrupt is
    rejected, the function returns immediately and never reaches the
    second tool call."""
    mock_tool = MagicMock()
    other_tool = MagicMock()

    fake_registry = {
        "tool_map": {"delete_file": mock_tool, "list_drives": other_tool},
        "interrupt_tools": {"delete_file"}
    }

    state = {
        "messages": [
            AIMessage(
                content="Hello",
                tool_calls=[
                    {
                        "name": "delete_file",
                        "args": {},
                        "id": "test_call_1",
                        "type": "tool_call"
                    },
                    {
                        "name": "list_drives",
                        "args": {},
                        "id": "test_call_2",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    with patch("nodes.get_tools", return_value=fake_registry), \
         patch("nodes.interrupt", return_value="no"):
        result = nodes.tool_node(state)

    other_tool.invoke.assert_not_called()
    assert len(result["messages"]) == 1


# ---------------------------------------------------------------------------
# should_continue
# ---------------------------------------------------------------------------

def test_should_continue_routes_to_tool_when_tool_calls_present():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_drives",
                        "args": {},
                        "id": "test_call_1",
                        "type": "tool_call"
                    }
                ]
            )
        ]
    }

    assert nodes.should_continue(state) == "Tool"


def test_should_continue_routes_to_end_when_no_tool_calls():
    state = {
        "messages": [
            AIMessage(content="Final answer", tool_calls=[])
        ]
    }

    assert nodes.should_continue(state) == END


# ---------------------------------------------------------------------------
# agent_node
# ---------------------------------------------------------------------------

def test_agent_node_returns_partial_bound_to_agent():
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = AIMessage(content="response")

    node_fn = nodes.agent_node(mock_agent)

    state = {"messages": [HumanMessage(content="hi")]}
    result = node_fn(state)

    mock_agent.invoke.assert_called_once_with({"messages": state["messages"]})
    assert result == {"messages": [mock_agent.invoke.return_value]}