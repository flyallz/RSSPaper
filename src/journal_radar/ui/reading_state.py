"""Keep reading state across data updates, without restoring an obsolete filter."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer

from .paper_card import PaperCard


@dataclass(frozen=True)
class ExpansionState:
    abstract: bool
    abstract_translation: bool
    title_translation: bool


@dataclass
class ReadingSnapshot:
    anchor: tuple[str, int] | None = None
    expanded: dict[str, ExpansionState] = field(default_factory=dict)


class ReadingState(QObject):
    def __init__(self, scroll_area, layout):
        super().__init__(scroll_area)
        self.scroll = scroll_area.verticalScrollBar()
        self.layout = layout
        self.key = None
        self.saved: OrderedDict[tuple, ReadingSnapshot] = OrderedDict()
        self.revision = 0
        self.pending = None

    def cards(self):
        return [
            self.layout.itemAt(i).widget()
            for i in range(self.layout.count())
            if isinstance(self.layout.itemAt(i).widget(), PaperCard)
        ]

    def capture(self) -> ReadingSnapshot:
        self.layout.activate()
        snapshot = ReadingSnapshot()
        for card in self.cards():
            if snapshot.anchor is None and card.y() + card.height() > self.scroll.value():
                snapshot.anchor = (card.paper_id, card.y() - self.scroll.value())
            snapshot.expanded[card.paper_id] = ExpansionState(
                bool(card.abstract_toggle and card.abstract_toggle.isChecked()),
                bool(card.translation_toggle and card.translation_toggle.isChecked()),
                card.title_parts[0].toggle.isChecked(),
            )
        if (
            self.pending
            and self.pending[0] == self.revision
            and self.pending[2] == self.scroll.value()
        ):
            snapshot.anchor = self.pending[1].anchor
        return snapshot

    def rebuild(self, key: tuple, update: Callable[[], None]) -> None:
        if self.key is not None:
            self.saved[self.key] = self.capture()
            self.saved.move_to_end(self.key)
            while len(self.saved) > 40:
                self.saved.popitem(last=False)
        self.key = key
        snapshot = self.saved.get(key, ReadingSnapshot())
        self.apply(snapshot, update, reset=True)

    def preserve(self, update: Callable[[], None]) -> None:
        self.apply(self.capture(), update)

    def apply(self, snapshot: ReadingSnapshot, update: Callable[[], None], reset=False) -> None:
        self.revision += 1
        revision = self.revision
        initial_scroll = self.scroll.value()
        self.pending = (revision, snapshot, initial_scroll)
        update()
        for card in self.cards():
            expanded = snapshot.expanded.get(card.paper_id)
            if expanded:
                if card.abstract_toggle:
                    card.abstract_toggle.setChecked(expanded.abstract)
                if card.translation_toggle:
                    card.translation_toggle.setChecked(expanded.abstract_translation)
                card.title_parts[0].toggle.setChecked(expanded.title_translation)
        if reset:
            self.scroll.setValue(0)
            self.pending = (revision, snapshot, self.scroll.value())

        def restore():
            if revision != self.revision:
                return
            pending = self.pending
            self.pending = None
            if pending and self.scroll.value() != pending[2]:
                return  # The user scrolled again before the layout completed.
            self.layout.activate()
            if snapshot.anchor:
                for card in self.cards():
                    if card.paper_id == snapshot.anchor[0]:
                        self.scroll.setValue(card.y() - snapshot.anchor[1])
                        return
            if reset:
                self.scroll.setValue(0)

        # Wrapping and the scroll holder's resize are separate Qt layout passes.
        QTimer.singleShot(0, self, lambda: QTimer.singleShot(0, self, restore))
