from asyncio import sleep

from usb1 import USBDeviceHandle

from data import semitones
import model
from structs import no_mod
from usb_transport import UsbTransport, struct

cmd2evt: dict[int, type[model.Event]] = {
	0x2d: model.KnobValue,
	0x2e: model.KnobMin,
	0x2f: model.KnobMax,
	0x30: model.KnobCtrl,

	0x11: model.ModuleType,
	0x13: model.ModuleOnOff,
	0x14: model.ModuleTempo1,
	0x31: model.ModuleTempo2,
	0x32: model.ModuleFswitch,
}

evt2cmd = { v: k for k, v in cmd2evt.items() }

class UsbAdapter(UsbTransport, model.EvListener):
	def __init__(self, hdl: USBDeviceHandle, model: model.Model) -> None:
		super().__init__(hdl)
		model.listeners.append(self)
		self.model = model
		self.ready = False

	async def on_ev(self, ev: model.Event):
		preset = self.model.preset
		match ev:
			case model.Startup():
				while not self.ready:
					await self.send_cmd(0x21, struct.pack('i', 0))
					await sleep(0.1)
				await self.send_cmd(0x21, struct.pack('i', 9)) # get selected list
				await self.send_cmd(0x21, struct.pack('i', 8)) # get selected preset
				await self.send_cmd(0x00, struct.pack('2h', -1, -1)) # get active preset
				# get setlist names
				for i in range(8):
					await self.send_cmd(0x28, struct.pack('h2x', i))
				# TODO get all presets?
			case model.WholePreset():
				await self.send_cmd(0x02, struct.pack('2h', -1, -1) + self.model.preset.dump(struct))
			case model.ListSel():
				await self.send_cmd(0x2c, struct.pack('i', self.model.sel_list))
				await self.send_cmd(0x20, struct.pack('3i', 0, 9, self.model.sel_list))
			case model.PresetSel():
				await self.send_cmd(0x27, struct.pack('i', self.model.sel_preset))
				await self.send_cmd(0x20, struct.pack('3i', 0, 8, self.model.sel_preset))
			case model.ListName(nr):
				await self.send_cmd(0x2a, struct.pack('i16s', nr, self.model.bank[nr].name.encode()))
			case model.ParamChangeInt(nr):
				arg = self.model.preset.int_params[nr]
				await self.send_cmd(0x16, struct.pack('4x2ii', 0, nr, arg))
			case model.ParamChangeFlt(nr):
				arg = self.model.preset.flt_params[nr]
				await self.send_cmd(0x16, struct.pack('4x2if', 0, nr, arg))
			case model.KnobEvent(mod_idx, knob_id):
				knob = preset.modules[mod_idx].knobs[knob_id]
				match ev:
					case model.KnobValue(): arg = knob.val
					case model.KnobMin():   arg = knob.min
					case model.KnobMax():   arg = knob.max
					case model.KnobCtrl():  arg = knob.ctrl
					case _: assert False, 'messed up'
				fmt = int(isinstance(arg, float))
				mod_idx = {1: 2, 2: 1}.get(mod_idx, mod_idx)
				await self.send_cmd(evt2cmd[type(ev)], struct.pack('4x3i'+'if'[fmt], mod_idx, fmt, ev.knob_id, arg))
			case model.ModuleEvent(mod_idx):
				module = preset.modules[mod_idx]
				match ev:
					case model.ModuleType():    arg = module.model_id
					case model.ModuleOnOff():   arg = module.en
					case model.ModuleTempo1():  arg = module.tempo1
					case model.ModuleTempo2():  arg = module.tempo2
					case model.ModuleFswitch(): arg = module.fs
					case _: assert False, 'messed up'
				mod_idx = {1: 2, 2: 1}.get(mod_idx, mod_idx)
				await self.send_cmd(evt2cmd[type(ev)], struct.pack('4x2i', mod_idx, arg))

	async def on_pkt(self, is_resp: int, cmd: int, data: bytes):
		mod_idx: int
		knob_id: int

		evt = cmd2evt.get(cmd, model.Event)

		if issubclass(evt, model.KnobEvent):
			mod_idx, fmt, knob_id = struct.unpack('4x3i', data[:-4])
			mod_idx = {1: 2, 2: 1}.get(mod_idx, mod_idx)
			assert fmt in (0, 1)
			arg, = struct.unpack('if'[fmt], data[-4:])
			mod = self.model.preset.modules[mod_idx]
			if mod.info is no_mod:
				return
			knob = mod.knobs[knob_id]
			match evt:
				case model.KnobValue: knob.val  = arg
				case model.KnobMin:   knob.min  = arg
				case model.KnobMax:   knob.max  = arg
				case model.KnobCtrl:  knob.ctrl = arg
			self.send_ev(evt(mod_idx, knob_id))
			return

		if issubclass(evt, model.ModuleEvent):
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
			return

		match cmd:
			case 0x01:
				self.model.preset.load(data, struct)
				# TODO check if it's the current one
				self.send_ev(model.WholePreset())
			case 0x03:
				# set preset ack, data is always i(0)
				pass
			case 0x16:
				typ, nr = struct.unpack('4x2i', data[:-4])
				assert typ in (0, 1)
				if typ:
					val, = self.model.preset.flt_params[nr], = struct.unpack('f', data[-4:])
					self.send_ev(model.ParamChangeFlt(nr))
				else:
					val, = self.model.preset.int_params[nr], = struct.unpack('i', data[-4:])
					self.send_ev(model.ParamChangeInt(nr))
				# print(f'param ({nr}) {params[nr][2]} changed: {val}')
			case 0x22:
				nr, val = struct.unpack('4xii', data)
				if nr == 0:
					# not sure what this actually is but good enough for this purpose
					self.ready = True
				elif nr == 9:
					self.model.sel_list = val
					self.send_ev(model.ListSel())
				elif nr == 8:
					self.model.sel_preset = val
					self.send_ev(model.PresetSel())
				else:
					print(f'thing {nr}: {val}')
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
				nr, name = struct.unpack('i16s', data)
				self.model.bank[nr].name = name.decode().rstrip()
				self.send_ev(model.ListName(nr))
			case 0x2b:
				# setlist name change ack, body is i(0)
				pass
			case 0x2c:
				sl, = struct.unpack('i', data)
				self.model.sel_list = sl
				self.send_ev(model.ListSel())
			case 0x33:
				self.send_ev(model.DspOvl())
			# case 0x34: midi assignments
			# guess: 0x35 to query names
			case 0x36:
				rawname, = struct.unpack('4x16s16x', data)
				name = rawname.rstrip(b'\0 ').decode()
				self.model.preset.name = name
				self.send_ev(model.PresetName())
				# print(f'preset saved as {name}') # might implicitly switch active presets...
			case 0x23:
				# no data, sent after changing preset / list
				pass
			case _:
				print('res' if is_resp else 'evt', hex(cmd), data.hex())
