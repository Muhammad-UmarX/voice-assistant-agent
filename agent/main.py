import logging

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent_setup import build_agent
from logger_setup import set_logger
from llm import init_llm
from nodes import agent_node, tool_node
from prompts.prompt import prompt
from state import AssistantState
from tools.registry import get_tools
from agent_workflow import build_workflow


def build_app():
    """
    Construct the workflow without any side effects (no printing, no
    blocking on input()). This is what tests should import - importing
    main.py directly used to hang, because module-level code ran the
    REPL loop as a side effect of import.
    """
    load_dotenv()
    set_logger()
    logger = logging.getLogger(__name__)

    logger.debug("Initializing application")

    llm = init_llm()
    tool_reg = get_tools()
    tools = tool_reg["tool_objs"]
    agent = build_agent(llm=llm, prompt=prompt, tools=tools)
    call_agent_node = agent_node(agent)

    nodes = {
        "Tool": tool_node,
        "Agent": call_agent_node,
    }

    logger.debug("Loading Checkpointer")
    checkpointer = MemorySaver()

    workflow = build_workflow(nodes=nodes, checkpointer=checkpointer)

    logger.info("Application initialized successfully")
    return workflow, logger


def normalize_approval(raw: str):
    """
    Turn free-text input into a canonical 'YES' / 'NO', or None if it
    doesn't match. Previously raw input (any casing/whitespace/typo)
    was passed straight into Command(resume=...), so 'yes', ' YES ',
    or 'yes please' would silently fail to match whatever the graph
    was checking for.
    """
    val = raw.strip().upper()
    if val in ("Y", "YES"):
        return "YES"
    if val in ("N", "NO"):
        return "NO"
    return None


def action(workflow, config, text: str, approval=None, input_fn=input, logger=None):
    """
    Run one user turn through the workflow.

    Fixes vs. the original:
    - Loops over __interrupt__ instead of handling only one round, so a
      workflow that pauses twice in a single turn (e.g. two separate
      tool calls each needing approval) is handled correctly instead of
      returning a raw interrupt dict as the "final" result.
    - Normalizes/validates approval input instead of passing raw text
      straight into Command(resume=...).
    - Catches and logs invoke failures instead of letting a tool
      exception or API error crash the whole REPL loop.
    """
    logger = logger or logging.getLogger(__name__)
    state: AssistantState = {"messages": [HumanMessage(text)]}

    try:
        result = workflow.invoke(state, config=config)
    except Exception:
        logger.exception("workflow.invoke failed on initial turn")
        raise

    while isinstance(result, dict) and "__interrupt__" in result:
        logger.info("Human approval required")

        current_approval = approval
        approval = None  # only reuse a caller-supplied approval once

        if current_approval is None:
            current_approval = normalize_approval(input_fn("YES / NO?: "))
            while current_approval is None:
                current_approval = normalize_approval(
                    input_fn("Please answer YES or NO: ")
                )
        else:
            current_approval = normalize_approval(current_approval)
            if current_approval is None:
                raise ValueError("approval must be YES or NO")

        try:
            result = workflow.invoke(Command(resume=current_approval), config=config)
        except Exception:
            logger.exception("workflow.invoke failed while resuming from interrupt")
            raise

    return result


if __name__ == "__main__":
    workflow, logger = build_app()

    config = {
        "configurable": {
            "thread_id": 123
        }
    }

    print("Hello!... How can I help you:\n")

    while True:
        user_in = input("")

        if user_in.lower() in ["exit", "quit", "e", "q"]:
            logger.info("Application exited by user")
            break

        print("User:", user_in)
        result = action(workflow, config, user_in, logger=logger)
        print(result["messages"][-1].content)
        print("\n\n", result)