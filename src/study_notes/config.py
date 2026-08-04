import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = "REPLACE_ME"


class ConfigError(ValueError):
    """config.toml is present but a value is unset or invalid."""


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
    browser: dict = field(default_factory=dict)
    paywall: dict = field(default_factory=dict)


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = tomllib.loads(path.read_text())
    raw_vault = str(data["vault_path"]).strip()
    if not raw_vault or PLACEHOLDER in raw_vault:
        raise ConfigError(
            f"vault_path is unset in {path} (still the {PLACEHOLDER!r} placeholder). "
            "Edit config.toml and set vault_path to your Obsidian vault: an absolute path, "
            "or one relative to this config file (it must resolve under $HOME)."
        )
    vault_path = Path(raw_vault).expanduser()
    if not vault_path.is_absolute():
        # resolve a relative path against the config file's directory (cwd-independent)
        vault_path = (path.resolve().parent / vault_path).resolve()
    return Config(
        vault_path=vault_path,
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
        browser=dict(data.get("browser", {})),
        paywall=dict(data.get("paywall", {})),
    )
