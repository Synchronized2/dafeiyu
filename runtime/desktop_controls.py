"""Consistent controls for the desktop companion."""
from __future__ import annotations

from typing import Any
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

def style_panel(self: QDialog) -> None:
    dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        bg, surface, text, muted = "#171e2b", "#232d3e", "#edf3fc", "#adbbd0"
        border, selection, accent, hover = "#52647f", "#285ab8", "#76a9ff", "#2e3c52"
    else:
        bg, surface, text, muted = "#f5f7fc", "#ffffff", "#253248", "#586b85"
        border, selection, accent, hover = "#b8c6da", "#245bc0", "#245bc0", "#ecf2fd"
    icons = Path(__file__).with_name("ui-icons").as_posix()
    arrow = f"{icons}/chevron-{'dark' if dark else 'light'}.svg"
    check = f"{icons}/check.svg"
    palette = QPalette(self.palette())
    for role, value in ((QPalette.ColorRole.Window, bg), (QPalette.ColorRole.Base, surface),
                        (QPalette.ColorRole.AlternateBase, hover), (QPalette.ColorRole.WindowText, text),
                        (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, surface),
                        (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.Highlight, selection),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, muted)):
        palette.setColor(role, QColor(value))
    self.setPalette(palette)
    self.setStyleSheet(f"""
        QDialog {{ background: {bg}; color: {text}; }}
        QWidget {{ color: {text}; }}
        QLabel {{ background: transparent; }}
        QLabel#browserTitle {{ font-size: 18px; font-weight: 600; }}
        QLabel#browserNote, QLabel#resultCount, QLabel#settingHint {{ color: {muted}; }}
        QLabel#sectionTitle {{ font-size: 15px; font-weight: 600; }}
        QFrame#settingsCard {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
        QScrollArea#settingsScroll, QWidget#settingsContent {{ background: {bg}; border: none; }}
        QLabel#playbackStatus {{ background: {surface}; border: 1px solid {border};
            border-radius: 8px; padding: 8px 10px; }}
        QCheckBox {{ spacing: 10px; padding: 7px 0; }}
        QCheckBox::indicator, QAbstractItemView::indicator {{ width: 18px; height: 18px;
            background: {surface}; border: 2px solid {border}; border-radius: 5px; }}
        QCheckBox::indicator:hover, QAbstractItemView::indicator:hover {{ border-color: {accent}; }}
        QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: {selection};
            border-color: {selection}; image: url("{check}"); }}
        QAbstractItemView::indicator:selected {{ border-color: white; }}
        QCheckBox:focus {{ color: {accent}; }}
        QLineEdit, QComboBox {{ background: {surface}; color: {text}; border: 1px solid {border};
            border-radius: 7px; min-height: 28px; padding: 5px 10px;
            selection-background-color: {selection}; selection-color: white; }}
        QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border-color: {accent}; background: {hover}; }}
        QComboBox {{ padding-right: 32px; combobox-popup: 0; }}
        QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
            width: 30px; border: none; }}
        QComboBox::down-arrow {{ image: url("{arrow}"); width: 14px; height: 14px; }}
        QComboBox QAbstractItemView {{ background: {surface}; color: {text};
            border: 1px solid {border}; outline: none;
            selection-background-color: {selection}; selection-color: white; }}
        QComboBox QAbstractItemView::item {{ min-height: 32px; padding: 3px 9px; }}
        QComboBox QAbstractItemView::item:selected {{ background: {selection}; color: white; }}
        QTabWidget::pane {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; }}
        QTabBar::tab {{ background: {bg}; color: {muted}; padding: 9px 16px;
            border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: white; background: {selection}; border-bottom: 2px solid {selection}; }}
        QListWidget {{ background: {surface}; color: {text}; border: none;
            outline: none; selection-background-color: {selection}; selection-color: white; }}
        QListWidget::item {{ color: {text}; padding: 6px; min-height: 24px; border-radius: 4px; }}
        QListWidget::item:hover {{ background: {hover}; }}
        QListWidget::item:selected, QListWidget::item:selected:!active {{ background: {selection}; color: white; }}
        QPushButton {{ background: {surface}; color: {text}; border: 2px solid {border};
            border-radius: 6px; min-height: 32px; padding: 4px 10px; }}
        QPushButton:hover {{ background: {hover}; border-color: {accent}; }}
        QPushButton:focus {{ border-color: {accent}; }}
        QPushButton:pressed {{ background: {hover}; border-color: {selection}; }}
        QPushButton:checked, QPushButton#playOnceAction, QPushButton#doneAction {{ background: {selection};
            color: white; border-color: {selection}; }}
        QPushButton:checked:hover, QPushButton#playOnceAction:hover, QPushButton#doneAction:hover {{ border-color: {accent}; }}
        QPushButton:disabled {{ color: {muted}; background: {bg}; border-color: {border}; }}
        QScrollBar:vertical {{ background: {bg}; width: 12px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {border}; min-height: 28px; border-radius: 5px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """)


class PetSettings(QDialog):
    def __init__(self, companion: Any) -> None:
        super().__init__(companion)
        self.setObjectName("petSettings")
        self.setWindowTitle("大肥鱼 · 桌宠设置")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(480, 660)
        font = self.font()
        font.setPointSizeF(max(10.5, font.pointSizeF()))
        self.setFont(font)
        style_panel(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("桌宠设置", self)
        title.setObjectName("browserTitle")
        layout.addWidget(title)
        subtitle = QLabel("让大肥鱼以你喜欢的方式陪伴", self)
        subtitle.setObjectName("browserNote")
        layout.addWidget(subtitle)
        scroll = QScrollArea(self)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        content.setObjectName("settingsContent")
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 8, 0)
        sections.setSpacing(14)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        def section(heading: str) -> QVBoxLayout:
            card = QFrame(content)
            card.setObjectName("settingsCard")
            inner = QVBoxLayout(card)
            inner.setContentsMargins(16, 14, 16, 14)
            inner.setSpacing(10)
            label = QLabel(heading, card)
            label.setObjectName("sectionTitle")
            inner.addWidget(label)
            sections.addWidget(card)
            return inner

        display = section("显示")
        form = QFormLayout()
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.choices: dict[str, QComboBox] = {}
        for name, label, values in (
            ("scale", "角色大小", (("迷你", 0.6), ("小", 0.8), ("标准", 1.0), ("大", 1.25))),
            ("bubble_scale", "气泡大小", (("小", 0.8), ("标准", 1.0), ("大", 1.2))),
            ("render_profile", "画面模式", (("明亮清晰 · 推荐", "bright"), ("自然清晰", "natural"), ("原始画面", "original"))),
        ):
            choice = QComboBox(self)
            choice.setObjectName(name)
            for text, value in values:
                choice.addItem(text, value)
            current = getattr(companion, name)
            index = choice.findData(current)
            if index < 0:
                choice.addItem(f"当前（{current}）", current)
                index = choice.count() - 1
            choice.setCurrentIndex(index)
            choice.currentIndexChanged.connect(
                lambda _, name=name, choice=choice: companion._set_preference(name, choice.currentData()))
            form.addRow(label, choice)
            self.choices[name] = choice
        display.addLayout(form)
        hint = QLabel("明亮清晰：轻微提亮中间色调，优化放大后的线条。", self)
        hint.setObjectName("settingHint")
        hint.setWordWrap(True)
        display.addWidget(hint)
        behavior = section("互动与动作")
        activity = QComboBox(self)
        for text, value in (("安静", "quiet"), ("标准", "normal"), ("活泼", "lively")):
            activity.addItem(text, value)
        activity.setCurrentIndex(max(0, activity.findData(companion.activity_level)))
        activity.currentIndexChanged.connect(lambda _: companion._set_preference("activity_level", activity.currentData()))
        activity_form = QFormLayout()
        activity_form.addRow("空闲活跃程度", activity)
        behavior.addLayout(activity_form)
        self.choices["activity_level"] = activity
        self.toggles: dict[str, QCheckBox] = {}
        for name, text in (("inertia_enabled", "惯性甩抛与反弹"),
                           ("gravity_enabled", "甩抛响应重力"),
                           ("edge_snap", "靠近屏幕边缘时吸附"),
                           ("reduced_motion", "减少动态")):
            toggle = QCheckBox(text, self)
            toggle.setObjectName(name)
            toggle.setChecked(getattr(companion, name))
            toggle.toggled.connect(lambda checked, name=name: companion._set_preference(name, checked))
            behavior.addWidget(toggle)
            self.toggles[name] = toggle
        gravity_hint = QLabel("关闭重力后，只沿甩出方向移动、碰壁反弹并逐渐停下。", self)
        gravity_hint.setObjectName("settingHint")
        gravity_hint.setWordWrap(True)
        behavior.addWidget(gravity_hint)
        idle_button = QPushButton('设置空闲随机动作…', self)
        idle_button.clicked.connect(companion._open_action_browser)
        behavior.addWidget(idle_button)
        sections.addStretch(1)
        note = QLabel("更改立即生效 · 自动保存", self)
        note.setObjectName("browserNote")
        note.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(note, 1)
        close = QPushButton("完成", self)
        close.setObjectName("doneAction")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        screen = self.screen()
        if screen:
            self.resize(min(480, screen.availableGeometry().width() - 32),
                        min(660, screen.availableGeometry().height() - 64))
