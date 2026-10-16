"""Observabilidad: Phoenix / OpenTelemetry opcional.

Si PHOENIX_ENABLED=true registra instrumentación de LangChain via phoenix.otel.
Si no, no hace nada: el módulo es seguro de importar siempre.
"""
from __future__ import annotations

import os


def register() -> None:
    """Registra Phoenix OTEL si PHOENIX_ENABLED=true.

    Llama una vez al arrancar la aplicación (runner_real, api).
    """
    if os.environ.get("PHOENIX_ENABLED", "false").lower() not in ("1", "true", "yes"):
        return

    try:
        import phoenix as px  # noqa: PLC0415
        from phoenix.otel import register as _register  # noqa: PLC0415
        from openinference.instrumentation.langchain import LangChainInstrumentor  # noqa: PLC0415

        px.launch_app()
        _register()
        LangChainInstrumentor().instrument()
    except ImportError:
        # Phoenix no instalado; no bloquear el arranque
        import logging  # noqa: PLC0415
        logging.getLogger(__name__).warning(
            "PHOENIX_ENABLED=true pero arize-phoenix no está instalado. "
            "Observabilidad deshabilitada."
        )
