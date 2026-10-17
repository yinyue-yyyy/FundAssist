"""One configuration path for the web app and the real-case runner."""
from __future__ import annotations

import os
from pathlib import Path
import tomllib
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent
MODEL = "gpt-5.4-mini-2026-03-17"
PROMPT_VERSION = "2026-10-17.v2"


@dataclass(frozen=True, repr=False)
class Settings:
    api_key: str = ""
    access_code: str = ""


def load_settings() -> Settings:
    config_path = ROOT / ".streamlit" / "secrets.toml"
    local = {}
    # Capture explicit environment values before Streamlit promotes platform secrets.
    env_api = os.environ.get("OPENAI_API_KEY")
    env_access = os.environ.get("DEMO_ACCESS_CODE")
    if config_path.exists():
        try:
            with config_path.open("rb") as stream:
                local = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError("secrets.toml 无法读取；请检查 TOML 格式，密钥需放在英文引号内。") from exc
    else:
        # Community Cloud may mount secrets outside the repository. Merely reading
        # os.environ is insufficient because Streamlit parses these secrets lazily.
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError
        try:
            local = {key: st.secrets.get(key, "") for key in ("OPENAI_API_KEY", "DEMO_ACCESS_CODE")}
        except StreamlitSecretNotFoundError:
            local = {}
    return Settings(api_key=str(env_api or local.get("OPENAI_API_KEY") or "").strip(),
                    access_code=str(env_access or local.get("DEMO_ACCESS_CODE") or "").strip())
