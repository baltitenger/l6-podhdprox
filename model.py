import asyncio
from dataclasses import dataclass

from structs import PresetState

@dataclass(frozen=True, slots=True)
class Event: pass

@dataclass(frozen=True, slots=True)
class WholePreset(Event): pass

@dataclass(frozen=True, slots=True)
class ListSel(Event): pass

@dataclass(frozen=True, slots=True)
class PresetSel(Event): pass

@dataclass(frozen=True, slots=True)
class ListName(Event): pass

@dataclass(frozen=True, slots=True)
class PresetName(Event): pass

@dataclass(frozen=True, slots=True)
class ParamChangeInt(Event):
	nr: int

@dataclass(frozen=True, slots=True)
class ParamChangeFlt(Event):
	nr: int

@dataclass(frozen=True, slots=True)
class ModuleEvent(Event):
	mod_idx: int

@dataclass(frozen=True, slots=True)
class ModuleType(ModuleEvent): pass

@dataclass(frozen=True, slots=True)
class ModuleOnOff(ModuleEvent): pass

@dataclass(frozen=True, slots=True)
class ModuleTempo1(ModuleEvent): pass

@dataclass(frozen=True, slots=True)
class ModuleTempo2(ModuleEvent): pass

@dataclass(frozen=True, slots=True)
class ModuleFswitch(ModuleEvent): pass

@dataclass(frozen=True, slots=True)
class KnobEvent(ModuleEvent):
	knob_id: int

@dataclass(frozen=True, slots=True)
class KnobValue(KnobEvent): pass

@dataclass(frozen=True, slots=True)
class KnobMin(KnobEvent): pass

@dataclass(frozen=True, slots=True)
class KnobMax(KnobEvent): pass

@dataclass(frozen=True, slots=True)
class KnobCtrl(KnobEvent): pass

@dataclass(frozen=True, slots=True)
class Tuner(Event):
	note: int
	offset: int

# @dataclass(frozen=True, slots=True)
# class BaseEvent: pass
#
# type EventType = Literal['whole_preset', 'list_sel', 'preset_sel', 'list_name', 'preset_name']
# @dataclass(frozen=True, slots=True)
# class Event(BaseEvent):
# 	typ: EventType
#
# type ModuleEventType = Literal['on_off', 'tempo1', 'tempo2', 'fswitch']
# @dataclass(frozen=True, slots=True)
# class ModuleEvent(BaseEvent):
# 	typ: ModuleEventType
# 	mod_idx: int
#
# type KnobEventType = Literal['value', 'min', 'max', 'ctrl']
# @dataclass(frozen=True, slots=True)
# class KnobEvent(BaseEvent):
# 	typ: KnobEventType
# 	mod_idx: int
# 	knob_id: int

class EvListener:
	model: 'Model'
	async def on_ev(self, ev: Event): ...
	def send_ev(self, ev: Event):
		print(self, ev)
		for listener in self.model.listeners:
			if listener is not self:
				asyncio.create_task(listener.on_ev(ev))

class SetlistModel:
	name: str
	presets: list[PresetState | None]
	def __init__(self, name: str):
		self.name = name
		self.presets = [None] * 64

class Model:
	listeners: list[EvListener]
	sel_list: int
	sel_preset: int
	# current, in-memory preset
	preset: PresetState
	bank: list[SetlistModel | None]
	# TODO store / cache other presets?
	def __init__(self) -> None:
		self.listeners = []
		self.sel_list = 0
		self.sel_preset = 0
		self.bank = [None] * 8
