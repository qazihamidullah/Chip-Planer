# chip_planner_mvp.py
import sys, json, uuid
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QFileDialog, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsSimpleTextItem, QGraphicsItem,
    QToolBar, QInputDialog, QMessageBox, QComboBox, QLabel
)
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor

# --- Custom Graphics Item with lock & metadata ---
class PartitionRect(QGraphicsRectItem):
    def __init__(self, rect: QRectF, uid=None, units="um", locked=False, properties=None):
        super().__init__(rect)
        # Add dimension label
        self.label = QGraphicsSimpleTextItem(self)
        self.label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

        # Ensure label shows correct dims right away
        self.update_label()
        self.uid = uid or str(uuid.uuid4())
        self.units = units
        self.locked = locked
        self.properties = properties or {}
        self.setFlags(
            QGraphicsRectItem.ItemIsSelectable |
            QGraphicsRectItem.ItemIsMovable |
            QGraphicsRectItem.ItemSendsGeometryChanges
        )
        self.update_visual()
    def update_label(self):
        r = self.rect()
        w = round(r.width())
        h = round(r.height())

        # Update text
        self.label.setText(f"{w} x {h}")

        # Position at top-right (slightly offset)
        self.label.setPos(r.right() + 5, r.top() - 5)
    def update_visual(self):
        pen = QPen(Qt.black, 0)
        brush = QBrush(QColor(200, 220, 255, 160))
        if self.locked:
            pen = QPen(Qt.red, 0, Qt.DashLine)
            brush = QBrush(QColor(255, 200, 200, 160))
            self.setFlag(QGraphicsRectItem.ItemIsMovable, False)
        else:
            self.setFlag(QGraphicsRectItem.ItemIsMovable, True)

        self.setPen(pen)
        self.setBrush(brush)

    def set_locked(self, locked: bool):
        self.locked = locked
        self.update_visual()

    def itemChange(self, change, value):
        # Prevent movement if locked
        if change == QGraphicsRectItem.ItemPositionChange and self.locked:
            return self.pos()  # ignore move
        return super().itemChange(change, value)

    def to_dict(self):
        r = self.rect()
        p = self.pos()
        return {
            "id": self.uid,
            "type": "rect",
            "x": p.x() + r.x(),
            "y": p.y() + r.y(),
            "width": r.width(),
            "height": r.height(),
            "units": self.units,
            "locked": self.locked,
            "properties": self.properties
        }

    @staticmethod
    def from_dict(d):
        rect = QRectF(d["x"], d["y"], d["width"], d["height"])
        item = PartitionRect(rect, uid=d.get("id"), units=d.get("units", "um"), locked=d.get("locked", False), properties=d.get("properties", {}))
        item.setPos(0,0)
        return item

# --- Main Window & Canvas ---
class CanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self._pan = False
        self._last_pan = QPointF()
        from PyQt5.QtGui import QPainter
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.scale_factor = 1.0

        # for drawing new rect
        self.drawing = False
        self.draw_start = None
        self.temp_rect_item = None

    def wheelEvent(self, event):
        # Zoom in/out
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        if event.angleDelta().y() > 0:
            factor = zoom_in_factor
        else:
            factor = zoom_out_factor
        self.scale(factor, factor)
        self.scale_factor *= factor

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan = True
            self._last_pan = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        # Left button used for drawing when in draw mode (we toggle with toolbar)
        main_win = self.window()
        if event.button() == Qt.LeftButton and getattr(main_win, 'draw_mode', False):
            self.drawing = True
            self.draw_start = self.mapToScene(event.pos())
            self.temp_rect_item = QGraphicsRectItem(QRectF(self.draw_start, self.draw_start))
            self.temp_rect_item.setPen(QPen(Qt.blue, 0, Qt.DashLine))
            self.temp_rect_item.setBrush(QBrush(QColor(150, 150, 255, 60)))
            self.scene().addItem(self.temp_rect_item)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan:
            delta = event.pos() - self._last_pan
            self._last_pan = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return

        if self.drawing and self.temp_rect_item:
            current = self.mapToScene(event.pos())
            rect = QRectF(self.draw_start, current).normalized()
            self.temp_rect_item.setRect(rect)
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan:
            self._pan = False
            self.setCursor(Qt.ArrowCursor)
            return

        main_win = self.window()
        if event.button() == Qt.LeftButton and getattr(main_win, 'draw_mode', False) and self.drawing:
            self.drawing = False
            if self.temp_rect_item:
                rect = self.temp_rect_item.rect().normalized()
                self.scene().removeItem(self.temp_rect_item)
                self.temp_rect_item = None
                if rect.width() > 1 and rect.height() > 1:
                    # create PartitionRect
                    item = PartitionRect(rect, units=main_win.current_units, locked=False)
                    self.scene().addItem(item)
                    item.update_label()
            return

        super().mouseReleaseEvent(event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Chip Planer — MVP")
        self.resize(1000, 700)

        self.scene = QGraphicsScene()
        self.view = CanvasView(self.scene)
        self.setCentralWidget(self.view)

        # state
        self.draw_mode = False
        self.current_units = "um"

        self._create_toolbar()
        self._create_statusbar()

    def _create_toolbar(self):
        toolbar = QToolBar("Tools")
        self.addToolBar(toolbar)

        act_draw = QAction("Draw Rect", self)
        act_draw.setCheckable(True)
        act_draw.triggered.connect(self.toggle_draw_mode)
        toolbar.addAction(act_draw)

        act_coord = QAction("Add by Coords", self)
        act_coord.triggered.connect(self.add_by_coords)
        toolbar.addAction(act_coord)

        act_lock = QAction("Toggle Lock Selected", self)
        act_lock.triggered.connect(self.toggle_lock_selected)
        toolbar.addAction(act_lock)

        act_delete = QAction("Delete Selected", self)
        act_delete.triggered.connect(self.delete_selected)
        toolbar.addAction(act_delete)

        toolbar.addSeparator()

        save_act = QAction("Save JSON", self)
        save_act.triggered.connect(self.save_json)
        toolbar.addAction(save_act)

        load_act = QAction("Load JSON", self)
        load_act.triggered.connect(self.load_json)
        toolbar.addAction(load_act)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Units:"))
        units_cb = QComboBox()
        units_cb.addItems(["um", "mm", "px"])
        units_cb.currentTextChanged.connect(self.change_units)
        toolbar.addWidget(units_cb)

    def _create_statusbar(self):
        self.status = self.statusBar()
        self.status.showMessage("Ready")

    # Tool actions
    def toggle_draw_mode(self, checked):
        self.draw_mode = checked
        if checked:
            self.status.showMessage("Draw mode ON — drag left mouse to draw rectangles")
            self.view.setDragMode(QGraphicsView.NoDrag)
        else:
            self.status.showMessage("Draw mode OFF")
            self.view.setDragMode(QGraphicsView.RubberBandDrag)

    def add_by_coords(self):
        # Simple dialog for x,y,w,h in current units
        ok = True
        vals = []
        prompts = ["x", "y", "width", "height"]
        for p in prompts:
            v, is_ok = QInputDialog.getDouble(self, "Add by Coordinates", f"{p} ({self.current_units}):", decimals=3)
            if not is_ok:
                ok = False
                break
            vals.append(v)
        if not ok:
            return
        x, y, w, h = vals
        rect = QRectF(x, y, w, h)
        item = PartitionRect(rect, units=self.current_units, locked=False)
        self.scene.addItem(item)
        item.update_label()

    def toggle_lock_selected(self):
        for it in self.scene.selectedItems():
            if isinstance(it, PartitionRect):
                it.set_locked(not it.locked)

    def delete_selected(self):
        for it in self.scene.selectedItems():
            self.scene.removeItem(it)

    def change_units(self, u):
        self.current_units = u
        self.status.showMessage(f"Units set to {u}")

    # Persistence
    def save_json(self):
        fname, _ = QFileDialog.getSaveFileName(self, "Save JSON", filter="JSON Files (*.json)")
        if not fname:
            return
        shapes = []
        for it in self.scene.items():
            if isinstance(it, PartitionRect):
                shapes.append(it.to_dict())
        doc = {"units": self.current_units, "shapes": shapes}
        try:
            with open(fname, "w") as f:
                json.dump(doc, f, indent=2)
            self.status.showMessage(f"Saved {len(shapes)} shapes to {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def load_json(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open JSON", filter="JSON Files (*.json)")
        if not fname:
            return
        try:
            with open(fname, "r") as f:
                doc = json.load(f)
            self.scene.clear()
            for sd in doc.get("shapes", []):
                item = PartitionRect.from_dict(sd)
                # Ensure we place item correctly: PartitionRect.from_dict put rect at absolute coords,
                # so setPos to 0 and rect coordinates are left as given.
                item.setPos(0,0)
                self.scene.addItem(item)
                item.update_label()
            self.current_units = doc.get("units", self.current_units)
            self.status.showMessage(f"Loaded {len(doc.get('shapes', []))} shapes from {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
