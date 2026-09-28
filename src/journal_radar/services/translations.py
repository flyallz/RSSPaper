"""Immutable translation requests keep asynchronous results in the right cache."""

from dataclasses import dataclass

from ..adapters.translation import contains_cjk, translate_title, translation_key
from ..domain.models import ContentType, Language, Settings


@dataclass(frozen=True)
class TranslationJob:
    text: str
    endpoint: str
    model: str
    proxy: str = ""
    content_type: ContentType = "title"
    target_language: Language = "zh"

    @classmethod
    def from_settings(cls, text: str, settings: Settings, content_type: ContentType = "title"):
        return cls(
            text,
            settings["api_endpoint"],
            settings["api_model"],
            settings["proxy"],
            content_type,
            "en" if contains_cjk(text) else "zh",
        )

    @property
    def cache_key(self) -> str:
        # Retain the previous key format so upgrades can reuse saved translations.
        cache_text = "摘要：" + self.text if self.content_type == "abstract" else self.text
        return translation_key(self.endpoint, self.model, cache_text, self.target_language)

    def execute(self, api_key: str) -> str:
        return translate_title(
            self.text,
            self.endpoint,
            self.model,
            api_key,
            self.proxy,
            self.target_language,
            self.content_type,
        )
