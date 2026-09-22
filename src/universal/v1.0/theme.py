"""Visual system for the generic Journal Radar desktop app."""

STYLE = r"""
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 12px; color: #203343; }
QMainWindow, QDialog { background: #F4F7FA; }
QFrame#sidebar { background: #17374A; border: none; }
QFrame#sidebar QLabel { color: #D7EBF0; }
QLabel#brand { color: #FFFFFF; font-size: 23px; font-weight: 700; }
QLabel#sidebarCaption { color: #9FC3CB; font-size: 11px; }
QLabel#pageTitle { color: #18364A; font-size: 25px; font-weight: 700; }
QLabel#pageSubtitle { color: #6B8291; font-size: 12px; }
QLabel#sectionTitle { color: #18364A; font-size: 17px; font-weight: 700; }
QLabel#statValue { color: #17374A; font-size: 25px; font-weight: 700; }
QLabel#statLabel { color: #718A98; font-size: 11px; }
QFrame#statCard, QFrame#paperCard, QFrame#emptyCard { background: #FFFFFF; border: 1px solid #E1EAF0; border-radius: 14px; }
QFrame#paperCard:hover { border-color: #9BCFCC; }
QLabel#paperTitle { color: #1B3242; font-size: 15px; font-weight: 600; }
QLabel#paperMeta { color: #718692; font-size: 11px; }
QLabel#translation { color: #146A66; font-size: 13px; }
QLabel#notice { color: #5D7786; font-size: 11px; }
QPushButton { background: #FFFFFF; border: 1px solid #D2DFE7; border-radius: 9px; padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #EFF6F7; border-color: #93C9C7; }
QPushButton:pressed { background: #E2F0EF; }
QPushButton:disabled { color: #A0AEB7; background: #F0F3F5; border-color: #E3E8EB; }
QPushButton#primary { background: #13847E; color: #FFFFFF; border: 1px solid #13847E; }
QPushButton#primary:hover { background: #0F706B; border-color: #0F706B; }
QPushButton#danger { color: #B34141; border-color: #EBCACA; }
QPushButton#nav { color: #DCEEF1; background: transparent; border: none; text-align: left; padding: 12px 14px; }
QPushButton#nav:hover { background: #254E60; }
QPushButton#navActive { color: #FFFFFF; background: #2E6574; border: none; text-align: left; padding: 12px 14px; }
QFrame#sidebar QPushButton#sidebarAction { color: #EAF6F6; background: #28556A; border-color: #386A7B; text-align: left; }
QFrame#sidebar QPushButton#sidebarAction:hover { background: #326B7A; }
QFrame#sidebar QComboBox { color: #F6FFFF; background: #28556A; border: 1px solid #427182; }
QLineEdit, QComboBox, QSpinBox, QTableWidget { background: #FFFFFF; border: 1px solid #D4E0E7; border-radius: 8px; padding: 8px; selection-background-color: #C9E5E2; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #13847E; }
QComboBox::drop-down { border: none; width: 24px; }
QTableWidget { gridline-color: #E5EDF1; alternate-background-color: #F7FAFB; }
QHeaderView::section { background: #EEF3F6; color: #526B7A; border: none; padding: 10px 8px; font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #EFF3F6; width: 11px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: #C3D0D7; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 8px; }
"""
