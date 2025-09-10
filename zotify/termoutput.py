from __future__ import annotations
import platform
import sys
from os import get_terminal_size, system
from itertools import cycle
from time import sleep
from pprint import pformat
from tabulate import tabulate
from threading import Thread, Lock
from traceback import TracebackException
from enum import Enum
from tqdm import tqdm
from mutagen import FileType
import io
import contextlib

from zotify.const import *


# ANSI escape sequences
UP_ONE_LINE = "\033[A"
DOWN_ONE_LINE = "\033[B"
RIGHT_ONE_COL = "\033[C"
LEFT_ONE_COL = "\033[D"
START_OF_PREV_LINE = "\033[F"
CLEAR_LINE = "\033[K"
CLEAR_TO_END = "\033[0K"
SAVE_CURSOR = "\033[s"
RESTORE_CURSOR = "\033[u"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


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
    LOADER = "\n\t"
    LOADER_CYCLE = f"\r\t"  # Use carriage return instead of complex cursor movement
    HASHTAG = "\n###   "
    JSON = "\n#"
    DEBUG = "\nDEBUG\n"


class TerminalManager:
    """Manages terminal state and coordinates different output types"""
    
    def __init__(self):
        self.lock = Lock()
        self.loader_active = False
        self.last_loader_lines = 0
        self.last_print_category = PrintCategory.NONE
        self.tqdm_instances = []
        
    def clear_loader_lines(self):
        """Clear lines used by loader"""
        if self.last_loader_lines > 0:
            # Move cursor up and clear lines
            for _ in range(self.last_loader_lines):
                sys.stdout.write(UP_ONE_LINE + CLEAR_LINE)
            sys.stdout.flush()
            self.last_loader_lines = 0
    
    def write_with_coordination(self, text: str, is_loader: bool = False, end: str = "\n"):
        """Thread-safe write that coordinates with loaders and progress bars"""
        with self.lock:
            if self.loader_active and not is_loader:
                # Clear loader before writing other content
                self.clear_loader_lines()
            
            # Write the content
            if is_loader:
                # For loader, we might need to handle multiple lines
                lines = text.split('\n')
                self.last_loader_lines = len([l for l in lines if l.strip()])
                sys.stdout.write(text + end)
            else:
                # For regular content, use tqdm.write for better coordination
                for line in text.split('\n'):
                    if line.strip() or end != '\n':  # Don't skip empty lines unless using newline
                        tqdm.write(line.ljust(self._term_cols()) if end == '\n' else line, end=end if line == text.split('\n')[-1] else '\n')
            
            sys.stdout.flush()
    
    def _term_cols(self) -> int:
        try:
            columns, _ = get_terminal_size()
        except OSError:
            columns = 80
        return columns


# Global terminal manager instance
TERMINAL = TerminalManager()
ACTIVE_LOADER: Loader | None = None


class Printer:
    @staticmethod
    def _term_cols() -> int:
        return TERMINAL._term_cols()

    @staticmethod
    def _api_shrink(obj: list | tuple | dict) -> dict:
        """Shrinks API objects to remove unnecessary data for debugging"""

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
        """Format message with appropriate prefixes"""
        if category is PrintCategory.HASHTAG:
            if channel in {PrintChannel.WARNING, PrintChannel.ERROR, PrintChannel.API_ERROR,
                           PrintChannel.SKIPPING}:
                msg = channel.name + ":  " + msg
            msg = msg.replace("\n", "   ###\n###   ") + "   ###"
            if channel is PrintChannel.DEBUG:
                msg = category.value.replace("\n", "", 1) + msg
                category = PrintCategory.DEBUG
        elif category is PrintCategory.JSON:
            cols = Printer._term_cols()
            msg = "#" * (cols-1) + "\n" + msg + "\n" + "#" * cols

        # Handle continuation from previous print types
        if TERMINAL.last_print_category is PrintCategory.DEBUG and category is PrintCategory.DEBUG:
            pass  # Continue debug block
        elif (TERMINAL.last_print_category in {PrintCategory.LOADER, PrintCategory.LOADER_CYCLE} 
              and category is PrintCategory.LOADER):
            msg = "\r\t" + msg  # Use carriage return for loader updates
        elif (TERMINAL.last_print_category in {PrintCategory.LOADER, PrintCategory.LOADER_CYCLE} 
              and "LOADER" not in category.name):
            # Clear loader and add new content
            msg = "\n" + category.value.lstrip('\n') + msg
        else:
            msg = category.value + msg

        return msg

    @staticmethod
    def new_print(channel: PrintChannel, msg: str, category: PrintCategory = PrintCategory.NONE, 
                  end: str = "\n") -> None:
        """Main print function with proper coordination"""
        
        # Check if we should print based on channel settings
        if channel != PrintChannel.MANDATORY:
            from zotify.config import Zotify
            if not Zotify.CONFIG.get(channel.value):
                return

        # Format the message
        formatted_msg = Printer._format_message(msg, category, channel)
        
        # Handle debug logging to file
        if channel == PrintChannel.DEBUG:
            from zotify.config import Zotify
            if Zotify.CONFIG.logger:
                clean_msg = formatted_msg.strip().replace("DEBUG", "").strip()
                Zotify.CONFIG.logger.debug(clean_msg)
        
        # Coordinate output with terminal manager
        is_loader = "LOADER" in category.name
        TERMINAL.write_with_coordination(formatted_msg, is_loader=is_loader, end=end)
        
        # Update state
        TERMINAL.last_print_category = category

    @staticmethod
    def get_input(prompt: str) -> str:
        """Get user input with proper loader coordination"""
        user_input = ""
        
        # Pause any active loader
        if ACTIVE_LOADER and not ACTIVE_LOADER.paused:
            ACTIVE_LOADER.pause()
        
        with TERMINAL.lock:
            TERMINAL.clear_loader_lines()
            while len(user_input) == 0:
                sys.stdout.write(prompt)
                sys.stdout.flush()
                user_input = input().strip()
        
        # Resume loader if it was active
        if ACTIVE_LOADER and ACTIVE_LOADER.paused:
            ACTIVE_LOADER.resume()
        
        return user_input

    # Print Wrappers
    @staticmethod
    def json_dump(obj: dict, channel: PrintChannel = PrintChannel.ERROR, 
                  category: PrintCategory = PrintCategory.JSON) -> None:
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
        warning_msg = (
            f"\n###   WARNING: {'CONFIG' if CONFIG else 'ARGUMENT'} `{option_string}` IS DEPRECIATED, IGNORING   ###\n"
            f"###   THIS WILL BE REMOVED IN FUTURE VERSIONS   ###"
        )
        if help_msg:
            warning_msg += f"\n###   {help_msg}   ###"
        warning_msg += "\n"
        
        Printer.new_print(PrintChannel.MANDATORY, warning_msg)

    @staticmethod
    def table(title: str, headers: tuple[str], tabular_data: list) -> None:
        Printer.hashtaged(PrintChannel.MANDATORY, title)
        Printer.new_print(PrintChannel.MANDATORY, 
                         tabulate(tabular_data, headers=headers, tablefmt='pretty'))

    # Prefabs
    @staticmethod
    def clear() -> None:
        """Clear the console window"""
        if platform.system() == WINDOWS_SYSTEM:
            system('cls')
        else:
            system('clear')

    @staticmethod
    def splash() -> None:
        """Displays splash screen"""
        splash_art = (
            "    ███████╗ ██████╗ ████████╗██╗███████╗██╗   ██╗\n"
            "    ╚══███╔╝██╔═══██╗╚══██╔══╝██║██╔════╝╚██╗ ██╔╝\n"
            "      ███╔╝ ██║   ██║   ██║   ██║█████╗   ╚████╔╝ \n"
            "     ███╔╝  ██║   ██║   ██║   ██║██╔══╝    ╚██╔╝  \n"
            "    ███████╗╚██████╔╝   ██║   ██║██║        ██║   \n"
            "    ╚══════╝ ╚═════╝    ╚═╝   ╚═╝╚═╝        ╚═╝   "
        )
        Printer.new_print(PrintChannel.SPLASH, splash_art)

    @staticmethod
    def search_select() -> None:
        """Display search selection instructions"""
        instructions = (
            "\n> SELECT A DOWNLOAD OPTION BY ID\n"
            "> SELECT A RANGE BY ADDING A DASH BETWEEN BOTH ID's\n"
            "> OR PARTICULAR OPTIONS BY ADDING A COMMA BETWEEN ID's"
        )
        Printer.new_print(PrintChannel.MANDATORY, instructions)

    # Progress Bars
    @staticmethod
    def pbar(iterable=None, desc=None, total=None, unit='it', 
             disable=False, unit_scale=False, unit_divisor=1000, pos=None) -> tqdm:
        """Create a progress bar with proper coordination"""
        
        # Auto-disable for single items when other progress bars are active
        if iterable and len(iterable) == 1 and len(TERMINAL.tqdm_instances) > 0:
            disable = True
        
        # Calculate position
        if pos is None:
            pos = len(TERMINAL.tqdm_instances)
        
        new_pbar = tqdm(
            iterable=iterable, desc=desc, total=total, disable=disable, 
            position=pos, unit=unit, unit_scale=unit_scale, 
            unit_divisor=unit_divisor, leave=False, 
            file=sys.stdout, dynamic_ncols=True
        )
        
        if not new_pbar.disable:
            TERMINAL.tqdm_instances.append(new_pbar)
        
        return new_pbar

    @staticmethod
    def refresh_all_pbars(pbar_stack: list[tqdm] | None = None) -> None:
        """Refresh all progress bars"""
        if pbar_stack:
            for pbar in pbar_stack:
                if not pbar.disable:
                    pbar.refresh()
            
            # Clean up completed progress bars
            if pbar_stack and pbar_stack[-1].n >= pbar_stack[-1].total:
                completed = pbar_stack.pop()
                if completed in TERMINAL.tqdm_instances:
                    TERMINAL.tqdm_instances.remove(completed)


class Loader:
    """Improved busy symbol loader with better terminal coordination"""

    def __init__(self, chan, desc="Loading...", end='', timeout=0.1, mode='prog'):
        self.desc = desc
        self.end = end
        self.timeout = timeout
        self.channel = chan
        self.category = PrintCategory.LOADER

        self._thread = Thread(target=self._animate, daemon=True)
        
        # Animation modes
        if mode == 'std1':
            self.steps = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
        elif mode == 'std2':
            self.steps = ["◜", "◝", "◞", "◟"]
        elif mode == 'std3':
            self.steps = ["😐 ", "😐 ", "😮 ", "😮 ", "😦 ", "😦 ", "😧 ", "😧 ", "🤯 ", "💥 ", "✨ ", "\u3000 ", "\u3000 ", "\u3000 "]
        elif mode == 'prog':
            self.steps = ["[∙∙∙]", "[●∙∙]", "[∙●∙]", "[∙∙●]", "[∙∙∙]"]

        self.done = False
        self.paused = False
        self.dead = False
        self._previous_loader = None

    def _loader_print(self, msg: str):
        """Print loader message with proper coordination"""
        TERMINAL.loader_active = True
        
        if self.category is PrintCategory.LOADER:
            Printer.new_print(self.channel, msg, self.category, end='')
            self.category = PrintCategory.LOADER_CYCLE
        else:
            # Update existing loader line
            with TERMINAL.lock:
                sys.stdout.write(f'\r\t{msg}{CLEAR_TO_END}')
                sys.stdout.flush()

    def start(self):
        """Start the loader"""
        global ACTIVE_LOADER
        self._previous_loader = ACTIVE_LOADER
        ACTIVE_LOADER = self
        
        self._thread.start()
        sleep(self.timeout * 2)  # Ensure first print happens
        return self

    def _animate(self):
        """Animation loop"""
        for c in cycle(self.steps):
            if self.done:
                break
            elif not self.paused:
                self._loader_print(f"{c} {self.desc}")
            sleep(self.timeout)
        self.dead = True

    def pause(self):
        """Pause the loader animation"""
        self.paused = True

    def resume(self):
        """Resume the loader animation"""
        self.category = PrintCategory.LOADER
        self.paused = False
        sleep(self.timeout * 2)

    def stop(self):
        """Stop the loader"""
        self.done = True
        
        # Wait for animation thread to finish
        while not self.dead:
            sleep(self.timeout)
        
        global ACTIVE_LOADER
        ACTIVE_LOADER = self._previous_loader
        TERMINAL.loader_active = False
        
        # Clear loader lines and print end message if provided
        with TERMINAL.lock:
            TERMINAL.clear_loader_lines()
            if self.end:
                Printer.new_print(self.channel, self.end, PrintCategory.GENERAL)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, tb):
        self.stop()