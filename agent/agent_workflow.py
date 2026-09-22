import logging

from langgraph.graph import StateGraph, END

from state import AssistantState
from nodes import should_continue


logger = logging.getLogger(__name__)

def build_workflow(nodes, checkpointer):
    logger.debug("Building workflow")

    try:
        workflow = StateGraph(AssistantState)
        workflow.add_node("Tool", nodes["Tool"])
        workflow.add_node("Agent", nodes["Agent"])

        workflow.add_edge("Tool", "Agent")
        workflow.add_conditional_edges("Agent", should_continue, {
            END: END,
            "Tool": "Tool"
        })

        workflow.set_entry_point("Agent")

        logger.info("Workflow built successfully")

        compiled_workflow = workflow.compile(checkpointer=checkpointer)

        logger.info("Workflow compiled successfully")

        return compiled_workflow

    except Exception:
        logger.exception("Failed to build workflow")

        raise