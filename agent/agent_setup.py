import logging

from state import AssistantState

logger = logging.getLogger(__name__)

def build_agent(llm, prompt, tools):
    logger.debug("Building agent")

    try:
        agent = prompt | llm.bind_tools(tools)

        logger.info("Agent built successfully")

        return agent
    
    except Exception:
        logger.exception("Failed to build agent")

        raise

def call_agent(state: AssistantState, agent) -> AssistantState:
    logger.debug("Invoking agent")
    response = agent.invoke({
        "messages": state['messages']
         })

    logger.debug("Agent invoked successfully")

    return {"messages": [response]}