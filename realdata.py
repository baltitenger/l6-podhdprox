from dataclasses import dataclass

from data import AmpModel, Model, Param, dropdowns, models

params = {
	0x00: (0, 3368, 'variax ??'),
	0x01: (0, 3369, 'variax ??'),
	0x02: (0, 3370, 'variax ??'),
	0x03: (0, 3371, 'variax ??'),
	0x04: (0, 3372, 'variax ??'),
	0x05: (0, 3373, 'variax ??'),
	0x06: (0, 3374, 'variax ??'),
	0x07: (0, 3375, 'variax ??'),
	0x08: (0, 3376, 'variax ??'),
	0x09: (0, 3377, 'variax ??'),
	0x0a: (0, 3378, 'variax ??'),
	0x0b: (0, 3379, 'variax ??'),
	0x0c: (0, 3380, 'variax ??'),
	0x0d: (0, 3381, 'variax ??'),
	0x0e: (0, 3382, 'variax ??'),
	0x0f: (0, 3383, 'variax ??'),
	0x10: (0, 3384, 'variax ??'),
	0x11: (0, 3385, 'variax ??'),
	0x12: (0, 3386, 'variax ??'),
	0x13: (0, 3387, 'variax ??'),
	0x14: (0, 3388, 'variax ??'),
	0x15: (0, 3389, 'variax ??'),
	0x56: (0, 3390, 'variax ??'),
	0x5f: (0, 3391, 'variax ??'),
	0x61: (0, 3392, 'variax ??'),
	0x62: (0, 3393, 'variax ??'),
	0x63: (0, 3394, 'variax ??'),
	0x64: (0, 3395, 'variax ??'),
	0x65: (0, 3396, 'variax ??'),
	0x66: (0, 3397, 'variax ??'),
	0x60: (0, 3398, 'variax ??'),

	0x17: (1, 3416, 'tempo'), # 30-240 bpm
	0x26: (0, 3116, 'DT A topology '), # [0-4]
	0x27: (0, 3118, 'DT A mode'), # triode -> 0, pentode -> 0x7f
	0x28: (0, 3117, 'DT A class'), # A -> 0, A/B -> 0x7f
	0x29: (0, 3124, 'DT B topology '), # [0-4]
	0x2a: (0, 3126, 'DT B mode'), # triode -> 0, pentode -> 0x7f
	0x2b: (0, 3125, 'DT B class'), # A -> 0, A/B -> 0x7f
	# next 4 are stored in 2 offsets, cur, cur+16
	0x2c: (1, 3428, 'Mix A level'), # can also cause 4090 to change
	0x2d: (1, 3432, 'Mix B level'), # can also cause 4090 to change
	0x2e: (1, 3420, 'Mix A pan'),
	0x2f: (1, 3424, 'Mix B pan'),
	0x30: (1, 3452, 'Cab A bypass vol?'),
	0x31: (1, 3456, 'Cab B bypass vol?'),
	0x32: (1, 3404, 'Cab A E.R.'),
	0x33: (1, 3412, 'Cab B E.R.'),
	0x34: (0, 4088, 'Cab A Mic'),
	0x35: (0, 4089, 'Cab B Mic'),
	0x36: (0, 4094, 'Input 1 src'),
	0x37: (0, 4095, 'Input 2 src'),
	0x38: (0, 4083, 'Trails'),
	0x39: (0, 3112, 'l6 link amp 1 audio'),
	0x3a: (0, 3113, 'l6 link amp 2 audio'),
	0x3b: (0, 3114, 'l6 link amp 3 audio'),
	0x3c: (0, 3115, 'l6 link amp 4 audio'),

	0x3d: (0, 3132, '??'),
	0x3e: (0, 3133, '??'),
	0x3f: (0, 3134, '??'),
	0x40: (0, 3135, '??'),
	0x41: (0, 3136, '??'),
	0x42: (0, 3137, '??'),
	0x43: (0, 3138, 'l6 link amp 1 ctrl'),
	0x44: (0, 3139, 'l6 link amp 2 ctrl'),
	0x45: (0, 3140, 'l6 link amp 3 ctrl'),
	0x46: (0, 3141, 'l6 link amp 4 ctrl'),
	0x47: (0, 3142, 'l6 link amp 1 ctrl'), # duplicate values??
	0x48: (0, 3143, 'l6 link amp 2 ctrl'),
	0x49: (0, 3144, 'l6 link amp 3 ctrl'),
	0x4a: (0, 3145, 'l6 link amp 4 ctrl'),
	0x4b: (0, 3119, '??'),
	0x4c: (0, 3120, '??'),
	0x4d: (0, 3121, '??'),
	0x4e: (0, 3122, '??'),
	0x4f: (0, 3123, '??'),
	0x50: (0, 3127, '??'),
	0x51: (0, 3128, '??'),
	0x52: (0, 3129, '??'),
	0x53: (0, 3130, '??'),
	0x54: (0, 3131, '??'),

	0x55: (0, 3538, 'Guitar in-z'),

	0x57: (1, 572, 'Cab A low cut'),
	0x58: (1, 828, 'Cab B low cut'),
	0x59: (1, 592, 'Cab A res level'),
	0x5a: (1, 848, 'Cab B res level'),
	0x5b: (1, 612, 'Cab A thump'),
	0x5c: (1, 868, 'Cab B thump'),
	0x5d: (1, 632, 'Cab A decay'),
	0x5e: (1, 888, 'Cab B decay'),
}

semitones = 'C C♯ D E♭ E F F♯ G G♯ A B♭ B'.split()

categories: dict[int, str] = {
	0:  'Dynamics',
	5:  'Distortion',
	3:  'Modulation',
	10: 'Filter',
	9:  'Pitch',
	12: 'Preamp+EQ',
	2:  'Delay',
	4:  'Reverb',
	7:  'Vol/Pan',
	6:  'Wah',
	8:  'FX loop',
	13: '[disabled]',
}

def fmt_fs(fs: int):
	if fs == 0:
		return 'None'
	elif fs == 9:
		return 'Exp toe switch'
	return f"FS{fs}"

tempo_sync = dropdowns[4]

mod_names = [
	'Amp A',
	'Cab A',
	'Amp B',
	'Cab B',
	'Mod 1',
	'Mod 2',
	'Mod 3',
	'Mod 4',
	'Mod 5',
	'Mod 6',
	'Mod 7',
	'Mod 8',
]

ctrl_names = [
	'Off',
	'Exp 1',
	'Exp 2',
	'Variax vol',
	'Variax tone',
]

pos_map = {
	0: 'Pre',
	1: 'A',
	2: 'B',
	3: 'A Post',
	4: 'B Post',
	5: 'Post',
	7: 'Amp A',
	8: 'Amp B',
}

@dataclass
class Range:
	lo: float
	hi: float
	unit: str

	def fmt(self, val: float):
		res = val * (self.hi - self.lo) + self.lo
		return f'{res:.4g}{self.unit}'

ranges: dict[int, Range] = {
	1:  Range(0,    100,  '%'),
	4:  Range(1,    1,    ''), # 30-240
	5:  Range(-12,  12,   'dB'),
	6:  Range(-11,  11,   'dB'),
	7:  Range(-18,  18,   'dB'),
	8:  Range(-96,  0,    'dB'),
	9:  Range(-80,  0,    'dB'),
	10: Range(0,    24,   'dB'),
	11: Range(75,   1400, 'Hz'),
	13: Range(0.100000001,  15,   'Hz'),
	14: Range(0.100000001,  15,   'Hz'),
	15: Range(0,    3520, 'Hz'),
	16: Range(20,   2000, 'ms'),
	17: Range(0,    200,  'ms'),
	18: Range(0,    800,  'ms'),
	19: Range(0,    4000, 'ms'),
	20: Range(-24,  +24,  ''), # %+ (signed+)
	21: Range(0,    100,  '%'), # input is -1..+1, %L / %R
	22: Range(-100, +100, '%'), # input is 0..+1, %L / %R
	23: Range(0,    1,    ''), # input is 0..11 -> tone: dropdown nr 1
	24: Range(0,    1,    ''), # input is 0..7 -> scale: dropdown nr 2
	25: Range(0,    1,    ''), # input is -8..+8 -> dropdown nr 3
	26: Range(20,   500,  'Hz'),
	27: Range(5,    20,   'kHz'), # 0 -> off
}

controller_map = [ 'Off', 'Exp 1', 'Exp 2', 'Variax Vol', 'Variax Tone' ]

