"""Theme-safe action selection and independent idle-action preferences."""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

try:
    from .action_library import actions_for
    from .desktop_controls import style_panel
except ImportError:
    from action_library import actions_for
    from desktop_controls import style_panel


class ActionBrowser(QDialog):
    def __init__(self, companion: Any, manifest: dict[str, Any]) -> None:
        super().__init__(companion)
        self.companion = companion
        self.manifest = manifest
        self.feedback_until = 0.0
        self.setObjectName("actionBrowser")
        self.setWindowTitle("大肥鱼 · 动作库")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        font = self.font()
        font.setPointSizeF(max(10.5, font.pointSizeF()))
        self.setFont(font)
        self.resize(520, 650)
        style_panel(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title = QLabel("选择大肥鱼的动作", self)
        title.setObjectName("browserTitle")
        layout.addWidget(title)
        self.search = QLineEdit(self)
        self.search.setObjectName("actionSearch")
        self.search.setPlaceholderText("搜索动作，例如：跳舞、吃饭、魔方")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("分类", self))
        self.category = QComboBox(self)
        self.category.setObjectName("actionCategory")
        self.category.addItems(["全部", *dict.fromkeys(a[2] for a in actions_for(manifest))])
        filters.addWidget(self.category, 1)
        self.count_label = QLabel(self)
        self.count_label.setObjectName("resultCount")
        filters.addWidget(self.count_label)
        layout.addLayout(filters)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("actionTabs")
        layout.addWidget(self.tabs, 1)
        manual_tab = QWidget(self)
        manual_layout = QVBoxLayout(manual_tab)
        explanation = QLabel("选中动作后点击播放，也可以双击播放一次。", manual_tab)
        explanation.setWordWrap(True)
        manual_layout.addWidget(explanation)
        self.manual_list = QListWidget(manual_tab)
        self.manual_list.setObjectName("manualActionList")
        manual_layout.addWidget(self.manual_list, 1)
        buttons = QHBoxLayout()
        self.play_once = QPushButton("播放一次", manual_tab)
        self.play_once.setObjectName("playOnceAction")
        self.play_repeat = QPushButton("循环播放", manual_tab)
        self.play_repeat.setObjectName("repeatAction")
        buttons.addWidget(self.play_once)
        buttons.addWidget(self.play_repeat)
        manual_layout.addLayout(buttons)
        self.tabs.addTab(manual_tab, "主动播放")

        idle_tab = QWidget(self)
        idle_layout = QVBoxLayout(idle_tab)
        idle_explanation = QLabel("勾选空闲时允许随机出现的动作。勾选后不会立即播放。", idle_tab)
        idle_explanation.setWordWrap(True)
        idle_layout.addWidget(idle_explanation)
        self.idle_list = QListWidget(idle_tab)
        self.idle_list.setObjectName("idleActionList")
        idle_layout.addWidget(self.idle_list, 1)
        self.tabs.addTab(idle_tab, "空闲随机动作")

        self.status = QLabel(self)
        self.status.setObjectName("playbackStatus")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(48)
        layout.addWidget(self.status)
        note = QLabel("等待确认、完成和异常提醒会优先显示。", self)
        note.setObjectName("browserNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.search.textChanged.connect(self._fill)
        self.category.currentTextChanged.connect(self._fill)
        self.manual_list.currentRowChanged.connect(self._update_buttons)
        self.manual_list.itemDoubleClicked.connect(lambda _: self._play(False))
        self.idle_list.itemChanged.connect(self._select_idle)
        self.play_once.clicked.connect(lambda: self._play(False))
        self.play_repeat.clicked.connect(lambda: self._play(True))
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(200)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start()
        self._fill()
        self._update_status()

    def _fill(self) -> None:
        selected = self.manual_list.currentItem()
        selected_key = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        matches = actions_for(self.manifest, self.search.text(), self.category.currentText())
        self.manual_list.blockSignals(True)
        self.idle_list.blockSignals(True)
        self.manual_list.clear()
        self.idle_list.clear()
        selected_row = 0
        for row, (key, title, group, _) in enumerate(matches):
            text = f"{title}    · {group}"
            manual = QListWidgetItem(text, self.manual_list)
            manual.setData(Qt.ItemDataRole.UserRole, key)
            manual.setFlags(manual.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            idle = QListWidgetItem(text, self.idle_list)
            idle.setData(Qt.ItemDataRole.UserRole, key)
            idle.setFlags(idle.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            idle.setCheckState(Qt.CheckState.Checked if key in self.companion.idle_actions else Qt.CheckState.Unchecked)
            if key == selected_key:
                selected_row = row
        if matches:
            self.manual_list.setCurrentRow(selected_row)
        self.manual_list.blockSignals(False)
        self.idle_list.blockSignals(False)
        self.count_label.setText(f"{len(matches)} 个动作")
        self._update_buttons()

    def _update_buttons(self, *_: Any) -> None:
        enabled = self.manual_list.currentItem() is not None
        self.play_once.setEnabled(enabled)
        self.play_repeat.setEnabled(enabled)

    def _select_idle(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        idle_actions = self.companion.idle_actions
        if item.checkState() == Qt.CheckState.Checked:
            if key not in idle_actions:
                idle_actions.append(key)
        elif key in idle_actions:
            idle_actions.remove(key)
        self.companion.model.idle_micro_clips = tuple(idle_actions)
        self.companion._save_layout()
        self.companion._schedule_micro()

    def _play(self, repeat: bool) -> None:
        item = self.manual_list.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if self.companion._play_manual_action(key, repeat=repeat):
            self.feedback_until = 0
            self._update_status()
        else:
            self.status.setText("暂时不能播放：请先结束拖拽、处理待确认事项，或关闭“减少动态”。")
            self.feedback_until = time.monotonic() + 4

    def _update_status(self) -> None:
        if time.monotonic() < self.feedback_until:
            return
        model = self.companion.model
        action = next((a for a in actions_for(self.manifest) if a[0] == model.manual_clip_name), None)
        if action:
            mode = "循环播放中；选择其他动作即可切换" if model.manual_repeat else "播放一次，结束后自动恢复"
            self.status.setText(f"正在播放：{action[1]}\n{mode}")
        else:
            self.status.setText("自动模式\n跟随 Codex 任务状态，空闲时播放已勾选的随机动作。")
