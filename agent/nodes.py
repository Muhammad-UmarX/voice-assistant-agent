import json
import logging
from functools import partial

from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.types import interrupt

from agent_setup import call_agent
from state import AssistantState
from tools.registry import get_tools


logger = logging.getLogger(__name__)

def tool_node(state: AssistantState) -> AssistantState:
    '''Execute the tool call/s from the last message in the state'''
    outputs = []

    tool_reg = get_tools()
    tool_map = tool_reg["tool_map"]
    tool_map = tool_reg["tool_map"]
    interrupt_tools = tool_reg["interrupt_tools"]

    try:
        logger.debug("Starting tool calling process")

        for tool_call in state["messages"][-1].tool_calls:
            logger.debug("Calling tool: %s", tool_call['name'])

            if tool_call['name'] in interrupt_tools:
                logger.debug("Calling interrupt. Human approval needed for tool: %s", tool_call['name'])
                approval = interrupt(
                    {
                        "action": tool_call["name"],
                        "args": tool_call["args"],
                        "message": "This action will have irreversible consequences"
                    }
                )

                if approval.lower() != "yes":
                    logger.info(
                        "Tool execution rejected by user: %s",
                        tool_call["name"]
                    )
                    return {
                        'messages': [
                            ToolMessage(
                                content="Action not approved",
                                name=tool_call["name"],
                                tool_call_id=tool_call["id"]
                            )
                        ]
                    }
                
                logger.debug(
                    "Human approval received for tool: %s",
                    tool_call["name"]
                )
                
            tool = tool_map[tool_call['name']]
            tool_result = tool.invoke(tool_call["args"])

            logger.info("Tool executed successfully: %s", tool_call['name'])

            outputs.append(
                ToolMessage(content = json.dumps(tool_result),
                name = tool_call["name"],
                tool_call_id = tool_call["id"]
                )
            )
        logger.info("Tool calling process finished successfully")

        return {"messages": outputs}

    except Exception:
        logger.exception("Tool calling process failed")

        raise

def should_continue(state: AssistantState):
    last_msg = state['messages'][-1]

    if last_msg.tool_calls:
        logger.debug("Routing to Tool Node")
        
        return "Tool"

    logger.info("Agent execution finished successfully")

    return END

def agent_node(agent):
    return partial(call_agent, agent=agent)