from data_gen import models
from pxio import parse_pxb
from structs import LEStruct, ModState, PresetState, no_mod

def test_blank_pres():
	pres = PresetState()
	mods = pres.modules[4:]
	assert pres.lanes == [[4, 5, 6, 7], [], [], [], [], [8, 9, 10, 11]]
	assert [ mod.pos for mod in mods ] == [0x5000000, 0x5000001, 0x5000002, 0x5000003, 0x5050004, 0x5050005, 0x5050006, 0x5050007]
	assert all(mod.info is no_mod for mod in mods)

def test_lane2pos():
	pres = PresetState()
	mods = pres.modules[4:]
	pres.lanes = [[5], [4, 11], [7], [6, 9], [10], [8]]
	pres.lane2pos()
	assert [ mod.pos for mod in mods ] == [0x5010001, 0x5000000, 0x5030004, 0x5020003, 0x5050007, 0x5030005, 0x5040006, 0x5010002]

def test_move_mod():
	pres = PresetState()
	pres.move_mod(6, 0, 1)
	assert pres.lanes == [[4, 6, 5, 7], [], [], [], [], [8, 9, 10, 11]]
	pres.move_mod(9, 5, 4)
	assert pres.lanes == [[4, 6, 5, 7], [], [], [], [], [8, 10, 11, 9]]
	pres.move_mod(7, 2, 0)
	assert pres.lanes == [[4, 6, 5], [], [7], [], [], [8, 10, 11, 9]]

def test_move_amp():
	pres = PresetState()
	assert pres.amp_pos() == 5
	pres.lanes = [[5], [4, 11], [7], [6, 9], [10], [8]]
	pres.move_mod(0, 5, 0)
	assert pres.amp_pos() == 7
	pres.move_mod(0, 1, 1)
	assert pres.amp_pos() == 0
	assert pres.lanes == [[5], [4], [7], [11, 6, 9], [10], [8]]
	pres.move_mod(1, 2, 0)
	assert pres.amp_pos() == 0
	assert pres.lanes == [[5], [4], [], [11, 6, 9], [7, 10], [8]]

def test_pxio_vs_usb_parse():
	usb_pres = PresetState()
	with (
			open('junk/reset.pxb',   'rb') as pxb,
			open('junk/presets.bin', 'rb') as usb):
		pxb_it = (pres for sl in parse_pxb(pxb) for pres in sl.presets)
		for i, pxb_pres in enumerate(pxb_it):
			usb_pres.load(usb.read(0x1000), LEStruct)
			assert usb_pres == pxb_pres, i

def test_wire_roundtrip():
	pres = PresetState()
	pres.name = 'foo'
	pres.modules[0].change_type(0x7000b)
	pres.modules[1].change_type(0x70071)
	pres.modules[4].change_type(0x20a0012)
	pres.modules[5].change_type(0x200000b)
	pres.modules[6].change_type(0x20c000b)
	pres.modules[7].change_type(0x2040020)
	assert pres == PresetState().load(pres.dump(LEStruct), LEStruct)

def test_wire_roundtrip_all():
	pres = PresetState()
	for mi in models.keys():
		if mi >> 16 == 0x07:
			mod = pres.modules[0]
			mod.change_type(mi)
			assert mod == ModState(pres, 0).load(mod.dump(LEStruct), LEStruct)
		elif mi >> 24 == 0x02:
			mod = pres.modules[4]
			mod.change_type(mi)
			assert mod == ModState(pres, 4).load(mod.dump(LEStruct), LEStruct)
