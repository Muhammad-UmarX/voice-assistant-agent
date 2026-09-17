from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from prompts.base_prompt import base_prompt
from prompts.apps_files_prompt import apps_files_prompt
from prompts.folder_prompt import folder_prompt 
from policies import safety_policy

prompt = ChatPromptTemplate.from_messages([
    ("system", 
    f"""
    1. General Instructions:
        {base_prompt}
    \n

    2. Safety Instructions:
        {safety_policy}

    3. Tool Instructions:

    a. Applications/Files Tools:
        {apps_files_prompt} 
        \n 
    b. Folder Tools:
        {folder_prompt}
        \n
    """),
    MessagesPlaceholder(variable_name="messages")
])
