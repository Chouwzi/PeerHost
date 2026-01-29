import logging
from rich.logging import RichHandler
from rich.console import Console
from rich.theme import Theme

# Define clear, bright colors for dark terminals
custom_theme = Theme({
    "info": "bold #FFFFFF on #61AD00",
    "warning": "bold #FFFFFF on #DB6900",
    "error": "bold #FFFFFF on #d70000", 
    "critical": "bold #FFFFFF on red",
    "logging.level.debug": "cyan",
    "logging.level.info": "bold #FFFFFF on #61AD00",
    "logging.level.warning": "bold #FFFFFF on #DB6900", 
    "logging.level.error": "bold #FFFFFF on #d70000",
    "logging.level.critical": "bold #FFFFFF on red",
    "log.time": "#A3A3A3", 
})

# Shared Console for consistent output (Standard Output)
console = Console(theme=custom_theme)

# Keep track of loggers to update levels dynamically
_loggers = []

class CustomRichHandler(RichHandler):
    def render_message(self, record, message):
        """Render the message with specific color based on level."""
        text = super().render_message(record, message)
        
        # Force message text color to match level intent
        if record.levelno >= logging.ERROR:
            text.style = "#FF7878"
        elif record.levelno >= logging.WARNING:
            text.style = "#FFD078"
            
        return text

def setup_logger(name: str = "Client") -> logging.Logger:
    """
    Setup a logger using CustomRichHandler for beautiful output.
    """
    logger = logging.getLogger(name)
    
    # Avoid adding duplicate handlers
    if not logger.handlers:
        # CustomRichHandler automatically handles timestamps, levels, and colors
        handler = CustomRichHandler(
            console=console, 
            rich_tracebacks=True,
            show_time=True,
            omit_repeated_times=False,
            show_path=False, 
            markup=True,
            enable_link_path=False
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO) # Default
    
    # Prevent propagation to root logger to avoid double logging if root has handlers
    logger.propagate = False
    
    if logger not in _loggers:
        _loggers.append(logger)
        
    return logger

def set_debug_mode(enabled: bool):
    """
    Toggle DEBUG level for all registered loggers.
    """
    level = logging.DEBUG if enabled else logging.INFO
    for logger in _loggers:
        logger.setLevel(level)

