"""nylab.config -- load and validate the YAML configs in config/ (ARCHITECTURE.md S1, ROADMAP 1.2)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def legacy_windows(name: str = "windows.yaml") -> dict:
    """Build a v0-shaped windows dict {pip, asia, london_kz, pre_ny, ny, ny_am_kz} from
    windows.yaml's `sessions` + `legacy_aliases`, so nylab/days.py can be a near-verbatim,
    low-risk port of ny_session_lab.py's build_days() -- same column semantics, same numbers,
    just YAML-driven instead of a hardcoded CONFIG dict."""
    raw = _load_yaml(name)
    sessions, alias = raw["sessions"], raw["legacy_aliases"]
    out = {"pip": float(raw["pip"])}
    for legacy_name, session_name in alias.items():
        out[legacy_name] = tuple(float(x) for x in sessions[session_name])
    return out


def sessions(name: str = "windows.yaml") -> dict:
    """The full SESSIONS_AND_CONTEXT.md S1 session table as {name: (lo_h, hi_h)}. Used from
    Phase 5 onward; Phase 1 only needs legacy_windows()."""
    raw = _load_yaml(name)
    return {k: tuple(float(x) for x in v) for k, v in raw["sessions"].items()}


@dataclasses.dataclass
class CostsConfig:
    default_cost_pips: float
    spread_col_divisor: float


def load_costs(name: str = "costs.yaml") -> CostsConfig:
    raw = _load_yaml(name)
    return CostsConfig(default_cost_pips=float(raw["default_cost_pips"]),
                        spread_col_divisor=float(raw["spread_col_divisor"]))


@dataclasses.dataclass
class ModelConfig:
    name: str
    version: str
    params: dict
    description: str = ""


def load_model(model_name: str) -> ModelConfig:
    raw = _load_yaml(f"models/{model_name}.yaml")
    return ModelConfig(name=raw["name"], version=str(raw["version"]), params=dict(raw["params"]),
                        description=raw.get("description", ""))


def load_prop(name: str = "prop.yaml") -> dict:
    """Maven account programs (verified, see config/prop.yaml header). Used from Phase 8."""
    return _load_yaml(name)
