import pytest
from unittest.mock import MagicMock
import agent_setup
from langchain_core.messages import AIMessage, HumanMessage


# ---------------------------------------------------------------------------
# build_agent
# ---------------------------------------------------------------------------

def test_build_agent_success():
    """prompt | llm.bind_tools(tools) should be built and returned."""
    tools = [MagicMock(name="tool_a")]

    bound_llm = MagicMock(name="bound_llm")
    llm = MagicMock(name="llm")
    llm.bind_tools.return_value = bound_llm

    expected_chain = MagicMock(name="chain")
    prompt = MagicMock(name="prompt")
    prompt.__or__.return_value = expected_chain

    result = agent_setup.build_agent(llm, prompt, tools)

    llm.bind_tools.assert_called_once_with(tools)
    prompt.__or__.assert_called_once_with(bound_llm)
    assert result is expected_chain


def test_build_agent_fail_bind(caplog):
    tools = [MagicMock()]
    prompt = MagicMock()

    llm = MagicMock()
    llm.bind_tools.side_effect = RuntimeError("bind failed")

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="bind failed"):
            agent_setup.build_agent(llm, prompt, tools)

    assert "Failed to build agent" in caplog.text


def test_build_agent_pipe_fail(caplog):
    tools = [MagicMock()]

    bound_llm = MagicMock()
    llm = MagicMock()
    llm.bind_tools.return_value = bound_llm

    prompt = MagicMock()
    prompt.__or__.side_effect = ValueError("pipe failed")

    with caplog.at_level("ERROR"):
        with pytest.raises(ValueError, match="pipe failed"):
            agent_setup.build_agent(llm, prompt, tools)

    assert "Failed to build agent" in caplog.text

# ---------------------------------------------------------------------------
# call_agent
# ---------------------------------------------------------------------------

def test_call_agent_success():
    response = AIMessage(content="hello back")
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = response

    state = {"messages": [HumanMessage(content="hi")]}

    result = agent_setup.call_agent(state, mock_agent)

    mock_agent.invoke.assert_called_once_with({"messages": state["messages"]})
    assert result == {"messages": [response]}


def test_call_agent_preserves_full_message_history():
    """call_agent should forward the entire messages list, not just the
    last message, so multi-turn context reaches the LLM."""
    messages = [
        HumanMessage(content="first"),
        AIMessage(content="first reply"),
        HumanMessage(content="second"),
    ]
    state = {"messages": messages}

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = AIMessage(content="second reply")

    agent_setup.call_agent(state, mock_agent)

    mock_agent.invoke.assert_called_once_with({"messages": messages})


def test_call_agent_exception():
    """call_agent has no try/except of its own, so an exception from
    agent.invoke should propagate unchanged."""
    mock_agent = MagicMock()
    mock_agent.invoke.side_effect = RuntimeError("llm unavailable")

    state = {"messages": [HumanMessage(content="hi")]}

    with pytest.raises(RuntimeError, match="llm unavailable"):
        agent_setup.call_agent(state, mock_agent)