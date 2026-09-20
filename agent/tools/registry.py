import inspect
import logging

from langchain_core.tools import BaseTool
from typing import TypedDict

from tools import apps_files
from tools import folders


logger = logging.getLogger(__name__)

class ToolRegistry(TypedDict):
    tool_objs: list[BaseTool]
    tool_map: dict[str, BaseTool]
    interrupt_tools: set[str]

def get_tools() -> ToolRegistry:
    logger.debug("Discovering tools")
    modules = [apps_files, folders]
    tools = []

    for module in modules:
        for _, obj in inspect.getmembers(module):
            if isinstance(obj, BaseTool):
                logger.debug("Discovered tool: %s", obj.name)
                tools.append(obj)

    tool_map = {
        tool.name: tool
        for tool in tools
    }

    interrupt_tools = {
        tool.name for tool in tools
        if tool.name in {"remove_dir"}
        }

    logger.info("%d tools discovered successfully", len(tools))

    return {
        "tool_objs": tools, 
        "tool_map": tool_map,
        "interrupt_tools": interrupt_tools
        }