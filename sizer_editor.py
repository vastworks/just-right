"""PyQt6 dialog for adding, editing, and deleting saved window sizes.

Run directly (``python3 sizer_editor.py``) to open the editor on its own; on
save it persists the presets and reloads the KWin script. The tray app imports
``PresetsEditor`` to show the same dialog from its menu.
"""

import sys

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import sizer_engine


class PresetsEditor(QDialog):
    def __init__(self, presets, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Just Right — Edit Presets")
        self.resize(540, 360)

        # Keep the original identifiers so saved keyboard shortcuts stay bound.
        self._row_identifiers = [preset["identifier"] for preset in presets]

        self.table = QTableWidget(len(presets), 4, self)
        self.table.setHorizontalHeaderLabels(["Name", "Width", "Height", "Position"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        for row_index, preset in enumerate(presets):
            self._fill_row(row_index, preset)

        add_button = QPushButton("Add", self)
        remove_button = QPushButton("Remove selected", self)
        save_button = QPushButton("Save", self)
        cancel_button = QPushButton("Cancel", self)

        add_button.clicked.connect(self.add_row)
        remove_button.clicked.connect(self.remove_selected_row)
        save_button.clicked.connect(self.handle_save)
        cancel_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(button_row)

        self.saved_presets = None

    def _fill_row(self, row_index, preset):
        self.table.setItem(row_index, 0, QTableWidgetItem(str(preset.get("name", ""))))
        self.table.setItem(row_index, 1, QTableWidgetItem(str(preset.get("width", ""))))
        self.table.setItem(row_index, 2, QTableWidgetItem(str(preset.get("height", ""))))
        position_box = QComboBox()
        position_box.addItems(sizer_engine.VALID_POSITIONS)
        current_position = preset.get("position", "keep")
        if current_position in sizer_engine.VALID_POSITIONS:
            position_box.setCurrentText(current_position)
        self.table.setCellWidget(row_index, 3, position_box)

    def add_row(self):
        new_row_index = self.table.rowCount()
        self.table.insertRow(new_row_index)
        self._row_identifiers.append(None)
        self._fill_row(new_row_index, {"name": "New size", "width": 1280, "height": 720})

    def remove_selected_row(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return
        self.table.removeRow(selected_row)
        del self._row_identifiers[selected_row]

    def handle_save(self):
        collected_presets = []
        for row_index in range(self.table.rowCount()):
            name = self._cell_text(row_index, 0)
            width_text = self._cell_text(row_index, 1)
            height_text = self._cell_text(row_index, 2)
            position = self.table.cellWidget(row_index, 3).currentText()

            if not name:
                self._report_error(f"Row {row_index + 1}: name cannot be empty.")
                return
            try:
                width = int(width_text)
                height = int(height_text)
            except ValueError:
                self._report_error(f"Row {row_index + 1}: width and height must be whole numbers.")
                return
            if width <= 0 or height <= 0:
                self._report_error(f"Row {row_index + 1}: width and height must be greater than zero.")
                return

            preset = {"name": name, "width": width, "height": height, "position": position}
            existing_identifier = self._row_identifiers[row_index]
            if existing_identifier:
                preset["identifier"] = existing_identifier
            collected_presets.append(preset)

        self.saved_presets = collected_presets
        self.accept()

    def _cell_text(self, row_index, column_index):
        item = self.table.item(row_index, column_index)
        return item.text().strip() if item is not None else ""

    def _report_error(self, message):
        QMessageBox.warning(self, "Invalid preset", message)


def main():
    application = QApplication(sys.argv)
    editor = PresetsEditor(sizer_engine.load_presets())
    if editor.exec() and editor.saved_presets is not None:
        sizer_engine.save_presets(editor.saved_presets)
        sizer_engine.reload_kwin_script()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
