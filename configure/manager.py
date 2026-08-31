from typing import Any, Dict

from configure.exceptions import ConfigureError
from configure.runtime import RuntimeConfigManager


class ConfigureManager:
    """
    Koordiniert MEMORIA Runtime-Konfiguration.
    """

    def __init__(self, config_path: str = None):
        if config_path:
            self.runtime = RuntimeConfigManager(config_path=config_path)
        else:
            self.runtime = RuntimeConfigManager()

    def build_runtime_config(
        self,
        setup_mode: str,
        adapter: str,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        context_length: int = 32768,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        history_enabled: bool = True,
        max_history_entries: int = 1000,
        diagnostic_level: str = "standard",
    ) -> Dict[str, Any]:
        try:
            return self.runtime.build_runtime_config(
                setup_mode=setup_mode,
                adapter=adapter,
                base_url=base_url,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                context_length=context_length,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
                history_enabled=history_enabled,
                max_history_entries=max_history_entries,
                diagnostic_level=diagnostic_level,
            )

        except Exception as e:
            raise ConfigureError(str(e)) from e

    def save_runtime_config(
        self,
        config: Dict[str, Any],
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        try:
            return self.runtime.save(
                config=config,
                overwrite=overwrite,
            )

        except Exception as e:
            raise ConfigureError(str(e)) from e

    def load_runtime_config(self) -> Dict[str, Any]:
        try:
            return self.runtime.load()

        except Exception as e:
            raise ConfigureError(str(e)) from e

    def runtime_config_exists(self) -> bool:
        return self.runtime.exists()
