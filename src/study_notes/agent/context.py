from dataclasses import dataclass

from study_notes.config import Config
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex


@dataclass
class EngineContext:
    config: Config
    index: VaultIndex
    writer: VaultWriter
