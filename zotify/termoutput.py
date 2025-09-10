from __future__ import annotations
import logging
import platform
import sys
from os import get_terminal_size, system
from pprint import pformat
from tabulate import tabulate
from traceback import TracebackException
from enum import Enum
from tqdm import tqdm
from mutagen import FileType

from zotify.const import *

# --- Logger Setup (Do this once at the start of your application) ---

# Get a logger instance
log = logging.getLogger('zotify')

def setup_logger(level=logging.INFO):
    """Configures the root logger for clean, simple output."""
    log.setLevel(level)
    
    # Avoid adding handlers if they already exist
    if log.hasHandlers():
        log.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    
    # This formatter is simple and perfect for regex
    formatter = logging.Formatter('[%(levelname)s] %(message)s')
    
    handler.setFormatter(formatter)
    log.addHandler(handler)

# --- Enums (Unchanged, as requested) ---

class PrintChannel(Enum):
    MANDATORY = MANDATORY
    DEBUG = DEBUG

    SPLASH = PRINT_SPLASH

    WARNING = PRINT_WARNINGS
    ERROR = PRINT_ERRORS
    API_ERROR = PRINT_API_ERRORS

    PROGRESS_INFO = PRINT_PROGRESS_INFO
    SKIPPING = PRINT_SKIPS
    DOWNLOADS = PRINT_DOWNLOADS


# --- Core Logger Class (Replaces Printer) ---

class Logger:
    # A dictionary to map your channels to standard logging levels
    CHANNEL_LEVEL_MAP = {
        PrintChannel.MANDATORY: logging.INFO,
        PrintChannel.SPLASH: logging.INFO,
        Print_Channel.PROGRESS_INFO: logging.INFO,
        PrintChannel.SKIPPING: logging.INFO,
        PrintChannel.DOWNLOADS: logging.INFO,
        PrintChannel.DEBUG: logging.DEBUG,
        PrintChannel.WARNING: logging.WARNING,
        PrintChannel.ERROR: logging.ERROR,
        PrintChannel.API_ERROR: logging.ERROR,
    }

    @staticmethod
    def _term_cols() -> int:
        try:
            columns, _ = get_terminal_size()
        except OSError:
            columns = 80
        return columns

    @staticmethod
    def _api_shrink(obj: list | tuple | dict) -> dict:
        """ Shrinks API objects to remove data unnecessary data for debugging. (Unchanged) """
        def shrink(k: str) -> str | None:
            if k in {AVAIL_MARKETS, IMAGES}:
                return "LIST REMOVED FOR BREVITY"
            if k in {EXTERNAL_URLS, PREVIEW_URL}:
                return "URL REMOVED FOR BREVITY"
            if k in {"_children"}:
                return "SET REMOVED FOR BREVITY"
            if k in {"metadata_block_picture", "APIC:0", "covr"}:
                return "BYTES REMOVED FOR BREVITY"
            return None

        if isinstance(obj, list):
            obj = [Logger._api_shrink(item) for item in obj]
        elif isinstance(obj, tuple):
            if len(obj) == 2 and isinstance(obj[0], str):
                shrunk_val = shrink(obj[0])
                if shrunk_val:
                    obj = (obj[0], shrunk_val)
        elif isinstance(obj, (dict, FileType)):
            for k, v in obj.items():
                shrunk_val = shrink(k)
                if shrunk_val:
                    obj[k] = shrunk_val
                else:
                    obj[k] = Logger._api_shrink(v)
        return obj

    @staticmethod
    def new_print(channel: PrintChannel, msg: str) -> None:
        """The core logging function. Maps a channel to a log level and logs the message."""
        # This check should be done before calling this function
        # from zotify.config import Zotify
        # if channel != PrintChannel.MANDATORY and not Zotify.CONFIG.get(channel.value):
        #     return
            
        log_level = Logger.CHANNEL_LEVEL_MAP.get(channel, logging.INFO)
        log.log(log_level, msg)

    @staticmethod
    def get_input(prompt: str) -> str:
        """
        Gets user input. Bypasses the logger for the prompt to ensure clean interaction.
        """
        # We write directly to stdout to avoid the '[INFO]' prefix on the prompt
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return input()

    # --- Print Wrappers (Adapted for the new logger) ---

    @staticmethod
    def json_dump(obj: dict, channel: PrintChannel = PrintChannel.ERROR) -> None:
        """Logs a pretty-printed, shrunken dictionary."""
        shrunken_obj = Logger._api_shrink(obj)
        formatted_str = pformat(shrunken_obj, indent=2)
        # Add a border for clarity in logs
        msg = f"JSON DUMP START\n{'-'*40}\n{formatted_str}\n{'-'*40}\nJSON DUMP END"
        Logger.new_print(channel, msg)

    @staticmethod
    def debug(*msg: str | object) -> None:
        """Logs any number of messages or objects at the DEBUG level."""
        for m in msg:
            if isinstance(m, str):
                Logger.new_print(PrintChannel.DEBUG, m)
            else:
                Logger.json_dump(m, PrintChannel.DEBUG)

    @staticmethod
    def hashtaged(channel: PrintChannel, msg: str):
        """Logs a message prefixed with hashtags for emphasis."""
        # Multi-line hashtags for better log readability
        lines = msg.split('\n')
        formatted_msg = "\n" + "\n".join([f"### {line} ###" for line in lines])
        Logger.new_print(channel, formatted_msg)

    @staticmethod
    def traceback(e: Exception) -> None:
        """Logs an exception with its full traceback. The standard library way."""
        log.exception(e)

    @staticmethod
    def depreciated_warning(option_string: str, help_msg: str = None, is_config=True) -> None:
        source = "CONFIG" if is_config else "ARGUMENT"
        title = f"DEPRECATION WARNING: {source} `{option_string}` is deprecated and will be ignored."
        details = "This option will be removed in a future version."
        if help_msg:
            details += f"\n{help_msg}"
        Logger.hashtaged(PrintChannel.WARNING, f"{title}\n{details}")

    @staticmethod
    def table(title: str, headers: tuple[str], tabular_data: list) -> None:
        """Logs a formatted table."""
        Logger.hashtaged(PrintChannel.MANDATORY, title)
        table_str = tabulate(tabular_data, headers=headers, tablefmt='pretty')
        Logger.new_print(PrintChannel.MANDATORY, f"\n{table_str}")

    # --- Prefabs (Adapted) ---

    @staticmethod
    def clear() -> None:
        """Clears the console screen."""
        system('cls' if platform.system() == WINDOWS_SYSTEM else 'clear')

    @staticmethod
    def splash() -> None:
        """Displays splash screen, now through the logger."""
        splash_art = (
            "    ███████╗ ██████╗ ████████╗██╗███████╗██╗   ██╗\n"
            "    ╚══███╔╝██╔═══██╗╚══██╔══╝██║██╔════╝╚██╗ ██╔╝\n"
            "      ███╔╝ ██║   ██║   ██║   ██║█████╗   ╚████╔╝ \n"
            "     ███╔╝  ██║   ██║   ██║   ██║██╔══╝    ╚██╔╝  \n"
            "    ███████╗╚██████╔╝   ██║   ██║██║        ██║   \n"
            "    ╚══════╝ ╚═════╝    ╚═╝   ╚═╝╚═╝        ╚═╝   "
        )
        Logger.new_print(PrintChannel.SPLASH, f"\n{splash_art}\n")

    @staticmethod
    def search_select() -> None:
        """Displays search selection help text."""
        msg = (
            "\n> SELECT A DOWNLOAD OPTION BY ID\n"
            "> SELECT A RANGE BY ADDING A DASH BETWEEN BOTH ID's\n"
            "> OR PARTICULAR OPTIONS BY ADDING A COMMA BETWEEN ID's"
        )
        Logger.new_print(PrintChannel.MANDATORY, msg)

    # --- Progress Bars (Simplified) ---

    @staticmethod
    def pbar(*args, **kwargs) -> tqdm:
        """Creates and returns a tqdm progress bar.
        
        Note: tqdm is an interactive element. In a non-interactive log file, it will
        print its final state, which is usually sufficient.
        """
        # To make logging and tqdm work together, redirect logging through tqdm
        # This should be done once at application start if progress bars are used
        # from tqdm.contrib.logging import logging_redirect_tqdm
        # with logging_redirect_tqdm():
        #     ... your code with progress bars ...
        return tqdm(*args, **kwargs)


class Loader:
    """
    A simple, log-friendly context manager to show the start and end of a task.
    Replaces the complex animated loader.
    
    Usage:
    with Loader(PrintChannel.MANDATORY, "Doing a long task..."):
        # your code here
        time.sleep(2)
    
    Log Output:
    [INFO] Starting: Doing a long task...
    [INFO] Finished: Doing a long task...
    """

    def __init__(self, channel: PrintChannel, desc: str = "Loading...", end_msg: str | None = None):
        self.channel = channel
        self.desc = desc
        self.end_msg = end_msg if end_msg is not None else f"Finished: {self.desc}"

    def __enter__(self):
        Logger.new_print(self.channel, f"Starting: {self.desc}")
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type:
            # If an error occurred, log it differently
            Logger.new_print(PrintChannel.ERROR, f"Failed: {self.desc}")
        else:
            Logger.new_print(self.channel, self.end_msg)