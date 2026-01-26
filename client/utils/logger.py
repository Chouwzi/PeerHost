import logging
import sys

# ANSI Color Codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GRAY = "\033[90m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"

class CustomFormatter(logging.Formatter):
    """
    Custom logging formatter with colors but NO icons.
    Format: [Time] [Level] Message
    """

    FORMAT = f"{Colors.GRAY}[%(asctime)s]{Colors.RESET} %(level_prefix)s %(message)s"

    LEVEL_PREFIXES = {
        logging.DEBUG:    f"{Colors.CYAN}[DEBUG]{Colors.RESET}",
        logging.INFO:     f"{Colors.GREEN}[INFO]{Colors.RESET}",
        logging.WARNING:  f"{Colors.YELLOW}[WARN]{Colors.RESET}",
        logging.ERROR:    f"{Colors.RED}[ERROR]{Colors.RESET}",
        logging.CRITICAL: f"{Colors.BOLD_RED}[CRITICAL]{Colors.RESET}",
    }

    def format(self, record):
        # Add colored level prefix
        record.level_prefix = self.LEVEL_PREFIXES.get(record.levelno, f"[{record.levelname}]")
        
        # Format the timestamp
        formatter = logging.Formatter(self.FORMAT, datefmt="%H:%M:%S")
        return formatter.format(record)

def setup_logger(name: str = "Client"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)  # Default level

    # Check if handlers exist to avoid duplicate logs
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(CustomFormatter())
        logger.addHandler(console_handler)

    return logger
