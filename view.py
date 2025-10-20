from __future__ import annotations
from contextlib import contextmanager

from PySide6.QtCore import QObject, QPoint, QSize, Qt, Slot
from PySide6.QtGui import QAction, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QDial,
	QGridLayout,
	QLabel,
	QMainWindow,
	QMenu,
	QPushButton,
	QVBoxLayout,
	QWidget,
)

from model import EvListener, Event
import model
from realdata import categories, dropdowns, models, Model
from structs import KnobState, ModState, no_mod

amps = [ mod for mod in models.values() if mod.id >> 16 == 0x0007 ]
amp_index = { mod.id: i for i, mod in enumerate(amps) }
no_cab = Model(no_mod.id, 'No Cab', 0, {}, [], [])
cabs = [ mod for mod in models.values() if mod.id >> 16 == 0x0107 ] + [no_cab]
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
	def __init__(self, ev: EvListener, mod_idx: int, knob: KnobState):
		super().__init__()

		self.ev = ev
		self.mod_idx = mod_idx
		self.knob = knob

	def refresh_val(self): ...

	def send_ev(self, T: type[model.KnobEvent]):
		self.ev.send_ev(T(self.mod_idx, self.knob.param.id))

class DialKnobView(KnobView):
	def __init__(self, ev: EvListener, mod_idx: int, knob: KnobState):
		super().__init__(ev, mod_idx, knob)

		self.dial = QDial()
		self.refresh_val()
		self.dial.actionTriggered.connect(self.valChanged)

		self.addWidget(self.dial, stretch=1)
		self.label = QLabel(knob.param.name, alignment=Qt.AlignmentFlag.AlignCenter)
		self.addWidget(self.label)

	def refresh_val(self):
		with no_signals(self.dial):
			self.dial.setValue(int(self.knob.val*100))

	@Slot(int)
	def valChanged(self, val: int):
		self.knob.val = self.dial.value()/100
		self.send_ev(model.KnobValue)

class DropdownKnobView(KnobView):
	def __init__(self, ev: EvListener, mod_idx: int, knob: KnobState):
		super().__init__(ev, mod_idx, knob)

		self.cbox = QComboBox()
		self.cbox.setMaximumWidth(120)
		self.dd = dropdowns[knob.param.dropdown_id]
		self.cbox.addItems(self.dd.opts)
		self.refresh_val()
		self.cbox.currentIndexChanged.connect(self.idxChanged)

		self.addWidget(self.cbox, stretch=1, alignment=Qt.AlignmentFlag.AlignCenter)
		self.label = QLabel(knob.param.name, alignment=Qt.AlignmentFlag.AlignCenter)
		self.addWidget(self.label)

	def refresh_val(self):
		val = self.knob.val
		if isinstance(val, float):
			val = round(val * (len(self.dd.opts)-1))
		with no_signals(self.cbox):
			self.cbox.setCurrentIndex(val - self.dd.offset)

	@Slot(int)
	def idxChanged(self, idx: int):
		val = idx + self.dd.offset
		if isinstance(self.knob.val, float):
			val /= len(self.dd.opts)-1
		if self.knob.val == val:
			return
		self.knob.val = val
		self.send_ev(model.KnobValue)

LEFT = 0
RIGHT = 1
MID = 2

def load_img(mod: ModState):
	if mod.model.img_idx == 0:
		return QPixmap()
	return QPixmap(f'img/{mod.model.img_idx:03}.png') \
		.scaled(QSize(120, 120), Qt.AspectRatioMode.KeepAspectRatio)

class ModMenu(QPushButton):
	def __init__(self, model: ModState):
		super().__init__()

		menu = QMenu(self)
		self.setMenu(menu)
		cat_menus: dict[int, QMenu] = {}
		for catid, cat in categories.items():
			if catid == 13:
				menu.addAction(cat).setData(0x02ffff)
			else:
				cat_menus[catid] = menu.addMenu(cat)
		for mod in models.values():
			if mod.id >> 24 == 0x02:
				act = cat_menus[(mod.id >> 16) & 0xff].addAction(mod.name)
				act.setData(mod.id)

	# TODO quick switching with mouse wheel
	# def wheelEvent(self, event: QWheelEvent, /) -> None:

class ModViewBase(QObject):
	def __init__(self, mw: MainWindow, side: int, mod_idx: int, col: int):
		super().__init__()
		self.mw = mw
		self.side = side
		self.mod_idx = mod_idx
		self.col = col
		self.mod = mw.model.preset.modules[mod_idx]
		self.knobs: dict[int, KnobView] = {}

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
			if knob.param.dropdown_id:
				p = DropdownKnobView(self.mw, self.mod_idx, knob)
			else:
				p = DialKnobView(self.mw, self.mod_idx, knob)
			self.mw.gr.addLayout(p, row % maxrows + 4, self.col + row // maxrows)
			self.knobs[knob.param.id] = p

	def refresh_en(self):
		with no_signals(self.en):
			self.en.setChecked(not not self.mod.en)

	@Slot(int)
	def en_changed(self, val: int):
		self.mod.en = int(not not val)
		self.mw.send_ev(model.ModuleOnOff(self.mod_idx))

class ModView(ModViewBase):
	def __init__(self, mw: MainWindow, side: int, mod_idx: int, col: int):
		super().__init__(mw, side, mod_idx, col)

		self.img = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		mw.gr.addWidget(self.img, side % 2, col, 1 + side//2, 1)

		self.mod_menu = ModMenu(self.mod)
		self.mod_menu.menu().triggered.connect(self.type_changed)
		mw.gr.addWidget(self.mod_menu, 2, col)

		mw.gr.addWidget(self.en, 3, col, alignment=Qt.AlignmentFlag.AlignCenter)

		self.refresh_type()

	def refresh_type(self):
		self.img.setPixmap(load_img(self.mod))
		with no_signals(self.mod_menu):
			self.mod_menu.setText(self.mod.model.name)
		self.refresh_knobs()

	@Slot(QAction)
	def type_changed(self, act: QAction):
		self.mod.change_type(act.data())
		self.mw.send_ev(model.ModuleType(self.mod_idx))
		if self.mod.model is no_mod:
			self.mw.reload()
		else:
			self.refresh_type()

class AmpModView(ModViewBase):
	def __init__(self, mw: MainWindow, side: int, mod_idx: int, col: int):
		super().__init__(mw, side, mod_idx, col)
		self.cab = mw.model.preset.modules[mod_idx+2]

		self.amp_img = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		self.cab_img = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)

		self.ampbox = QComboBox()
		self.ampbox.setStyleSheet("QComboBox { padding-top: 1px; padding-bottom: 1px; }");
		self.ampbox.addItems([amp.name for amp in amps]) # TODO Amp disabled
		self.ampbox.currentIndexChanged.connect(self.amp_changed)
		self.ampbox.setToolTip('Amp')
		mw.gr.addWidget(self.ampbox, 2, col)

		self.cabbox = QComboBox()
		self.cabbox.setStyleSheet("QComboBox { padding-top: 1px; padding-bottom: 1px; }");
		self.cabbox.addItems([cab.name for cab in cabs]) # TODO No cab
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
			self.cabbox.setCurrentIndex(cab_index[self.cab.model.id])
		if self.mod.model.img_idx == self.cab.model.img_idx:
			self.cab_img.hide()
			self.mw.gr.addWidget(self.amp_img, self.side % 2, self.col, 1 + self.side//2, 2)
		else:
			self.cab_img.setPixmap(load_img(self.cab))
			self.cab_img.show()
			self.mw.gr.addWidget(self.amp_img, self.side % 2, self.col+0, 1 + self.side//2, 1)
			self.mw.gr.addWidget(self.cab_img, self.side % 2, self.col+1, 1 + self.side//2, 1)

	def refresh_type(self):
		with no_signals(self.ampbox):
			self.ampbox.setCurrentIndex(amp_index[self.mod.model.id])
		self.amp_img.setPixmap(load_img(self.mod))
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

class MainWindow(QMainWindow, EvListener):
	mods: dict[int, ModViewBase]

	def __init__(self, model: model.Model, on_closed):
		super().__init__()
		model.listeners.append(self)
		self.model = model
		self.on_closed = on_closed

		tb = self.addToolBar('Foo')
		tb.addAction(QIcon.fromTheme(QIcon.ThemeIcon.GoPrevious), 'Prev preset')
		tb.addAction(QIcon.fromTheme(QIcon.ThemeIcon.GoNext), 'Next preset')

	async def on_ev(self, ev: Event):
		match ev:
			case model.WholePreset():
				self.reload()
			case model.KnobEvent(mod_idx, knob_id):
				kn = self.mods[mod_idx].knobs[knob_id]
				match ev:
					case model.KnobValue():
						kn.refresh_val()
			case model.ModuleType():
				self.reload()
			case model.ModuleEvent(mod_idx):
				mod = self.mods.get(mod_idx)
				if mod is None:
					return
				match ev:
					case model.ModuleOnOff():
						mod.refresh_en()

	def create_mod(self, side: int, mod_idx: int, col: int | None = None):
		if self.model.preset.modules[mod_idx].model is no_mod:
			return
		if col is None:
			col = self.gr.columnCount()
		if mod_idx < 2:
			self.mods[mod_idx] = AmpModView(self, side, mod_idx, col)
		else:
			self.mods[mod_idx] = ModView(self, side, mod_idx, col)

	def reload(self):
		self.mods = {}
		widget = QWidget()
		self.setCentralWidget(widget)
		self.gr = QGridLayout(widget)
		mods = self.model.preset.modules
		lanes: list[list[int]] = [ [] for _ in range(10) ]
		for i, mod in enumerate(mods):
			lanes[(mod.pos>>16) & 0xff].append(i)
		for lane in lanes:
			lane.sort(key=lambda i: mods[i].pos & 0xff)
		def pr_lane(side: int, lane: int):
			for m in lanes[lane]:
				self.create_mod(side, m)
		amp_pos = mods[0].pos & 0xff
		pr_lane(MID, 0)
		if amp_pos == 5:
			self.create_mod(MID, 0)
		lrsplit = self.gr.columnCount()
		pr_lane(LEFT, 1)
		if amp_pos == 0:
			self.create_mod(LEFT, 0)
		pr_lane(LEFT, 3)
		pr_lane(RIGHT, 2)
		if amp_pos == 0:
			self.create_mod(RIGHT, 1)
		pr_lane(RIGHT, 4)
		# print(  '  mix  ')
		lrjoin = self.gr.columnCount()
		if amp_pos == 7:
			self.create_mod(MID, 0)
		pr_lane(MID, 5)

		line1 = Line1()
		line2 = Line2()
		line3 = Line1()
		self.gr.addWidget(line1, 0, 1, 2, lrsplit-1)
		self.gr.addWidget(line2, 0, lrsplit, 2, lrjoin-lrsplit)
		self.gr.addWidget(line3, 0, lrjoin, 2, self.gr.columnCount() - lrjoin)
		line1.lower()
		line2.lower()
		line3.lower()

	def closeEvent(self, event, /) -> None:
		self.on_closed()
		return super().closeEvent(event)
