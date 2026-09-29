"""Provider order and cancellation for registered metadata and publisher pages."""

from .abstracts import fetch_abstract
from .publisher_pages import fetch_publisher_abstract, publisher_name


def fetch_complete_abstract(doi, title, url, proxy="", cancelled=None):
    def check():
        if cancelled and cancelled():
            raise ValueError("摘要查询已取消")

    check()
    # Known publisher URLs can avoid title search and its missing-DOI ambiguity.
    providers = [
        lambda: fetch_abstract(doi, title, proxy),
        lambda: fetch_publisher_abstract(url, title, doi, proxy, cancelled),
    ]
    if publisher_name(url):
        providers.reverse()
    failures = []
    for provider in providers:
        check()
        try:
            result = provider()
            check()
            return result
        except Exception as error:
            check()
            failures.append(str(error))
    raise ValueError("；".join(dict.fromkeys(failures)))
