from __future__ import annotations
import platform
from os import get_terminal_size, system
from itertools import cycle
from time import sleep
from pprint import pformat
from tabulate import tabulate
from threading import Thread
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
    GENERAL = ""
    HASHTAG = "[#] "
    JSON = "[JSON] "
    DEBUG = "[DEBUG] "
    LOADER = "[LOAD] "

ACTIVE_LOADER: Loader | None = None
ACTIVE_PBARS: list[tqdm] = []

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

        def shrink(k: str) -> str:
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
    def _format_message(msg: str, category: PrintCategory, channel: PrintChannel) -> str:
        prefix = category.value
        
        if category is PrintCategory.HASHTAG:
            if channel in {PrintChannel.WARNING, PrintChannel.ERROR, PrintChannel.API_ERROR, PrintChannel.SKIPPING}:
                prefix = f"[{channel.name}] "
        
        if category is PrintCategory.JSON:
            separator = "-" * min(Printer._term_cols(), 80)
            return f"{separator}\n{prefix}{msg}\n{separator}"
        
        # Simple prefix for each line
        lines = msg.split('\n')
        return '\n'.join(f"{prefix}{line}" if line else "" for line in lines)

    @staticmethod
    def _pause_loader():
        global ACTIVE_LOADER
        if ACTIVE_LOADER and not ACTIVE_LOADER.paused:
            ACTIVE_LOADER.pause()
            return True
        return False

    @staticmethod
    def _resume_loader(was_paused: bool):
        global ACTIVE_LOADER
        if ACTIVE_LOADER and was_paused:
            ACTIVE_LOADER.resume()

    @staticmethod
    def new_print(channel: PrintChannel, msg: str, category: PrintCategory = PrintCategory.NONE, skip_toggle: bool = False, end: str = "\n") -> None:
        if channel != PrintChannel.MANDATORY:
            from zotify.config import Zotify
        if channel == PrintChannel.MANDATORY or Zotify.CONFIG.get(channel.value):
            msg = Printer._format_message(msg, category, channel)
            
            if channel == PrintChannel.DEBUG and Zotify.CONFIG.logger:
                Zotify.CONFIG.logger.debug(msg.strip() + "\n")
            
            loader_was_paused = False if skip_toggle else Printer._pause_loader()
            
            # Use tqdm.write for compatibility with progress bars
            for line in str(msg).splitlines():
                tqdm.write(line, end=end if line == str(msg).splitlines()[-1] else None)
            
            if not skip_toggle:
                Printer._resume_loader(loader_was_paused)

    @staticmethod
    def get_input(prompt: str) -> str:
        user_input = ""
        loader_was_paused = Printer._pause_loader()
        while len(user_input) == 0:
            Printer.new_print(PrintChannel.MANDATORY, prompt, PrintCategory.GENERAL, end=" ", skip_toggle=True)
            user_input = str(input())
        Printer._resume_loader(loader_was_paused)
        return user_input

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
    def depreciated_warning(option_string: str, help_msg: str = None, CONFIG = True) -> None:
        msg = f"WARNING: {'CONFIG' if CONFIG else 'ARGUMENT'} `{option_string}` IS DEPRECIATED, IGNORING\n"
        msg += "THIS WILL BE REMOVED IN FUTURE VERSIONS"
        if help_msg:
            msg += f"\n{help_msg}"
        Printer.new_print(PrintChannel.MANDATORY, msg, PrintCategory.HASHTAG)

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
        """ Displays search selection options """
        Printer.new_print(PrintChannel.MANDATORY, 
            "> SELECT A DOWNLOAD OPTION BY ID\n" +
            "> SELECT A RANGE BY ADDING A DASH BETWEEN BOTH ID's\n" +
            "> OR PARTICULAR OPTIONS BY ADDING A COMMA BETWEEN ID's\n"
        )

    @staticmethod
    def back_up() -> None:
        # Simplified - just print a newline instead of terminal manipulation
        Printer.new_print(PrintChannel.MANDATORY, "", PrintCategory.GENERAL, end="")

    # Progress Bars
    @staticmethod
    def pbar(iterable=None, desc=None, total=None, unit='it', 
            disable=False, unit_scale=False, unit_divisor=1000, pos=1) -> tqdm:
        if iterable and len(iterable) == 1 and len(ACTIVE_PBARS) > 0:
            disable = True # minimize clutter
        new_pbar = tqdm(iterable=iterable, desc=desc, total=total, disable=disable, position=pos, 
                        unit=unit, unit_scale=unit_scale, unit_divisor=unit_divisor, leave=False)
        if new_pbar.disable: new_pbar.pos = -pos
        if not new_pbar.disable: ACTIVE_PBARS.append(new_pbar)
        return new_pbar

    @staticmethod
    def refresh_all_pbars(pbar_stack: list[tqdm] | None, skip_pop: bool = False) -> None:
        for pbar in pbar_stack:
            pbar.refresh()

        if not skip_pop and pbar_stack:
            if pbar_stack[-1].n == pbar_stack[-1].total: 
                pbar_stack.pop()
                if not pbar_stack[-1].disable: ACTIVE_PBARS.pop()

    @staticmethod
    def pbar_position_handler(default_pos: int, pbar_stack: list[tqdm] | None) -> tuple[int, list[tqdm]]:
        pos = default_pos
        if pbar_stack is not None:
            pos = -pbar_stack[-1].pos + (0 if pbar_stack[-1].disable else -2)
        else:
            # next bar must be appended to this empty list
            pbar_stack = []

        return pos, pbar_stack

class Loader:
    """Simple loading indicator with minimal terminal manipulation."""

    def __init__(self, chan, desc="Loading...", end='', timeout=0.1, mode='prog'):
        self.desc = desc
        self.end = end
        self.timeout = timeout
        self.channel = chan
        self.category = PrintCategory.LOADER

        self._thread = Thread(target=self._animate, daemon=True)
        if mode == 'std1':
            self.steps = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
        elif mode == 'std2':
            self.steps = ["◜","◝","◞","◟"]
        elif mode == 'std3':
            self.steps = ["😐 ","😐 ","😮 ","😮 ","😦 ","😦 ","😧 ","😧 ","🤯 ","💥 ","✨ ","\u3000 ","\u3000 ","\u3000 "]
        elif mode == 'prog':
            self.steps = ["[∙∙∙]","[●∙∙]","[∙●∙]","[∙∙●]","[∙∙∙]"]

        self.done = False
        self.paused = False
        self.dead = False
        self._last_msg_len = 0

    def _loader_print(self, msg: str):
        # Clear previous line with spaces, then print new message
        clear_msg = '\r' + ' ' * self._last_msg_len + '\r'
        tqdm.write(clear_msg + msg, end='')
        self._last_msg_len = len(msg)

    def store_active_loader(self):
        global ACTIVE_LOADER
        self._inherited_active_loader = ACTIVE_LOADER
        ACTIVE_LOADER = self

    def release_active_loader(self):
        global ACTIVE_LOADER
        ACTIVE_LOADER = self._inherited_active_loader

    def start(self):
        self.store_active_loader()
        self._thread.start()
        sleep(self.timeout*2)
        return self

    def _animate(self):
        for c in cycle(self.steps):
            if self.done:
                break
            elif not self.paused:
                self._loader_print(f"{c} {self.desc}")
            sleep(self.timeout)
        self.dead = True

    def __enter__(self):
        self.start()

    def stop(self):
        self.done = True
        while not self.dead:
            sleep(self.timeout) 
        # Clear the loader line
        self._loader_print("")
        if self.end != "":
            tqdm.write(self.end)
        self.release_active_loader()

    def pause(self):
        self.paused = True
        self._loader_print("")  # Clear when pausing

    def resume(self):
        self.paused = False
        sleep(self.timeout*2)

    def __exit__(self, exc_type, exc_value, tb):
        self.stop()