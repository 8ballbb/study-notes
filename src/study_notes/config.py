import tomllib
from dataclasses import dataclass, field
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
    frames: dict = field(default_factory=dict)
    whisper_model: str | None = None


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
        models=dict(data.get("models", {})),
        prompts=dict(data["prompts"]),
        dry_run=bool(data["run"]["dry_run"]),
        frames=dict(data.get("frames", {})),
        whisper_model=data.get("whisper", {}).get("model"),
    )
