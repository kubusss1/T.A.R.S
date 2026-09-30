"""tars_telegram — ładne wiadomości Telegrama (HTML) i Mini App dla TARS.

Moduł nie zależy od żadnej biblioteki bota: wiadomości to napisy HTML
(``parse_mode="HTML"``), klawiatury to słowniki w formacie Bot API.

    from tars_telegram import card, progress_bar, main_menu, chunk_message
"""

from .ui import *  # noqa: F401,F403
from .ui import __all__  # noqa: F401
