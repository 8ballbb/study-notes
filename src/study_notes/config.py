import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    vault_path: Path
    notes_root: str
    attachments_dir: str
    frames_subdir: str
    database_url: str
    embedding_model: str
    models: dict[str, str]
    prompts: dict[str, str]
    dry_run: bool


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = tomllib.loads(path.read_text())
    return Config(
        vault_path=Path(data["vault_path"]),
        notes_root=data["notes_root"],
        attachments_dir=data["attachments_dir"],
        frames_subdir=data["frames_subdir"],
        database_url=data["database"]["url"],
        embedding_model=data["embedding"]["model"],
        models=dict(data["models"]),
        prompts=dict(data["prompts"]),
        dry_run=bool(data["run"]["dry_run"]),
    )
