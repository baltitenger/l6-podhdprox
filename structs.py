from __future__ import annotations
from dataclasses import dataclass, field
import struct
from typing import Iterable, Literal, TYPE_CHECKING

from data import AmpModInfo, KnobInfo, ModIdx, ModInfo, params
from data_gen import models
from util import chunk_bytes

if TYPE_CHECKING:
	from _typeshed import ReadableBuffer, WriteableBuffer

class MyPacker:
	def __init__(self, endian: Literal['<', '>'] = '<') -> None:
		self.endian = endian

	def pack(self, fmt: str, *args) -> bytes:
		return struct.pack(self.endian + fmt, *args)

	def pack_into(self, fmt: str, buf: WriteableBuffer, offset: int, *args):
		struct.pack_into(self.endian + fmt, buf, offset, *args)

	def unpack(self, fmt: str, buf: ReadableBuffer):
		return struct.unpack(self.endian + fmt, buf)

LEStruct = MyPacker('<')
BEStruct = MyPacker('>')

@dataclass(slots=True, init=False)
class KnobState:
	info: KnobInfo
	val: int | float
	min: int | float
	max: int | float
	ctrl: int

	def __init__(self, model: ModInfo, pbuf: bytes, struct: MyPacker):
		id, = struct.unpack('i', pbuf[:4])
		self.info = model.knobs[id]
		if self.info.id & 0xff0000:
			self.val, self.min, self.max = struct.unpack('3f', pbuf[4:-4])
		else:
			self.val, self.min, self.max = struct.unpack('3i', pbuf[4:-4])
		self.ctrl = pbuf[-4]

	def dump(self, struct: MyPacker) -> bytes:
		fmt = 'ifffb3x' if self.info.id & 0xff0000 else 'iiiib3x'
		return struct.pack(fmt, self.info.id, self.val, self.min, self.max, self.ctrl)

no_mod = ModInfo(0x7fffffff, '[disabled]', 0, {}, [], [])

mod_fmt = 'IIBBBBBxxB'
@dataclass(slots=True, init=False)
class ModState:
	pres: PresetState = field(compare=False, repr=False)
	model_id: int
	pos: int
	en: int
	tempo1: int
	tempo2: int
	valid: int # otherwise -> DSP OVERLOAD
	fs: int
	info: ModInfo
	knobs: dict[int, KnobState]

	def load_knobs(self, bufs: Iterable[bytes], struct: MyPacker):
		for pbuf in bufs:
			p = KnobState(self.info, pbuf, struct)
			self.knobs[p.info.id] = p
		for id, default in zip(self.info.knobs, self.info.defs):
			if id not in self.knobs:
				self.knobs[id] = KnobState(self.info, default, LEStruct)

	def update_model(self):
		self.knobs = {}
		if self.model_id & 0xffff == 0xffff:
			self.info = no_mod
			return
		self.info = models[self.model_id]

	def __init__(self, pres: PresetState, idx: int):
		self.pres = pres
		self.en = self.tempo1 = self.tempo2 = self.valid = self.fs = 0
		if idx < 4:
			self.model_id = (0x0007ffff, 0x0007ffff, 0x0107ffff, 0x0107ffff)[idx]
			self.pos      = (0x05070005, 0x05080000, 0x05070000, 0x05080000)[idx]
		else:
			self.model_id = 0x020dffff
			self.pos      = (0x05000000, 0x05050000)[(idx-4)//4] + idx - 4
			self.fs       = idx - 4 + 1
		self.update_model()

	def load(self, buf: bytes, struct: MyPacker):
		assert len(buf) == 0x100
		self.model_id, self.pos, self.en, self.tempo1, self.tempo2, self.valid, self.fs, n_knobs = struct.unpack(mod_fmt, buf[:0x10])
		self.update_model()
		if self.info is not no_mod:
			assert len(self.info.knobs) >= n_knobs, (self.info, len(self.info.knobs), n_knobs, buf.hex())
			self.load_knobs(chunk_bytes(buf, 20, 0x10, n_knobs), struct)
		return self

	def change_type(self, model_id: int):
		self.model_id = model_id
		self.update_model()
		self.valid = self.info is not no_mod
		if self.valid:
			self.load_knobs(self.info.defs, LEStruct)
			if isinstance(self.info, AmpModInfo):
				idx = self.pres.modules.index(self)
				self.pres.modules[idx+2].change_type(self.info.def_cab)
				self.pres.int_params[0x34+idx] = self.info.def_mic

	def lane(self):
		return (self.pos >> 16) & 0xff

	def dump(self, struct: MyPacker) -> bytes:
		head = struct.pack(mod_fmt, self.model_id, self.pos, self.en, self.tempo1, self.tempo2, self.valid, self.fs, len(self.knobs))
		data = head + b''.join( knob.dump(struct) for knob in self.knobs.values() )
		return data.ljust(0x100, b'\0')

@dataclass
class LaneMap:
	amp: int
	'''Which amp is in the given lane'''
	pos: int
	'''Value of amp_pos if amp is in this lane'''
	end: int
	'''Which end of the lane has the amp'''
	side: int
	'''Which side the lane is on'''

LEFT = 0
RIGHT = 1
MID = 2

lane_map = [
	LaneMap(0, 5, 1, MID),
	LaneMap(0, 0, 1, LEFT),
	LaneMap(1, 0, 1, RIGHT),
	LaneMap(0, 0, 0, LEFT),
	LaneMap(1, 0, 0, RIGHT),
	LaneMap(0, 7, 0, MID),
]

preset_fmt = '16s16xI4x'
@dataclass(slots=True, init=False)
class PresetState:
	name: str
	modules: list[ModState]
	lanes: list[list[ModIdx]]
	flt_params: dict[int, float]
	int_params: dict[int, int]

	def __init__(self):
		self.name = 'New Tone'
		self.modules = [ ModState(self, i) for i in range(12) ]
		self.pos2lane()
		# todo actual defaults
		self.flt_params = { k: 0.0 for k, (fmt, _, _) in params.items() if fmt == 1 }
		self.int_params = { k: 0   for k, (fmt, _, _) in params.items() if fmt == 0 }

	def load(self, data: bytes, struct: MyPacker):
		assert len(data) == 0x1000
		rawname, mcount_msize = struct.unpack(preset_fmt, data[:0x28])
		mcount = mcount_msize & 0xff
		msize = mcount_msize >> 8
		assert mcount == 12, f'expected 12 modules, got {mcount}'
		assert msize == 0x100, f'expected 0x100 bytes per module, got {msize}'
		self.name = rawname.rstrip(b'\0 ').decode()
		for mod, chunk in zip(self.modules, chunk_bytes(data, msize, 0x28, mcount)):
			mod.load(chunk, struct)
		self.pos2lane()
		self.flt_params = {}
		self.int_params = {}
		for pid, (is_flt, offs, name) in params.items():
			if is_flt:
				self.flt_params[pid], = struct.unpack('f', data[offs:offs+4])
			else:
				self.int_params[pid] = data[offs]
		return self

	def pos2lane(self):
		self.lanes = [ [] for _ in range(6) ]
		for i, mod in enumerate(self.modules[4:], 4):
			self.lanes[mod.lane()].append(i)
		for lane in self.lanes:
			lane.sort(key=lambda i: self.modules[i].pos & 0xff)

	def lane2pos(self):
		for nr, (lane, mod_idx) in enumerate((lane, mod_idx) for lane, l in enumerate(self.lanes) for mod_idx in l):
			self.modules[mod_idx].pos = 0x05 << 24 | lane << 16 | nr

	def dump(self, struct: MyPacker) -> bytes:
		head = struct.pack(preset_fmt, self.name.encode(), 0x1000c)
		res = head + b''.join( mod.dump(struct) for mod in self.modules )
		res = bytearray(res.ljust(0x1000, b'\0'))
		for pid, (is_flt, offs, name) in params.items():
			if is_flt:
				struct.pack_into('f', res, offs, self.flt_params[pid])
			else:
				res[offs] = self.int_params[pid]
		return bytes(res)

	def swap_amps(self):
		# TODO this might be hard to get right
		# needs to take care of: amps, cabs, global parameters
		pass

	def amp_pos(self):
		return self.modules[0].pos & 0xff

	def set_amp_pos(self, pos: int):
		self.modules[0].pos = 0x05070000 | pos

	def move_mod(self, src_idx: ModIdx, dst_lane: int, dst_lane_pos: int):
		if src_idx < 2: # amp
			lm = lane_map[dst_lane]
			if lm.amp != src_idx:
				self.swap_amps()
			self.set_amp_pos(lm.pos)
			if dst_lane not in (0, 5):
				if dst_lane in (1, 3):
					a, b = 1, 3
				else:
					a, b = 2, 4
				merged = self.lanes[a] + self.lanes[b]
				pt = dst_lane_pos
				if dst_lane == b:
					pt += len(self.lanes[a])
				self.lanes[a] = merged[:pt]
				self.lanes[b] = merged[pt:]
		elif src_idx < 4:
			assert False, "Can't move a cab"
		else:
			src = self.lanes[self.modules[src_idx].lane()]
			dst = self.lanes[dst_lane]
			if src is dst and dst.index(src_idx) < dst_lane_pos:
				dst_lane_pos -= 1
			src.remove(src_idx)
			dst.insert(dst_lane_pos, src_idx)
		self.lane2pos()

@dataclass
class Setlist:
	name: str
	presets: list[PresetState] = field(default_factory=lambda: [ PresetState() for _ in range(64) ])

