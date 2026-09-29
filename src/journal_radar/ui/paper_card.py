"""One paper's presentation; actions are signals handled by the main window."""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ..domain.models import Paper, Settings
from ..domain.papers import paper_abstract_kind, paper_date_label
from ..services.translations import TranslationJob
from .expandable_text import ExpandableText
from .widgets import make_button


def text_label(text: str, style: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setObjectName(style)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class PaperCard(QFrame):
    title_requested = Signal()
    abstract_requested = Signal()
    enrichment_requested = Signal()

    def __init__(self, paper: Paper, settings: Settings, translations: dict[str, str]):
        super().__init__()
        self.setObjectName("paperCard")
        self.paper_id = paper["id"]
        self.abstract_toggle = None
        self.translation_toggle = None
        self.abstract_parts = None
        self.enrichment_button = None
        column = QVBoxLayout(self)
        column.setContentsMargins(21, 18, 21, 17)
        column.setSpacing(9)
        column.addWidget(text_label(paper["title"], "paperTitle"))
        title_job = TranslationJob.from_settings(paper["title"], settings)
        translation = ExpandableText(
            translations.get(title_job.cache_key, ""), "translation", "译题", self
        )
        translation.setVisible(bool(translation.text()))
        column.addWidget(translation)
        title_actions = QHBoxLayout()
        title_actions.addWidget(translation.toggle)
        title_actions.addWidget(translation.copy_button)
        title_actions.addStretch()
        column.addLayout(title_actions)
        kind = paper_abstract_kind(paper)
        self.abstract_actions = QHBoxLayout()
        self.abstract_actions.setSpacing(18)
        if kind != "missing":
            self._add_abstract(column, paper, settings, translations)
        else:
            column.addWidget(text_label("来源未提供摘要", "notice"))
        if kind != "full":
            self.enrichment_button = make_button("获取完整摘要")
            self.enrichment_button.setObjectName("textAction")
            self.enrichment_button.setToolTip(
                "通过 DOI 或唯一的标题匹配查询 Crossref；不保证每篇都有摘要"
            )
            self.enrichment_button.clicked.connect(self.enrichment_requested.emit)
            self.abstract_actions.insertWidget(0, self.enrichment_button)
        self.abstract_actions.addStretch()
        column.addLayout(self.abstract_actions)
        if paper.get("abstract_error"):
            column.addWidget(text_label("摘要补全：" + paper["abstract_error"], "notice"))
        footer = QHBoxLayout()
        meta = text_label(
            f"{paper.get('source_name', '')}  ·  {paper_date_label(paper)}", "paperMeta"
        )
        footer.addWidget(meta, 1)
        footer.setSpacing(12)
        translate_label = "译为英文" if title_job.target_language == "en" else "译为中文"
        translate = make_button("已翻译" if translation.text() else translate_label)
        translate.setEnabled(not bool(translation.text()))
        translate.clicked.connect(self.title_requested.emit)
        open_button = make_button("打开原文 ↗")
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(paper["url"])))
        footer.addWidget(translate)
        footer.addWidget(open_button)
        column.addLayout(footer)
        self.title_parts = (translation, translate)

    def _add_abstract(self, column, paper, settings, translations):
        text = paper["abstract"].strip()
        kind = paper_abstract_kind(paper)
        abstract = ExpandableText(
            text, "abstract", "出版信息" if kind == "metadata" else "摘要", self
        )
        self.abstract_toggle = abstract.toggle
        column.addWidget(abstract)
        notices = {
            "fragment": "来源仅提供摘要片段",
            "metadata": "来源仅提供出版信息，未提供论文摘要",
            "available": "来源提供的摘要 / 描述，完整性未确认",
            "full": "完整摘要（来源提交）",
        }
        notice = notices[kind]
        if paper.get("abstract_source"):
            notice += " · " + paper["abstract_source"]
        if paper.get("abstract_retrieved_at"):
            notice += " · 获取于 " + paper["abstract_retrieved_at"][:10]
        column.addWidget(text_label(notice, "notice"))
        job = TranslationJob.from_settings(text, settings, "abstract")
        translation = ExpandableText(
            translations.get(job.cache_key, "") if kind != "metadata" else "",
            "translation",
            "摘要译文",
            self,
        )
        self.translation_toggle = translation.toggle
        translation.setVisible(bool(translation.text()))
        column.addWidget(translation)
        actions = self.abstract_actions
        actions.addWidget(abstract.toggle)
        actions.addWidget(abstract.copy_button)
        translated_actions = QHBoxLayout()
        translated_actions.setSpacing(18)
        translated_actions.addWidget(translation.toggle)
        translated_actions.addWidget(translation.copy_button)
        translated_actions.addStretch()
        column.addLayout(translated_actions)
        label = "摘要译为英文" if job.target_language == "en" else "摘要译为中文"
        translate = make_button("摘要已翻译" if translation.text() else label)
        translate.setObjectName("textAction")
        translate.setEnabled(kind != "metadata" and not bool(translation.text()))
        if kind == "metadata":
            translate.setToolTip("当前 RSS 未提供摘要")
            translate.hide()
        translate.clicked.connect(self.abstract_requested.emit)
        actions.addWidget(translate)
        self.abstract_parts = (translation, translate)
