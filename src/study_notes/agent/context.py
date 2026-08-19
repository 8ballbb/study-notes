from collections.abc import Callable
from dataclasses import dataclass

from study_notes.config import Config
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex


@dataclass
class EngineContext:
    config: Config
    index: VaultIndex
    writer: VaultWriter
    # Interactive stdin prompt for the ask_user tool + approval hook; None = non-interactive.
    ask_fn: Callable[[str], str] | None = None
