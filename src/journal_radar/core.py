"""Public compatibility exports. Implementation belongs to the focused modules.

Kept for historical diagnostic scripts; new code imports its owning layer.
"""

from .adapters.crossref import parse_crossref
from .adapters.rss import parse_rss
from .adapters.source_registry import fetch_source
from .adapters.subscriptions import export_opml, import_legacy_feeds, import_opml
from .adapters.translation import contains_cjk, translate_title, translation_key
from .config import APP_NAME
from .domain.papers import is_recent_publication, paper_date_label, sort_papers
from .domain.sources import create_source, paper_matches_source
from .domain.state import default_state, new_profile
from .domain.validation import normalize_issn, valid_api_endpoint, valid_http_url
from .errors import compact_error
from .platform.paths import data_dir
from .services import now_label
from .storage import current_profile, load_state, save_state

__all__ = [
    "APP_NAME",
    "compact_error",
    "data_dir",
    "default_state",
    "new_profile",
    "valid_http_url",
    "valid_api_endpoint",
    "normalize_issn",
    "create_source",
    "paper_matches_source",
    "sort_papers",
    "paper_date_label",
    "is_recent_publication",
    "load_state",
    "save_state",
    "current_profile",
    "parse_rss",
    "parse_crossref",
    "fetch_source",
    "import_opml",
    "import_legacy_feeds",
    "export_opml",
    "contains_cjk",
    "translation_key",
    "translate_title",
    "now_label",
]
