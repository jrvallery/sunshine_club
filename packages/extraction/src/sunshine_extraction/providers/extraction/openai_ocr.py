"""Hosted OpenAI OCR policy boundary."""


class HostedOpenAIOcrExecutor:
    def __init__(self, *_args, **_kwargs) -> None:
        raise ValueError("Hosted OpenAI OCR is not allowed; use local Cortex OCR or Tesseract")


__all__ = ["HostedOpenAIOcrExecutor"]
