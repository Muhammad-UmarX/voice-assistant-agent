import logging

from langchain_openrouter import ChatOpenRouter 
# from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

logger = logging.getLogger(__name__)

def init_llm():
    model = "openrouter/free"

    logger.debug("Initializing LLM: %s", model)

    try:
        llm = ChatOpenRouter(
            model=model,
            temperature=0
            )
        
        # endpoint = HuggingFaceEndpoint(
        #     model="Qwen/Qwen3-Coder-Next",
        #     task="text-generation",
        #     huggingfacehub_api_token=os.environ["HUGGINGFACE_API_KEY"],
        #     )
        
        # llm = ChatHuggingFace(llm=endpoint)
        
        logger.info("LLM initialized successfully")

        return llm

    except Exception:
        logger.exception("Failed to initialize LLM: %s", model)
        raise