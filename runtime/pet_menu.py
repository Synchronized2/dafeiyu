"""A single popup with searchable, directly playable action buttons."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget, QWidgetAction)
try:
    from .action_library import actions_for
    from .desktop_controls import style_panel
except ImportError:
    from action_library import actions_for
    from desktop_controls import style_panel


class PetMenu(QMenu):
    def __init__(self, companion):
        super().__init__(companion)
        self.setObjectName('petContextMenu')
        self.companion = companion
        self.setStyleSheet('QMenu { padding: 0; }')
        body = QWidget(self)
        # Use the same explicit palette as the controls on both system themes.
        style_panel(body)
        body.setAutoFillBackground(True)
        body.setFixedWidth(330)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title = QLabel('选择动作', body)
        title.setObjectName('browserTitle')
        header.addWidget(title, 1)
        self.repeat = QCheckBox('循环', body)
        header.addWidget(self.repeat)
        layout.addLayout(header)
        self.search = QLineEdit(body)
        self.search.setPlaceholderText('搜索动作')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        filters = QHBoxLayout()
        self.category = QComboBox(body)
        self.category.addItem('全部')
        self.category.addItems(list(dict.fromkeys(a[2] for a in actions_for(companion.manifest))))
        self.category.setMaxVisibleItems(10)
        self.category.setStyleSheet('QComboBox { combobox-popup: 0; }')
        filters.addWidget(self.category, 1)
        self.count = QLabel(body)
        self.count.setObjectName('resultCount')
        filters.addWidget(self.count)
        layout.addLayout(filters)
        self.scroll = QScrollArea(body)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(225)
        self.grid_body = QWidget(self.scroll)
        self.grid = QGridLayout(self.grid_body)
        self.grid.setContentsMargins(0, 0, 3, 0)
        self.grid.setSpacing(5)
        self.scroll.setWidget(self.grid_body)
        layout.addWidget(self.scroll)
        self.action_buttons = {}
        self.search.textChanged.connect(self._fill)
        self.category.currentTextChanged.connect(self._fill)
        self._fill()
        self.follow = QCheckBox('跟随 Codex 任务', body)
        self.follow.setChecked(companion.follow_codex)
        self.follow.setToolTip('关闭后只当桌宠使用；开启后自动跟随本机 Codex 任务。')
        self.follow.toggled.connect(lambda enabled: self._run(lambda: companion._set_follow_codex(enabled)))
        layout.addWidget(self.follow)
        row = QHBoxLayout()
        for text, callback in (("桌宠设置…", companion._open_settings), ("回到右下角", companion._go_home)):
            button = QPushButton(text, body)
            button.clicked.connect(lambda checked=False, fn=callback: self._run(fn))
            row.addWidget(button, 1)
        layout.addLayout(row)
        client = QPushButton(companion.open_label, body)
        client.clicked.connect(lambda: self._run(companion._open_client))
        layout.addWidget(client)
        lifecycle = QHBoxLayout()
        restart = QPushButton('重启', body)
        restart.setObjectName('restartPet')
        restart.setEnabled(companion.restart_supported)
        restart.setToolTip('保存设置并重新启动大肥鱼，保留当前陪伴模式。')
        restart.clicked.connect(lambda: self._run(companion._restart_pet))
        lifecycle.addWidget(restart, 1)
        close = QPushButton('本次关闭', body)
        close.clicked.connect(lambda: self._run(companion._close_pet))
        lifecycle.addWidget(close, 1)
        layout.addLayout(lifecycle)
        action = QWidgetAction(self)
        action.setDefaultWidget(body)
        self.addAction(action)
        screen = companion.screen()
        if screen and screen.availableGeometry().height() < 750:
            self.scroll.setFixedHeight(max(80, screen.availableGeometry().height() - 400))

    def _fill(self):
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row, 0)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.action_buttons.clear()
        for i, (key, name, category, _) in enumerate(actions_for(
                self.companion.manifest, self.search.text(), self.category.currentText())):
            button = QPushButton(self.grid_body)
            button.setText(QFontMetrics(button.font()).elidedText(name, Qt.TextElideMode.ElideRight, 125))
            button.setToolTip(name + ' · ' + category)
            button.setMinimumWidth(120)
            button.setCheckable(True)
            button.setChecked(key == self.companion.model.manual_clip_name)
            button.clicked.connect(lambda checked=False, key=key: self._run(
                lambda: self.companion._play_manual_action(key, repeat=self.repeat.isChecked())))
            self.grid.addWidget(button, i // 2, i % 2)
            self.action_buttons[key] = button
        if not self.action_buttons:
            self.grid.addWidget(QLabel('没有匹配的动作', self.grid_body), 0, 0, 1, 2)
        self.count.setText(f'{len(self.action_buttons)} 个动作')
        self.grid.setRowStretch((len(self.action_buttons) + 1) // 2, 1)
        self.scroll.verticalScrollBar().setValue(0)

    def _run(self, callback):
        self.close()
        callback()
