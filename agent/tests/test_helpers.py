from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver

from agent_workflow import build_workflow
from nodes import tool_node, agent_node
from agent_setup import build_agent
from prompts.prompt import prompt

class FakeLLM(Runnable):
    """
    Returns a scripted sequence of AIMessages, one per call to .invoke().
    Lets a test dictate exactly what the "model" does at each step
    without depending on real model behavior.
 
    Must subclass Runnable: agent_setup.py does `prompt | llm.bind_tools(tools)`,
    and LangChain's `|` operator (coerce_to_runnable) only accepts a real
    Runnable, a plain callable, a generator function, or a dict - an object
    that merely has an .invoke() method doesn't qualify and raises TypeError.
    """
 
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
 
    def bind_tools(self, tools):
        # Real chat models return a new runnable from bind_tools();
        # returning self keeps this fake simple since it ignores tool
        # schemas entirely and just replays scripted messages.
        return self
 
    def invoke(self, messages, *args, **kwargs):
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)
 
 
def make_workflow(llm, tools, thread_id):
    """Build a real workflow wired to a fake LLM, isolated checkpointer per test."""
    agent = build_agent(llm=llm, prompt=prompt, tools=tools)
    nodes = {
        "Tool": tool_node,
        "Agent": agent_node(agent),
    }
    checkpointer = MemorySaver()
    workflow = build_workflow(nodes=nodes, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    return workflow, config