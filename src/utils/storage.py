from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_settings() -> dict:
    with open(PROJECT_ROOT / "config" / "settings.yaml") as f:
        return yaml.safe_load(f)


def raw_dir(source: str) -> Path:
    """Directory for raw files of one source, e.g. data/raw/smard/."""
    cfg = load_settings()["storage"]
    path = PROJECT_ROOT / cfg["base_path"] / cfg["raw_dir"] / source
    path.mkdir(parents=True, exist_ok=True)
    return path
