from __future__ import annotations
import platform
from os import get_terminal_size, system
from itertools import cycle
from time import sleep
import sys
import threading # Added for Lock
# from pprint import pformat # Uncomment if used elsewhere
# from tabulate import tabulate # Uncomment if used elsewhere
# from traceback import TracebackException # Uncomment if used elsewhere
from enum import Enum
from tqdm import tqdm
# from mutagen import FileType # Uncomment if used elsewhere

# --- Assume your existing constants like MANDATORY, DEBUG, PRINT_SPLASH etc. are here ---
# Example placeholders (replace with your actual const values)
MANDATORY = "MANDATORY"
DEBUG = "DEBUG"
PRINT_SPLASH = "PRINT_SPLASH"
PRINT_WARNINGS = "PRINT_WARNINGS"
PRINT_ERRORS = "PRINT_ERRORS"
PRINT_API_ERRORS = "PRINT_API_ERRORS"
PRINT_PROGRESS_INFO = "PRINT_PROGRESS_INFO"
PRINT_SKIPS = "PRINT_SKIPS"
PRINT_DOWNLOADS = "PRINT_DOWNLOADS"
WINDOWS_SYSTEM = "Windows" # Placeholder
AVAIL_MARKETS = "available_markets"
IMAGES = "images"
EXTERNAL_URLS = "external_urls"
PREVIEW_URL = "preview_url"
# --- End of assumed constants ---

# ANSI Codes (if used elsewhere, keep them)
UP_ONE_LINE = "\033[A"
DOWN_ONE_LINE = "\033[B"
RIGHT_ONE_COL = "\033[C"
LEFT_ONE_COL = "\033[D"
START_OF_PREV_LINE = "\033[F"
CLEAR_LINE = "\033[K"

class PrintChannel(Enum):
    MANDATORY = MANDATORY
    DEBUG = DEBUG
    # Add other channels as needed, referencing your CONST values
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
    LOADER_CYCLE = f"{START_OF_PREV_LINE*2}\t"
    HASHTAG = "\n###   "
    JSON = "\n#"
    DEBUG = "\nDEBUG\n"

# Global variables (assuming they exist in your original file)
LAST_PRINT: PrintCategory = PrintCategory.NONE
ACTIVE_LOADER = None # Will hold the current Loader instance
ACTIVE_PBARS: list[tqdm] = []

# --- Assume Printer class definition is here, with all its methods ---
# (Printer class code - unchanged from your original, except potentially Loader usage)
class Printer:
    # ... (all your existing Printer methods: _term_cols, _api_shrink, _print_prefixes,
    # _toggle_active_loader, new_print, get_input, json_dump, debug, hashtaged,
    # traceback, depreciated_warning, table, clear, splash, search_select, back_up,
    # pbar, refresh_all_pbars, pbar_position_handler) ...
    pass # Placeholder for existing code

# --- Simplified Loader Class (Replaces your original Loader) ---
class Loader:
    """Simple, log-friendly animated loader."""

    # Define animation modes
    MODES = {
        'std1': ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"],
        'std2': ["◜", "◝", "◞", "◟"],
        'std3': ["😐 ", "😐 ", "😮 ", "😮 ", "😦 ", "😦 ", "😧 ", "😧 ", "🤯 ", "💥 ", "✨ ", "\u3000 ", "\u3000 ", "\u3000 "],
        'prog': ["[∙∙∙]", "[●∙∙]", "[∙●∙]", "[∙∙●]", "[∙∙∙]"],
        'basic': ['|', '/', '-', '\\'] # Simple fallback
    }

    def __init__(self, chan: PrintChannel, desc: str = "Loading...", end: str = 'Done!', timeout: float = 0.1, mode: str = 'prog'):
        """
        A simple, log-friendly animated loader.

        Args:
            chan (PrintChannel): The Printer channel for the final message.
            desc (str): The loader's description displayed during loading.
            end (str): Final print message when stopped. Printed on a new line.
            timeout (float): Sleep time between animation frames.
            mode (str): The animation style ('std1', 'std2', 'std3', 'prog', 'basic').
        """
        self.desc = desc
        self.end = end
        self.timeout = timeout
        self.channel = chan

        self._thread = threading.Thread(target=self._animate, daemon=True)
        self.steps = self.MODES.get(mode, self.MODES['prog']) # Default to 'prog'

        self._done = False
        self._lock = threading.Lock()
        self._started = False

        # For integration with ACTIVE_LOADER global if needed
        self._inherited_active_loader = None

    def store_active_loader(self):
        global ACTIVE_LOADER
        self._inherited_active_loader = ACTIVE_LOADER
        ACTIVE_LOADER = self

    def release_active_loader(self):
        global ACTIVE_LOADER
        ACTIVE_LOADER = self._inherited_active_loader

    def start(self):
        """Starts the loading animation in a separate thread."""
        if not self._started:
            self.store_active_loader()
            with self._lock:
                self._done = False # Ensure flag is reset
            self._thread.start()
            self._started = True
            # Small delay to let the first frame print
            sleep(min(self.timeout * 2, 0.1))
        return self

    def _animate(self):
        """The animation loop running in the thread."""
        try:
            for c in cycle(self.steps):
                with self._lock:
                    if self._done:
                        break
                # Directly write to stdout for clean animation
                sys.stdout.write(f'\r{c} {self.desc}')
                sys.stdout.flush()
                sleep(self.timeout)
        except Exception as e:
            # Handle potential errors in animation thread
            # Be cautious about logging here if Printer uses Loader
            pass # Or log minimally
        finally:
            # Ensure cursor moves to next line when stopping
            sys.stdout.write('\n')
            sys.stdout.flush()

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def stop(self):
        """Stops the animation and prints the final message."""
        if self._started:
            with self._lock:
                self._done = True

            # Wait for the animation thread to finish
            if self._thread.is_alive():
                self._thread.join()

            # Print the final message using Printer (goes on new line now)
            if self.end:
                Printer.new_print(self.channel, self.end, category=PrintCategory.GENERAL, skip_toggle=True)

            self.release_active_loader()
            self._started = False

    def __exit__(self, exc_type, exc_value, tb):
        """Context manager exit. Stops the loader."""
        self.stop()
        # Optionally handle exceptions passed here
        # if exc_type is not None:
        #     Printer.traceback(exc_value) # Example
        # Returning None allows exception propagation

# --- Assume the rest of your file (if any) is below ---
# Example usage (can be removed or placed in a separate test script)
# if __name__ == "__main__":
#     # Example 1: Context Manager
#     try:
#         with Loader(PrintChannel.MANDATORY, "Processing data...", "Data processed successfully!", timeout=0.2, mode='basic'):
#             sleep(3) # Simulate work
#             # raise ValueError("Something went wrong!") # Uncomment to test exception handling
#     except ValueError as e:
#         Printer.new_print(PrintChannel.ERROR, f"An error occurred: {e}")

#     print("---Separator---") # This should appear cleanly

#     # Example 2: Manual Start/Stop
#     loader = Loader(PrintChannel.DOWNLOADS, "Downloading file...", "Download complete!", timeout=0.1, mode='prog')
#     loader.start()
#     try:
#         sleep(2) # Simulate download
#     finally:
#         loader.stop() # Ensure stop is called

#     print("---End of Script---")
