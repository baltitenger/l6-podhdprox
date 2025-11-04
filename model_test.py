from structs import LEStruct, PresetState
from pxio import parse_pxb

def test_blank_pres():
	pres = PresetState()
	mods = pres.modules[4:]
	assert pres.lanes == [[4, 5, 6, 7], [], [], [], [], [8, 9, 10, 11]]
	assert [ mod.pos for mod in mods ] == [0x5000000, 0x5000001, 0x5000002, 0x5000003, 0x5050004, 0x5050005, 0x5050006, 0x5050007]

def test_lane2pos():
	pres = PresetState()
	mods = pres.modules[4:]
	pres.lanes = [[5], [4, 11], [7], [6, 9], [10], [8]]
	pres.lane2pos()
	print([ hex(mod.pos) for mod in mods ])
	assert [ mod.pos for mod in mods ] == [0x5010001, 0x5000000, 0x5030004, 0x5020003, 0x5050007, 0x5030005, 0x5040006, 0x5010002]

def test_pxio_vs_usb_parse():
	usb_pres = PresetState()
	with (
			open('junk/reset.pxb',   'rb') as pxb,
			open('junk/presets.bin', 'rb') as usb):
		pxb_it = (pres for name, sl in parse_pxb(pxb) for pres in sl)
		for i, pxb_pres in enumerate(pxb_it):
			usb_pres.load(usb.read(0x1000), LEStruct)
			assert usb_pres == pxb_pres, i
