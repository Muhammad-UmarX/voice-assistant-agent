import logging


def set_logger(level=logging.DEBUG, 
               handler_name="logs.log", 
               format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', 
               clear_handlers = True):
    logger = logging.getLogger()

    if clear_handlers:
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    logger.setLevel(level)

    file_handler = logging.FileHandler(handler_name)
    logger.addHandler(file_handler)

    formatter = logging.Formatter(format)

    file_handler.setFormatter(formatter)

    return logger
    