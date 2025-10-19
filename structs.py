from __future__ import annotations
import struct
from typing import Iterable, Literal, TYPE_CHECKING

from realdata import AmpModel, Model, Param, models, params
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

class KnobState:
	param: Param
	val: int | float
	min: int | float
	max: int | float
	ctrl: int

	def __init__(self, model: Model, pbuf: bytes | int, struct: MyPacker):
		if isinstance(pbuf, int):
			self.param = model.params[pbuf]
			self.val = self.min = self.max = self.ctrl = 0
			return
		id, = struct.unpack('i', pbuf[:4])
		self.param = model.params[id]
		if self.param.id & 0xff0000:
			self.val, self.min, self.max = struct.unpack('3f', pbuf[4:-4])
		else:
			self.val, self.min, self.max = struct.unpack('3i', pbuf[4:-4])
		self.ctrl = pbuf[-4]

	def dump(self, struct: MyPacker) -> bytes:
		fmt = 'ifffb3x' if self.param.id & 0xff0000 else 'iiiib3x'
		return struct.pack(fmt, self.param.id, self.val, self.min, self.max, self.ctrl)

no_mod = Model(0xffff, 'None', 0, {}, [], [])

mod_fmt = 'IIBBBxBxxB'
class ModState:
	model_id: int
	pos: int
	en: int
	tempo1: int
	tempo2: int
	fs: int
	model: Model
	knobs: dict[int, KnobState]

	def load_knobs(self, bufs: Iterable[bytes], struct: MyPacker):
		for pbuf in bufs:
			p = KnobState(self.model, pbuf, struct)
			self.knobs[p.param.id] = p
		for id in self.model.params:
			if id not in self.knobs:
				self.knobs[id] = KnobState(self.model, id, struct)

	def update_model(self):
		self.knobs = {}
		if self.model_id & 0xffff == 0xffff:
			self.model = no_mod
			return
		self.model = models[self.model_id]

	def __init__(self, pres: PresetState, buf: bytes, struct: MyPacker):
		assert len(buf) == 0x100
		self.pres = pres
		self.model_id, self.pos, self.en, self.tempo1, self.tempo2, self.fs, n_knobs = struct.unpack(mod_fmt, buf[:0x10])
		self.update_model()
		if self.model is not no_mod:
			assert len(self.model.params) >= n_knobs, (self.model, len(self.model.params), n_knobs, buf.hex())
			self.load_knobs(chunk_bytes(buf, 20, 0x10, n_knobs), struct)

	def change_type(self, model_id: int):
		self.model_id = model_id
		self.update_model()
		if self.model is not no_mod:
			self.load_knobs(self.model.defs, LEStruct)
			if isinstance(self.model, AmpModel):
				idx = self.pres.modules.index(self)
				self.pres.modules[idx+2].change_type(self.model.def_cab)
				self.pres.int_params[0x34+idx] = self.model.def_mic

	def dump(self, struct: MyPacker) -> bytes:
		head = struct.pack(mod_fmt, self.model_id, self.pos, self.en, self.tempo1, self.tempo2, self.fs, len(self.knobs))
		data = head + b''.join( param.dump(struct) for param in self.knobs.values() )
		return data.ljust(0x100, b'\0')

preset_fmt = '16s16xI4x'
class PresetState:
	name: str
	modules: list[ModState]
	flt_params: dict[int, float]
	int_params: dict[int, int]

	def __init__(self, data: bytes, struct: MyPacker):
		assert len(data) == 0x1000
		rawname, mcount_msize = struct.unpack(preset_fmt, data[:0x28])
		mcount = mcount_msize & 0xff
		msize = mcount_msize >> 8
		assert mcount == 12, f'expected 12 modules, got {mcount}'
		assert msize == 0x100, f'expected 0x100 bytes per module, got {msize}'
		self.name = rawname.rstrip(b'\0 ').decode()
		self.modules = [ ModState(self, chunk, struct) for chunk in chunk_bytes(data, msize, 0x28, mcount) ]
		self.flt_params = {}
		self.int_params = {}
		for pid, (is_flt, offs, name) in params.items():
			if is_flt:
				self.flt_params[pid], = struct.unpack('f', data[offs:offs+4])
			else:
				self.int_params[pid] = data[offs]

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
