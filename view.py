from __future__ import annotations
from bisect import bisect
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from typing import Callable

from PySide6.QtCore import (
	QItemSelectionModel,
	QModelIndex,
	QObject,
	QPoint,
	QSize,
	Qt,
	Slot,
)
from PySide6.QtGui import (
	QAction,
	QIcon,
	QKeySequence,
	QMouseEvent,
	QPainter,
	QPen,
	QPixmap,
	QStandardItem,
	QStandardItemModel,
)
from PySide6.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QDial,
	QDialog,
	QFileDialog,
	QGridLayout,
	QLabel,
	QMainWindow,
	QMenu,
	QMessageBox,
	QPushButton,
	QSizePolicy,
	QStatusBar,
	QTreeView,
	QVBoxLayout,
	QWidget,
)

import app_rc
from data import KnobId, ModIdx, ModInfo, categories, ranges
from data_gen import dropdowns, models
from model import EvListener, Event
import model
from pxio import Setlist, parse_any_px, write_pxb, write_pxe, write_pxs
from structs import KnobState, ModState, PresetState, lane_map, no_mod

no_amp = ModInfo(no_mod.id, '[amp disabled]', 0, {}, [], [])
amps = [no_amp] + [ mod for mod in models.values() if mod.id >> 16 == 0x0007 ]
amp_index = { mod.id: i for i, mod in enumerate(amps) }
no_cab = ModInfo(no_mod.id, '[no cab]', 0, {}, [], [])
cabs = [no_cab] + [ mod for mod in models.values() if mod.id >> 16 == 0x0107 ]
cab_index = { mod.id: i for i, mod in enumerate(cabs) }
mics = [ mod for mod in models.values() if mod.id >> 16 == 0x0000 ]

@contextmanager
def no_signals(obj: QObject):
	obj.blockSignals(True)
	try:
		yield obj
	finally:
		obj.blockSignals(False)

class KnobView(QVBoxLayout):
	def __init__(self, mw: MainWindow, mod_idx: ModIdx, knob: KnobState):
		super().__init__()

		self.mw = mw
		self.mod_idx = mod_idx
		self.knob = knob

	def refresh_val(self): ...

	def send_ev(self, T: type[model.KnobEvent]):
		self.mw.send_ev(T(self.mod_idx, self.knob.info.id))

class DialKnobView(KnobView):
	def __init__(self, mw: MainWindow, mod_idx: ModIdx, knob: KnobState):
		super().__init__(mw, mod_idx, knob)

		self.dial = QDial()
		self.dial.setMaximum(100)
		self.refresh_val()
		self.dial.actionTriggered.connect(self.val_changed)

		self.addWidget(self.dial, stretch=1)
		self.label = QLabel(knob.info.name, alignment=Qt.AlignmentFlag.AlignCenter)
		self.addWidget(self.label)

		self.range = ranges[self.knob.info.range_id]

	def refresh_val(self):
		with no_signals(self.dial):
			self.dial.setValue(int(self.knob.val*100))

	@Slot(int)
	def val_changed(self, val: int):
		self.knob.val = self.dial.value()/100
		self.send_ev(model.KnobValue)
		self.mw.sb.showMessage(f'{self.knob.info.name}: {self.range.fmt(self.knob.val)}', 2000)

class DropdownKnobView(KnobView):
	def __init__(self, mw: MainWindow, mod_idx: ModIdx, knob: KnobState):
		super().__init__(mw, mod_idx, knob)

		self.cbox = QComboBox()
		self.cbox.setMaximumWidth(120)
		self.dd = dropdowns[knob.info.dropdown_id]
		self.cbox.addItems(self.dd.opts)
		self.refresh_val()
		self.cbox.currentIndexChanged.connect(self.idx_changed)

		self.addWidget(self.cbox, stretch=1, alignment=Qt.AlignmentFlag.AlignCenter)
		self.label = QLabel(knob.info.name, alignment=Qt.AlignmentFlag.AlignCenter)
		self.addWidget(self.label)

	def refresh_val(self):
		val = self.knob.val
		if isinstance(val, float):
			val = round(val * (len(self.dd.opts)-1))
		with no_signals(self.cbox):
			self.cbox.setCurrentIndex(val - self.dd.offset)

	@Slot(int)
	def idx_changed(self, idx: int):
		val = idx + self.dd.offset
		if isinstance(self.knob.val, float):
			val /= len(self.dd.opts)-1
		if self.knob.val == val:
			return
		self.knob.val = val
		self.send_ev(model.KnobValue)

@cache
def _load_img(img_idx: int):
	if img_idx == 0:
		return QPixmap()
	pm = QPixmap(f':/img/{img_idx:03}.png')
	pm.setDevicePixelRatio(max(pm.width()/120, pm.height()/120))
	return pm

def load_img(mod: ModState):
	return _load_img(mod.info.img_idx)

class FxMenu(QPushButton):
	def __init__(self):
		super().__init__()

		menu = QMenu(self)
		self.setMenu(menu)
		cat_menus: dict[int, QMenu] = {}
		for catid, cat in categories.items():
			if catid == 13:
				menu.addAction(cat).setData(0x7fffffff)
			else:
				cat_menus[catid] = menu.addMenu(cat)
		for mod in models.values():
			if mod.id >> 24 == 0x02:
				act = cat_menus[(mod.id >> 16) & 0xff].addAction(mod.name)
				act.setData(mod.id)

	# TODO quick switching with mouse wheel
	# def wheelEvent(self, event: QWheelEvent, /) -> None:

class ModView(QObject):
	def __init__(self, mw: MainWindow, side: int, mod_idx: ModIdx, col: int):
		super().__init__()
		self.mw = mw
		self.side = side
		self.mod_idx = mod_idx
		self.col = col
		self.mod = mw.model.preset.modules[mod_idx]
		self.knobs: dict[KnobId, KnobView] = {}

		self.en = QCheckBox("Enabled")
		self.refresh_en()
		self.en.stateChanged.connect(self.en_changed)

	def refresh_knobs(self):
		maxrows = 6
		for knob in self.knobs.values():
			for i in range(knob.count()):
				w = knob.itemAt(i).widget()
				assert w is not None
				w.deleteLater()
			knob.deleteLater()
		self.knobs.clear()
		for row, knob in enumerate(self.mod.knobs.values()):
			if knob.info.dropdown_id:
				p = DropdownKnobView(self.mw, self.mod_idx, knob)
			else:
				p = DialKnobView(self.mw, self.mod_idx, knob)
			self.mw.gr.addLayout(p, row % maxrows + 4, self.col + row // maxrows)
			self.knobs[knob.info.id] = p

	def refresh_en(self):
		with no_signals(self.en):
			self.en.setChecked(not not self.mod.en)

	@Slot(int)
	def en_changed(self, val: int):
		self.mod.en = int(not not val)
		self.mw.send_ev(model.ModuleOnOff(self.mod_idx))

class FxModView(ModView):
	def __init__(self, mw: MainWindow, side: int, mod_idx: ModIdx, col: int):
		super().__init__(mw, side, mod_idx, col)

		self.img = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		# self.img.setCursor(Qt.CursorShape.OpenHandCursor)
		mw.gr.addWidget(self.img, side % 2, col, 1 + side//2, 1)

		self.fx_menu = FxMenu()
		self.fx_menu.menu().triggered.connect(self.type_changed)
		mw.gr.addWidget(self.fx_menu, 2, col)

		mw.gr.addWidget(self.en, 3, col, alignment=Qt.AlignmentFlag.AlignCenter)

		self.refresh_type()

	def refresh_type(self):
		self.img.setPixmap(load_img(self.mod))
		with no_signals(self.fx_menu):
			self.fx_menu.setText(self.mod.info.name)
		self.refresh_knobs()

	@Slot(QAction)
	def type_changed(self, act: QAction):
		self.mod.change_type(act.data())
		self.mw.send_ev(model.ModuleType(self.mod_idx))
		if self.mod.info is no_mod:
			self.mw.reload()
		else:
			self.refresh_type()

class AmpModView(ModView):
	def __init__(self, mw: MainWindow, side: int, mod_idx: ModIdx, col: int):
		super().__init__(mw, side, mod_idx, col)
		self.cab = mw.model.preset.modules[mod_idx+2]

		self.amp_img = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		self.cab_img = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)

		self.ampbox = QComboBox(maxVisibleItems=16)
		# self.ampbox.setStyleSheet("padding-top: 1px; padding-bottom: 1px;");
		self.ampbox.addItems([amp.name for amp in amps])
		self.ampbox.currentIndexChanged.connect(self.amp_changed)
		self.ampbox.setToolTip('Amp')
		mw.gr.addWidget(self.ampbox, 2, col)

		self.cabbox = QComboBox(maxVisibleItems=16)
		# self.cabbox.setStyleSheet("padding-top: 1px; padding-bottom: 1px;");
		self.cabbox.addItems([cab.name for cab in cabs])
		self.cabbox.currentIndexChanged.connect(self.cab_changed)
		self.cabbox.setToolTip('Cab')
		mw.gr.addWidget(self.cabbox, 2, col+1)

		mw.gr.addWidget(self.en, 3, col, alignment=Qt.AlignmentFlag.AlignCenter)

		self.micbox = QComboBox()
		self.micbox.addItems([mic.name for mic in mics])
		self.micbox.currentIndexChanged.connect(self.mic_changed)
		self.micbox.setToolTip('Mic')
		mw.gr.addWidget(self.micbox, 3, col+1)

		# TODO add mic image somewhere?

		self.refresh_type()

	def refresh_mic(self):
		with no_signals(self.micbox):
			self.micbox.setCurrentIndex(self.mw.model.preset.int_params[0x34 + self.mod_idx])

	def refresh_cab(self):
		with no_signals(self.cabbox):
			self.cabbox.setCurrentIndex(cab_index[self.cab.info.id])
		if self.mod.info.img_idx == self.cab.info.img_idx:
			self.cab_img.hide()
			self.mw.gr.addWidget(self.amp_img, self.side % 2, self.col, 1 + self.side//2, 2)
		else:
			self.cab_img.setPixmap(load_img(self.cab))
			self.cab_img.show()
			self.mw.gr.addWidget(self.amp_img, self.side % 2, self.col+0, 1 + self.side//2, 1)
			self.mw.gr.addWidget(self.cab_img, self.side % 2, self.col+1, 1 + self.side//2, 1)

	def refresh_type(self):
		with no_signals(self.ampbox):
			self.ampbox.setCurrentIndex(amp_index[self.mod.info.id])
		self.amp_img.setPixmap(load_img(self.mod))
		if self.mod.info is no_mod:
			self.cab_img.hide()
			self.cabbox.hide()
			self.micbox.hide()
		else:
			self.cabbox.show()
			self.micbox.show()
			self.refresh_cab()
			self.refresh_mic()
		self.refresh_knobs()

	@Slot(QAction)
	def amp_changed(self, amp_idx: int):
		self.mod.change_type(amps[amp_idx].id)
		self.mw.send_ev(model.ModuleType(self.mod_idx))
		self.refresh_type()

	@Slot(QAction)
	def cab_changed(self, cab_idx: int):
		self.cab.change_type(cabs[cab_idx].id)
		self.mw.send_ev(model.ModuleType(self.mod_idx+2))
		self.refresh_cab()

	@Slot(QAction)
	def mic_changed(self, mic_idx: int):
		self.mw.model.preset.int_params[0x34 + self.mod_idx] = mic_idx
		self.mw.send_ev(model.ParamChangeInt(0x34 + self.mod_idx))

class Line1(QWidget):
	def paintEvent(self, event, /) -> None:
		painter = QPainter(self)
		app: QApplication = QApplication.instance() # type: ignore
		painter.setPen(QPen(app.palette().windowText().color(), 2))
		w, h = self.width(), self.height()
		painter.drawLine(0, h//2, w, h//2)

class Line2(QWidget):
	def paintEvent(self, event, /) -> None:
		painter = QPainter(self)
		painter.setRenderHints(QPainter.RenderHint.Antialiasing)
		app: QApplication = QApplication.instance() # type: ignore
		painter.setPen(QPen(app.palette().windowText().color(), 2))
		w, h = self.width(), self.height()
		x1, y1 = 40, h//4
		x2, y2 = w-x1, h-y1
		painter.drawPolyline([
			QPoint(0, h//2),
			QPoint(x1, y1),
			QPoint(x2, y1),
			QPoint(w, h//2),
		])
		painter.drawPolyline([
			QPoint(0, h//2),
			QPoint(x1, y2),
			QPoint(x2, y2),
			QPoint(w, h//2),
		])

@dataclass
class InsPoint:
	lane: int
	lane_pos: int
	side: int
	col: int

class SetlistDialog(QDialog):
	def __init__(self, mw: MainWindow):
		super().__init__(mw)
		self.mw = mw
		self.setWindowTitle("Setlists")
		self.tree = QTreeView(self)
		self.tree.setHeaderHidden(True)
		self.reload()

		lay = QVBoxLayout()
		lay.addWidget(self.tree)
		lay.setContentsMargins(0, 0, 0, 0)
		self.setLayout(lay)

	def sizeHint(self, /) -> QSize:
		return QSize(300, self.mw.height())

	def reload(self):
		self.model = QStandardItemModel()
		root = self.model.invisibleRootItem()
		for sl in self.mw.model.bank:
			sl_it = QStandardItem(sl.name)
			sl_it.setEditable(False)
			for i, pres in enumerate(sl.presets):
				it = QStandardItem(f'{i//4+1:02}{"ABCD"[i%4]} {pres.name}')
				it.setEditable(False)
				sl_it.appendRow(it)
			root.appendRow(sl_it)
		self.tree.setModel(self.model)
		self.update_sel()

	def update_sel(self):
		sl = self.model.index(self.mw.model.sel_list, 0)
		idx = self.model.index(self.mw.model.sel_preset, 0, sl)
		self.tree.selectionModel().setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)

class MainWindow(QMainWindow, EvListener):
	mods: dict[ModIdx, ModView]
	cols: dict[int, ModIdx]
	ins_points: list[InsPoint]

	def __init__(self, model: model.Model, on_closed: Callable[[], None]):
		super().__init__()
		model.listeners.append(self)
		self.model = model
		self.on_closed = on_closed

		self.setWindowTitle('POD HD Pro X')

		tb = self.addToolBar('Main Toolbar')
		tb.setMovable(False)
		openAct = tb.addAction(QIcon.fromTheme(QIcon.ThemeIcon.DocumentOpen), 'Open')
		openAct.triggered.connect(self.opendialog)
		openAct.setShortcut(QKeySequence.StandardKey.Open)
		saveAct = tb.addAction(QIcon.fromTheme(QIcon.ThemeIcon.DocumentSaveAs), 'Save As')
		saveAct.triggered.connect(self.savedialog)
		saveAct.setShortcut(QKeySequence.StandardKey.Save)
		# tb.addSeparator()
		# tb.addAction(QIcon.fromTheme(QIcon.ThemeIcon.ListAdd), 'Add Module').triggered.connect(self.add_module)
		self.top_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		self.top_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
		tb.addWidget(self.top_label)

		act = tb.addAction(QIcon.fromTheme('go-previous-skip'), 'Prev setlist')
		act.triggered.connect(self.prev_list)
		act.setShortcut(Qt.Key.Key_Home)

		act = tb.addAction(QIcon.fromTheme('go-previous'), 'Prev preset')
		act.triggered.connect(self.prev_pres)
		act.setShortcut(Qt.Key.Key_PageUp)

		tb.addAction(QIcon.fromTheme('application-menu'), 'Setlists').triggered.connect(self.show_setlist_dialog)

		act = tb.addAction(QIcon.fromTheme('go-next'), 'Next preset')
		act.triggered.connect(self.next_pres)
		act.setShortcut(Qt.Key.Key_PageDown)

		act = tb.addAction(QIcon.fromTheme('go-next-skip'), 'Next setlist')
		act.triggered.connect(self.next_list)
		act.setShortcut(Qt.Key.Key_End)

		# TODO shift+click/pageup should switch setlists

		self.setlist_dialog: SetlistDialog | None = None

		self.sb = QStatusBar(self)
		self.setStatusBar(self.sb)

		self.dragmod = -1
		self.dropins = -1

	@Slot(QAction)
	def opendialog(self, act: QAction):
		file, filt = QFileDialog.getOpenFileName(self, filter='POD HD Pro X Files (*.pxe *.pxs *.pxb)')
		if file == '':
			return
		self.do_load_file(file)

	def do_load_file(self, file: str):
		try:
			with open(file, 'rb') as f:
				res = parse_any_px(f)
		except OSError as e:
			QMessageBox.critical(self, 'Failed reading file', str(e), QMessageBox.StandardButton.Ok)
		except AssertionError as e:
			QMessageBox.critical(self, 'Failed parsing file', 'The file you tried to open is in an unknown format or contains invalid data', QMessageBox.StandardButton.Ok)
		else:
			if isinstance(res, PresetState):
				self.model.bank[self.model.sel_list].presets[self.model.sel_preset] = res
			elif isinstance(res, Setlist):
				self.model.bank[self.model.sel_list] = res
			else:
				self.model.bank = res
			self.pres_changed()

	@Slot(QAction)
	def savedialog(self, act: QAction):
		filters = (
			'POD HD Pro X Patch Files (*.pxe)',
			'POD HD Pro X Setlist Files (*.pxs)',
			'POD HD Pro X Patch Bundle Files (*.pxb)',
		)
		file, filt = QFileDialog.getSaveFileName(self, filter=';;'.join(filters))
		if file == '':
			return
		try:
			with open(file, 'wb') as f:
				idx = filters.index(filt)
				if idx == 0:
					write_pxe(f, self.model.preset)
				elif idx == 1:
					write_pxs(f, self.model.bank[self.model.sel_list])
				elif idx == 2:
					write_pxb(f, self.model.bank)
		except OSError as e:
			QMessageBox.critical(self, 'Failed writing file', str(e), QMessageBox.StandardButton.Ok)

	@Slot(QAction)
	def add_module(self, act: QAction):
		mods = self.model.preset.modules
		try:
			idx = next(i for i, mod in enumerate(mods[4:], 4) if mod.info is no_mod)
		except StopIteration:
			return
		mods[idx].change_type(0x2000011)
		self.send_ev(model.ModuleType(idx))
		self.reload()

	@Slot(QAction)
	def next_pres(self, act: QAction):
		self.model.sel_preset = (self.model.sel_preset + 1) % 64
		self.pres_changed()

	@Slot(QAction)
	def prev_pres(self, act: QAction):
		self.model.sel_preset = (self.model.sel_preset + 64 - 1) % 64
		self.pres_changed()

	@Slot(QAction)
	def next_list(self, act: QAction):
		self.model.sel_list = (self.model.sel_list + 1) % 8
		self.pres_changed()

	@Slot(QAction)
	def prev_list(self, act: QAction):
		self.model.sel_list = (self.model.sel_list + 8 - 1) % 8
		self.pres_changed()

	def pres_changed(self):
		self.model.preset = self.model.bank[self.model.sel_list].presets[self.model.sel_preset]
		self.send_ev(model.ListSel())
		self.send_ev(model.PresetSel())
		if self.setlist_dialog is not None:
			self.setlist_dialog.update_sel()
		self.reload()

	@Slot(QAction)
	def show_setlist_dialog(self, act: QAction):
		if self.setlist_dialog is None:
			self.setlist_dialog = SetlistDialog(self)
			self.setlist_dialog.tree.activated.connect(self.dialog_click)
		self.setlist_dialog.show()
		self.setlist_dialog.raise_()
		self.setlist_dialog.activateWindow()

	@Slot(QModelIndex)
	def dialog_click(self, idx: QModelIndex):
		par = idx.parent()
		if par.isValid():
			self.model.sel_list = par.row()
			self.model.sel_preset = idx.row()
			self.pres_changed()

	async def on_ev(self, ev: Event):
		match ev:
			case model.WholePreset():
				self.reload()
			case model.KnobEvent(mod_idx, knob_id):
				kn = self.mods[mod_idx].knobs[knob_id]
				match ev:
					case model.KnobValue():
						kn.refresh_val()
			case model.ModuleType(mod_idx):
				self.reload()
			case model.ModuleEvent(mod_idx):
				mod = self.mods.get(mod_idx)
				if mod is None:
					return
				match ev:
					case model.ModuleOnOff():
						mod.refresh_en()

	def create_mod(self, side: int, mod_idx: ModIdx, col: int | None = None):
		# if self.model.preset.modules[mod_idx].model is no_mod:
		# 	return
		if col is None:
			col = self.gr.columnCount()
		if mod_idx < 2:
			mod = AmpModView(self, side, mod_idx, col)
		else:
			mod = FxModView(self, side, mod_idx, col)
		self.mods[mod_idx] = mod
		self.cols[col] = mod_idx

	def add_ins_point(self, lane: int, lane_pos: int, side: int):
		col = self.gr.columnCount() - 1
		if self.ins_points:
			last = self.ins_points[-1]
			if last.side == side and last.col == col:
				return
		self.ins_points.append(InsPoint(lane, lane_pos, side, col))

	def pr_lane(self, lane: int):
		lm = lane_map[lane]
		lanes = self.model.preset.lanes
		if lm.pos == self.amp_pos and lm.end == 0 and lm.amp not in self.mods:
			self.create_mod(lm.side, lm.amp)
		for i, m in enumerate(lanes[lane]):
			self.add_ins_point(lane, i, lm.side)
			self.create_mod(lm.side, m)
		self.add_ins_point(lane, len(lanes[lane]), lm.side)
		if lm.pos == self.amp_pos and lm.end == 1 and lm.amp not in self.mods:
			self.create_mod(lm.side, lm.amp)

	def reload(self):
		sp = self.model.sel_preset
		self.top_label.setText(f'{self.model.bank[self.model.sel_list].name} - {sp//4+1:02}{"ABCD"[sp%4]} {self.model.preset.name}')
		self.mods = {}
		self.cols = {}
		self.ins_points = []
		widget = QWidget()
		self.setCentralWidget(widget)
		self.gr = QGridLayout(widget)
		self.gr.setRowMinimumHeight(0, 120)
		self.gr.setRowMinimumHeight(1, 120)
		self.amp_pos = self.model.preset.amp_pos()
		self.pr_lane(0)
		self.lrsplit = self.gr.columnCount()
		self.pr_lane(1)
		self.pr_lane(3)
		self.lrswitch = self.gr.columnCount()
		self.pr_lane(2)
		self.pr_lane(4)
		# print(  '  mix  ')
		self.lrjoin = self.gr.columnCount()
		self.pr_lane(5)

		line1 = Line1()
		line2 = Line2()
		line3 = Line1()
		if self.lrsplit > 1:
			self.gr.addWidget(line1, 0, 1, 2, self.lrsplit-1)
		if self.lrjoin != self.lrsplit:
			self.gr.addWidget(line2, 0, self.lrsplit, 2, self.lrjoin-self.lrsplit)
		if self.lrjoin != self.gr.columnCount():
			self.gr.addWidget(line3, 0, self.lrjoin, 2, self.gr.columnCount() - self.lrjoin)
		line1.lower()
		line2.lower()
		line3.lower()

	def closeEvent(self, event, /) -> None:
		self.on_closed()
		return super().closeEvent(event)

	def is_valid_drag(self, ev: QMouseEvent):
		top = self.centralWidget().y() + self.gr.cellRect(0, 0).top()
		bot = self.centralWidget().y() + self.gr.cellRect(1, 0).bottom()
		return top < ev.y() < bot

	def mouse2col(self, ev: QMouseEvent):
		if not self.is_valid_drag(ev):
			return -1
		return bisect(range(self.gr.columnCount()), ev.x(), key=lambda col: self.gr.cellRect(0, col).left()) - 1

	def mouse2ins(self, ev: QMouseEvent):
		if not self.is_valid_drag(ev):
			return -1
		x0 = self.centralWidget().x() + self.gr.verticalSpacing() // 2
		def getx(ip: InsPoint):
			return x0 + self.gr.cellRect(0, ip.col).right()
		midpoints = [ (getx(a)+getx(b))//2 for a, b in pairwise(self.ins_points) ]
		return bisect(midpoints, ev.x())

	def drag_end(self):
		self.dragmod = self.dropins = -1
		self.setCursor(Qt.CursorShape.ArrowCursor)

	def mousePressEvent(self, event: QMouseEvent, /) -> None:
		if event.button() != Qt.MouseButton.LeftButton:
			if self.dragmod != -1:
				self.drag_end()
				self.update()
			return
		col = self.mouse2col(event)
		self.dragmod = self.cols.get(col, self.cols.get(col-1, -1))
		if self.dragmod != -1:
			self.setCursor(Qt.CursorShape.DragMoveCursor)

	def mouseReleaseEvent(self, event: QMouseEvent, /) -> None:
		if self.dragmod == -1:
			return
		dragmod, dropins = self.dragmod, self.dropins
		self.drag_end()
		if dropins == -1:
			return
		ins = self.ins_points[dropins]
		self.model.preset.move_mod(dragmod, ins.lane, ins.lane_pos)
		self.send_ev(model.WholePreset())
		self.reload()
		self.update()

	def fix_ins_point(self, dropins: int) -> int:
		if dropins == -1:
			return -1
		ins = self.ins_points[dropins]
		lane = self.model.preset.lanes[ins.lane]
		if self.dragmod < 2:
			lm = lane_map[ins.lane]
			lane_pos = lm.end * len(lane)
			if self.amp_pos == lm.pos and ins.lane_pos == lane_pos and lm.amp == self.dragmod:
				return -1
			if ins.lane in (0, 5) and ins.lane_pos != lane_pos:
				return -1
		else:
			if self.dragmod not in lane:
				return dropins
			lane_pos = lane.index(self.dragmod)
			if ins.lane_pos == lane_pos:
				if dropins-1 >= 0 and self.ins_points[dropins-1].col == ins.col:
					return dropins - 1
				return -1
			elif ins.lane_pos == lane_pos + 1:
				if dropins+1 < len(self.ins_points) and self.ins_points[dropins+1].col == ins.col:
					return dropins + 1
				return -1
		return dropins

	def mouseMoveEvent(self, event: QMouseEvent, /) -> None:
		if self.dragmod == -1:
			return
		dropins = self.fix_ins_point(self.mouse2ins(event))
		if dropins != self.dropins:
			self.dropins = dropins
			self.update()

	def paintEvent(self, event, /) -> None:
		super().paintEvent(event)

		if self.dropins == -1:
			return

		ins = self.ins_points[self.dropins]
		side = ins.side

		painter = QPainter(self)
		app: QApplication = QApplication.instance() # type: ignore
		painter.setPen(QPen(app.palette().accent().color(), 3))
		x = self.centralWidget().x() + self.gr.cellRect(0, ins.col).right() + self.gr.verticalSpacing() // 2
		y = self.centralWidget().y() + (self.gr.cellRect(side % 2, 0).top() + self.gr.cellRect(side // 2 + side % 2, 0).bottom()) // 2
		painter.drawLine(x, y-50, x, y+50)
