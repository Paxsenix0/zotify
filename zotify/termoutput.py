from __future__ import annotations
import platform
from os import get_terminal_size, system
from time import sleep
from pprint import pformat
from tabulate import tabulate
from traceback import TracebackException
from enum import Enum
from tqdm import tqdm
from mutagen import FileType

from zotify.const import *

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


class PrintCategory(Enum):
    NONE = ""
    GENERAL = "\n"
    LOADER = "\t"  # Simplified: A loader is just another indented line
    HASHTAG = "\n###   "
    JSON = "\n#"
    DEBUG = "\nDEBUG\n"


class ProgressHandler:
    """
    A unified handler for creating and managing tqdm progress bars and spinners.
    This replaces the old Loader and the static pbar methods.
    """
    def __init__(self):
        self.active_pbars: list[tqdm] = []

    def _get_next_pos(self) -> int:
        """Calculates the screen position for the next progress bar."""
        return len(self.active_pbars)

    def loader(self, desc: str = "Loading...", **kwargs) -> tqdm:
        """Creates an indeterminate progress bar (spinner). Replaces the old Loader."""
        pbar = tqdm(
            desc=desc,
            total=None,  # Indeterminate
            position=self._get_next_pos(),
            bar_format='{l_bar}{bar:10}{r_bar}', # Spinner-like format
            leave=False,
            **kwargs
        )
        self.active_pbars.append(pbar)
        return pbar
    
    def pbar(self, *args, **kwargs) -> tqdm:
        """Creates a standard determinate progress bar."""
        # Set default position and leave behavior if not provided
        kwargs.setdefault('position', self._get_next_pos())
        kwargs.setdefault('leave', False)

        pbar = tqdm(*args, **kwargs)
        self.active_pbars.append(pbar)
        return pbar

    def close(self, pbar: tqdm):
        """Closes a specific progress bar and removes it from the active list."""
        if pbar in self.active_pbars:
            self.active_pbars.remove(pbar)
        pbar.close()
    
    def close_all(self):
        """Closes all active progress bars."""
        for pbar in reversed(self.active_pbars):
            pbar.close()
        self.active_pbars.clear()


# It's good practice to have a single instance of the handler
progress_handler = ProgressHandler()


class Printer:
    @staticmethod
    def _term_cols() -> int:
        try:
            columns, _ = get_terminal_size()
        except OSError:
            columns = 80
        return columns

    @staticmethod
    def _api_shrink(obj: list | tuple | dict) -> dict:
        """ Shrinks API objects to remove data unnecessary data for debugging """
        def shrink(k: str) -> str | None:
            if k in {AVAIL_MARKETS, IMAGES}:
                return "LIST REMOVED FOR BREVITY"
            elif k in {EXTERNAL_URLS, PREVIEW_URL}:
                return "URL REMOVED FOR BREVITY"
            elif k in {"_children"}:
                return "SET REMOVED FOR BREVITY"
            elif k in {"metadata_block_picture", "APIC:0", "covr"}:
                return "BYTES REMOVED FOR BREVITY"
            return None

        if isinstance(obj, list) and len(obj) > 0:
            obj = [Printer._api_shrink(item) for item in obj]
        elif isinstance(obj, tuple):
            if len(obj) == 2 and isinstance(obj[0], str):
                if shrink(obj[0]):
                    obj = (obj[0], shrink(obj[0]))
        elif isinstance(obj, (dict, FileType)):
            for k, v in obj.items():
                if shrink(k):
                    obj[k] = shrink(k)
                else:
                    obj[k] = Printer._api_shrink(v)
        return obj

    @staticmethod
    def _prepare_msg(msg: str, category: PrintCategory, channel: PrintChannel) -> str:
        """Prepares the message string with appropriate prefixes."""
        prefix = category.value
        
        if category is PrintCategory.HASHTAG:
            if channel in {PrintChannel.WARNING, PrintChannel.ERROR, PrintChannel.API_ERROR, PrintChannel.SKIPPING}:
                msg = channel.name + ":  " + msg
            msg = msg.replace("\n", "   ###\n###   ") + "   ###"
            # Remove the initial newline from the prefix for hashtags to align properly
            prefix = prefix.lstrip('\n')

        elif category is PrintCategory.JSON:
            cols = Printer._term_cols()
            msg = "#" * (cols - 1) + "\n" + msg + "\n" + "#" * cols
            prefix = "" # JSON category handles its own newlines

        return prefix + msg

    @staticmethod
    def new_print(channel: PrintChannel, msg: str, category: PrintCategory = PrintCategory.NONE, end: str = "\n") -> None:
        # Lazy import to avoid circular dependency if config uses Printer
        from zotify.config import Zotify

        if channel == PrintChannel.MANDATORY or Zotify.CONFIG.get(channel.value):
            
            # Use tqdm.write for all printing. It's thread-safe and doesn't mess with progress bars.
            full_msg = Printer._prepare_msg(str(msg), category, channel)
            
            # tqdm.write handles printing above any active bars correctly.
            tqdm.write(full_msg, end=end)
            
            if channel == PrintChannel.DEBUG and Zotify.CONFIG.logger:
                Zotify.CONFIG.logger.debug(full_msg.strip() + "\n")

    @staticmethod
    def get_input(prompt: str) -> str:
        """Safely gets user input without messing up active progress bars."""
        # Close any active bars so the input prompt is clean
        progress_handler.close_all()
        
        # We can now use the standard input function
        user_input = input(f"\n{prompt}")
        return user_input.strip()

    # Print Wrappers
    @staticmethod
    def json_dump(obj: dict, channel: PrintChannel = PrintChannel.ERROR, category: PrintCategory = PrintCategory.JSON) -> None:
        obj = Printer._api_shrink(obj)
        Printer.new_print(channel, pformat(obj, indent=2), category)

    @staticmethod
    def debug(*msg: tuple[str | object]) -> None:
        for m in msg:
            if isinstance(m, str):
                Printer.new_print(PrintChannel.DEBUG, m, PrintCategory.DEBUG)
            else:
                Printer.json_dump(m, PrintChannel.DEBUG, PrintCategory.DEBUG)

    @staticmethod
    def hashtaged(channel: PrintChannel, msg: str):
        Printer.new_print(channel, msg, PrintCategory.HASHTAG)

    @staticmethod
    def traceback(e: Exception) -> None:
        msg = "".join(TracebackException.from_exception(e).format())
        Printer.new_print(PrintChannel.ERROR, msg, PrintCategory.GENERAL)

    @staticmethod
    def depreciated_warning(option_string: str, help_msg: str = None, CONFIG=True) -> None:
        kind = "CONFIG" if CONFIG else "ARGUMENT"
        msg = (
            f"WARNING: {kind} `{option_string}` IS DEPRECIATED, IGNORING\n"
            "THIS WILL BE REMOVED IN FUTURE VERSIONS"
        )
        if help_msg:
            msg += f"\n{help_msg}"
        Printer.hashtaged(PrintChannel.MANDATORY, msg)


    @staticmethod
    def table(title: str, headers: tuple[str], tabular_data: list) -> None:
        Printer.hashtaged(PrintChannel.MANDATORY, title)
        Printer.new_print(PrintChannel.MANDATORY, tabulate(tabular_data, headers=headers, tablefmt='pretty'))

    # Prefabs
    @staticmethod
    def clear() -> None:
        """ Clear the console window """
        if platform.system() == WINDOWS_SYSTEM:
            system('cls')
        else:
            system('clear')

    @staticmethod
    def splash() -> None:
        """ Displays splash screen """
        Printer.new_print(PrintChannel.SPLASH,
        "    ███████╗ ██████╗ ████████╗██╗███████╗██╗   ██╗"+"\n"+\
        "    ╚══███╔╝██╔═══██╗╚══██╔══╝██║██╔════╝╚██╗ ██╔╝"+"\n"+\
        "      ███╔╝ ██║   ██║   ██║   ██║█████╗   ╚████╔╝ "+"\n"+\
        "     ███╔╝  ██║   ██║   ██║   ██║██╔══╝    ╚██╔╝  "+"\n"+\
        "    ███████╗╚██████╔╝   ██║   ██║██║        ██║   "+"\n"+\
        "    ╚══════╝ ╚═════╝    ╚═╝   ╚═╝╚═╝        ╚═╝   "+"\n" )

    @staticmethod
    def search_select() -> None:
        """ Displays search selection instructions """
        Printer.new_print(PrintChannel.MANDATORY,
        "> SELECT A DOWNLOAD OPTION BY ID\n" +
        "> SELECT A RANGE BY ADDING A DASH BETWEEN BOTH ID's\n" +
        "> OR PARTICULAR OPTIONS BY ADDING A COMMA BETWEEN ID's\n",
        category=PrintCategory.GENERAL
        )