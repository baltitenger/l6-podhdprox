import asyncio
from typing import cast

from usb1 import USBDeviceHandle

import model
from realdata import models, semitones
from structs import KnobState, PresetState, params
from usb_transport import Transport, struct

cmd2evt: dict[int, type[model.Event]] = {
	0x2d: model.KnobValue,
	0x2e: model.KnobMin,
	0x2f: model.KnobMax,
	0x30: model.KnobMax,

	0x11: model.ModuleType,
	0x13: model.ModuleOnOff,
	0x14: model.ModuleTempo1,
	0x31: model.ModuleTempo2,
	0x32: model.ModuleFswitch,
}

evt2cmd = { v: k for k, v in cmd2evt.items() }

class UsbAdapter(Transport, model.EvListener):
	def __init__(self, hdl: USBDeviceHandle, model: model.Model) -> None:
		super().__init__(hdl)
		model.listeners.append(self)
		self.model = model

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
			case model.ParamChangeInt(nr):
				arg = self.model.preset.int_params[nr]
				await self.send_cmd(0x16, struct.pack('4x2ii', 0, nr, arg))
			case model.ParamChangeFlt(nr):
				arg = self.model.preset.flt_params[nr]
				await self.send_cmd(0x16, struct.pack('4x2if', 0, nr, arg))
			case model.KnobEvent(mod, knob_id):
				knob = preset.modules[mod].knobs[knob_id]
				match ev:
					case model.KnobValue(): arg = knob.val
					case model.KnobMin():   arg = knob.min
					case model.KnobMax():   arg = knob.max
					case model.KnobCtrl():  arg = knob.ctrl
					case _: assert False, 'messed up'
				fmt = int(isinstance(arg, float))
				await self.send_cmd(evt2cmd[type(ev)], struct.pack('4x3i'+'if'[fmt], ev.mod_idx, fmt, ev.knob_id, arg))
			case model.ModuleEvent(mod):
				module = preset.modules[mod]
				match ev:
					case model.ModuleType():    arg = module.model_id
					case model.ModuleOnOff():   arg = module.en
					case model.ModuleTempo1():  arg = module.tempo1
					case model.ModuleTempo2():  arg = module.tempo2
					case model.ModuleFswitch(): arg = module.fs
					case _: assert False, 'messed up'
				await self.send_cmd(evt2cmd[type(ev)], struct.pack('4x2i', mod, arg))

	async def on_pkt(self, is_resp: int, cmd: int, data: bytes):
		mod_idx: int
		knob_id: int

		evt = cmd2evt.get(cmd, cmd)

		match evt:
			case model.KnobEvent:
				mod_idx, fmt, knob_id = struct.unpack('4x3i', data[:-4])
				knob = self.model.preset.modules[mod_idx].knobs[knob_id]
				assert fmt in (0, 1)
				arg, = struct.unpack('if'[fmt], data[-4:])
				match evt:
					case model.KnobValue: knob.val  = arg
					case model.KnobMin:   knob.min  = arg
					case model.KnobMax:   knob.max  = arg
					case model.KnobCtrl:  knob.ctrl = arg
				self.send_ev(evt(mod_idx, knob_id))
			case model.ModuleEvent:
				mod_idx, arg = struct.unpack('4x2i', data)
				mod_idx = {1: 2, 2: 1}.get(mod_idx, mod_idx)
				mod = self.model.preset.modules[mod_idx]
				match evt:
					case model.ModuleType:    mod.change_type(arg)
					case model.ModuleOnOff:   mod.en     = arg
					case model.ModuleTempo1:  mod.tempo1 = arg
					case model.ModuleTempo2:  mod.tempo2 = arg
					case model.ModuleFswitch: mod.fs     = arg
				self.send_ev(evt(mod_idx))
			case 0x01:
				mod_idx, arg = struct.unpack('4x2i', data)
				mod_idx = {1: 2, 2: 1}.get(mod_idx, mod_idx)
				mod = self.model.preset.modules[mod_idx]
				self.model.preset = PresetState(data, struct)
				# TODO check if it's the current one
				self.send_ev(model.WholePreset())
			case 0x03:
				print('set preset ack: ', data.hex())
			case 0x16:
				typ, nr = struct.unpack('4x2i', data[:-4])
				assert typ in (0, 1)
				if typ:
					val, = self.model.preset.flt_params[nr], = struct.unpack('f', data[-4:])
					self.send_ev(model.ParamChangeFlt(nr))
				else:
					val, = self.model.preset.int_params[nr], = struct.unpack('i', data[-4:])
					self.send_ev(model.ParamChangeInt(nr))
				print(f'param ({nr}) {params[nr][2]} changed: {val}')
			case 0x24:
				note, y, z, w = struct.unpack('ihbb', data)
				if note >= 0:
					octave, tone = divmod(note-1, len(semitones))
					note = f'{semitones[tone]}{octave+1}'
				off = (w & 0x3f) # idk
				print(f'tuner {note:3} {off:3}', data.hex())
			case 0x27:
				pres, = struct.unpack('i', data)
				self.model.sel_preset = pres
				self.send_ev(model.PresetSel())
			case 0x29:
				# TODO store setlists (at least names)
				nr, name = struct.unpack('i16s', data)
				# print(f'setlist {nr} name: {name.decode()}')
			case 0x2c:
				sl, = struct.unpack('i', data)
				self.model.sel_list = sl
				self.send_ev(model.ListSel())
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
				print('res' if is_resp else 'evt', hex(cmd), data.hex())

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
