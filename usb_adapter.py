import asyncio
from typing import cast

from usb1 import USBDeviceHandle

import model
from realdata import models, semitones
from structs import KnobState, PresetState, params
from usb_transport import Transport, struct

class UsbAdapter(Transport, model.EvListener):
	def __init__(self, hdl: USBDeviceHandle, model: model.Model) -> None:
		super().__init__(hdl)
		model.listeners.append(self)
		self.model = model

	async def bleh(self):
		await self.send_cmd(0x11, struct.pack('4xii', 0, 0x7fffffff))
		firstamp = True
		for mod_typ in models:
			ctgy = mod_typ >> 16
			if ctgy == 0x0007: # amp
				pos = 0
			elif ctgy == 0x0107: # cab
				continue
			elif ctgy == 0x0000 or ctgy == 0x7fff: # mic, no cab
				continue
			else: # model
				pos = 4
			# if mod_typ in (0x070083, 0x07006e, 0x070072, 0x070074, 0x070076, 0x070078, 0x07007c, 0x07007e, 0x070080, 0x070082):
			# 	continue # some amps have unexpected number of params
			if pos == 0 and firstamp:
				await self.send_cmd(0x11, struct.pack('4xii', 4, 0x7fffffff))
				firstamp = False
			await self.send_cmd(0x11, struct.pack('4xii', pos, mod_typ))
			self.foo = asyncio.Future()
			await self.rx_preset()
			await self.foo
			# mod = self.model.preset.modules[pos]
			# print(mod.model.name)
			# for k, v in mod.knobs.items():
			# 	print(k, v.val, v.min, v.max)
			# if pos == 0: # amp
			# 	print(params[0x34][2], self.model.preset.int_params[0x34])
			# 	for k in 0x30, 0x32, 0x57, 0x59, 0x5b, 0x5d:
			# 		v = self.model.preset.flt_params[k]
			# 		print(params[k][2], v)
			# if pos == 1: # cab
			# 	for k in 0x30, 0x32, 0x57, 0x59, 0x5b, 0x5d:
			# 		v = self.model.preset.flt_params[k]
			# 		print(params[k][2], v)

	def make_knobmsg(self, ev: model.KnobEvent, val: int | float):
		typ = int(isinstance(val, float))
		fmt = '4x3i' + 'if'[typ]
		return struct.pack(fmt, ev.mod_idx, typ, ev.knob_id, val)

	async def on_ev(self, ev: model.Event):
		preset = self.model.preset
		match ev:
			case model.WholePreset():
				await self.send_cmd(0x02, struct.pack('2h', -1, -1) + preset.dump(struct))
			case model.ListSel():
				await self.send_cmd(0x2c, struct.pack('i', self.model.sel_list))
			case model.PresetSel():
				await self.send_cmd(0x27, struct.pack('i', self.model.sel_preset))
			case model.ListName():
				await self.send_cmd(0x2c, struct.pack('i', self.model.sel_list))
			case model.KnobEvent(mod, knob_id):
				knob = preset.modules[mod].knobs[knob_id]
				match ev:
					case model.KnobValue():
						await self.send_cmd(0x2d, self.make_knobmsg(ev, knob.val))
					case model.KnobMin():
						await self.send_cmd(0x2e, self.make_knobmsg(ev, knob.min))
					case model.KnobMax():
						await self.send_cmd(0x2f, self.make_knobmsg(ev, knob.max))
					case model.KnobMax():
						await self.send_cmd(0x30, self.make_knobmsg(ev, knob.ctrl))
			case model.ModuleEvent(mod):
				module = preset.modules[mod]
				match ev:
					case model.ModuleType():
						await self.send_cmd(0x11, struct.pack('4xii', mod, module.model_id))
					case model.ModuleOnOff():
						await self.send_cmd(0x13, struct.pack('4xii', mod, module.en))
					case model.ModuleTempo1():
						await self.send_cmd(0x14, struct.pack('4xii', mod, module.tempo1))
					case model.ModuleTempo2():
						await self.send_cmd(0x31, struct.pack('4xii', mod, module.tempo2))
					case model.ModuleFswitch():
						await self.send_cmd(0x32, struct.pack('4xii', mod, module.fs))

	def knobmsg[T: model.KnobEvent](self, data: bytes, t: type[T]) -> tuple[KnobState, float | int, T]:
		mod, typ, knob = cast(tuple[int, int, int], struct.unpack('4xiii', data[:-4]))
		ref = self.model.preset.modules[mod].knobs[knob]
		fmt = 'f' if typ else 'i'
		val, = struct.unpack(fmt, data[-4:])
		return ref, val, t(mod, knob)


	async def on_pkt(self, is_resp: int, typ: int, data: bytes):
		mod: int
		match typ:
			case 0x01:
				self.model.preset = PresetState(data, struct)
				# TODO check if it's the current one
				self.send_ev(model.WholePreset())
			case 0x03:
				print('set preset ack: ', data.hex())
			case 0x11:
				# TODO what do
				# evt 0x11 00000000 07000000 ffff0d02
				mod, id = struct.unpack('4xii', data)
				self.model.preset.modules[mod].change_type(id)
				self.send_ev(model.ModuleType(mod))
				# typ_str = 'None' if id & 0xffff == 0xffff else models[id].name
				# print(f'changed module {mod:2}: type: {typ_str}')
				# await self.rx_preset()
				pass
			case 0x13:
				mod, en = struct.unpack('4xii', data)
				self.model.preset.modules[mod].en = en
				self.send_ev(model.ModuleOnOff(mod))
			case 0x14:
				mod, ts1 = struct.unpack('4xii', data)
				self.model.preset.modules[mod].tempo1 = ts1
				self.send_ev(model.ModuleTempo1(mod))
			case 0x16:
				typ, nr = struct.unpack('4x2i', data[:-4])
				assert typ in (0, 1)
				if typ:
					val, = self.model.preset.flt_params[nr], = struct.unpack('f', data[-4:])
				else:
					val, = self.model.preset.int_params[nr], = struct.unpack('i', data[-4:])
				print(f'param ({nr}) {params[nr][2]} changed: {val}')
			case 0x24:
				note, y, z, w = struct.unpack('ihbb', data)
				if note >= 0:
					octave, tone = divmod(note-1, len(semitones))
					note = f'{semitones[tone]}{octave+1}'
				off = (w & 0x3f) # idk
				# print(f'tuner {note:3} {off:3}', data.hex())
			case 0x27:
				pres, = struct.unpack('i', data)
				self.model.sel_preset = pres
				self.send_ev(model.PresetSel())
			case 0x29:
				# TODO store setlists (at least names)
				nr, name = struct.unpack('i16s', data)
				# print(f'setlist {nr} name: {name.decode()}')
			case 0x2d:
				ref, val, ev = self.knobmsg(data, model.KnobValue)
				ref.val = val
				self.send_ev(ev)
			case 0x2c:
				sl, = struct.unpack('i', data)
				self.model.sel_list = sl
				self.send_ev(model.ListSel())
			case 0x2e:
				ref, min, ev = self.knobmsg(data, model.KnobMin)
				ref.min = min
				self.send_ev(ev)
			case 0x2f:
				ref, max, ev = self.knobmsg(data, model.KnobMax)
				ref.max = max
				self.send_ev(ev)
			case 0x30:
				ref, ctrl, ev = self.knobmsg(data, model.KnobCtrl)
				assert isinstance(ctrl, int)
				ref.ctrl = ctrl
				self.send_ev(ev)
			case 0x31:
				mod, ts2 = struct.unpack('4xii', data)
				self.model.preset.modules[mod].tempo2 = ts2
				self.send_ev(model.ModuleTempo2(mod))
			case 0x32:
				mod, fs = struct.unpack('4xii', data)
				self.model.preset.modules[mod].fs = fs
				self.send_ev(model.ModuleFswitch(mod))
			case 0x33:
				print('DSP overload!!')
			# case 0x34: midi assignments
			# guess: 0x35 to query names
			case 0x36:
				rawname, = struct.unpack('4x16s16x', data)
				name = rawname.rstrip(b'\0 ').decode()
				self.model.preset.name = name
				self.send_ev(model.PresetName())
				# print(f'preset saved as {name}') # might implicitly switch active presets...
			case _:
				print('res' if is_resp else 'evt', hex(typ), data.hex())

	async def rx_preset(self, setlist: int = -1, preset: int = -1):
		await self.send_cmd(0x00, struct.pack('2h', preset, setlist))

	async def rx_setlist(self, setlist: int):
		await self.send_cmd(0x28, struct.pack('h2x', setlist))

	async def set_preset(self, setlist: int, preset: int, data: bytes):
		await self.send_cmd(0x02, struct.pack('2h', preset, setlist) + data)

	async def set_flt_param(self, param: int, val: float):
		await self.send_cmd(0x16, struct.pack('4xiif', 1, param, val))

	async def set_int_param(self, param: int, val: int):
		await self.send_cmd(0x16, struct.pack('4xiii', 0, param, val))
