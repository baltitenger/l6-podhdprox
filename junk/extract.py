#!/usr/bin/env python3

from pprint import pp
import struct
import xml.sax

from data import AmpModInfo, Dropdown, KnobInfo, ModInfo

src = '/home/baltazar/Downloads/4/POD HD Pro X Edit'

class HexInt(int):
	def __repr__(self) -> str:
		return hex(self)

strings: dict[bytes, dict[bytes, str]] = {}
class reader(xml.sax.ContentHandler):
	def __init__(self) -> None:
		self.grp = {}
	def startElement(self, name: str, attrs) -> None:
		if name == 'L6StringGroup':
			self.grp = strings[attrs['ID'].encode()] = {}
		elif name == 'L6StringEntry':
			self.grp[attrs['ID'].encode()] = attrs['eng']
xml.sax.parse(f'{src}/res/PODX4Edit.lang', reader())

mdls = strings[b'MDLS']
prms = strings[b'PRMS']
menu = strings[b'MENU']

dropdowns: list[Dropdown] = [Dropdown(0, [])]
# from sub at 0x41d7a0
with open('dropdowns.txt', 'r') as f:
	for line in f:
		start, *opts = line.strip().split('|')
		start = int(start)
		dropdowns.append(Dropdown(start, [menu.get(x.encode(), x) for x in opts]))

models: dict[int, ModInfo] = {}

AMP_EXTRA_START = 6
amp_extra: list[dict[int, KnobInfo]] = []

amp_spec = {
	0x7006f: 1,
	0x70070: 2,
	0x70079: 3,
	0x7007a: 4,
	# manual additions:
	0x070083: 0,
	0x07006e: 5,
	0x070072: 5,
	0x070074: 5,
	0x070076: 5,
	0x070078: 5,
	0x07007c: 5,
	0x07007e: 5,
	0x070080: 5,
	0x070082: 5,
}

with open('/home/baltazar/Downloads/4/POD HD Pro X Edit/POD HD Pro X Edit.exe', 'rb') as f:
	# model extra params
	f.seek(0x00105844)
	for _ in range(5):
		temp: dict[int, KnobInfo] = {}
		for _ in range(5):
			key, id = struct.unpack('<4si', f.read(8))
			id = HexInt(id)
			if key != b'\0\0\0\0':
				name = prms[key[::-1]]
				if name == 'BRIGHT':
					temp[id] = KnobInfo(id, name, 15, 0) # on/off
				else:
					temp[id] = KnobInfo(id, name, 0, 1)
		amp_extra.append(temp)
	# manual addition
	amp_extra.append({
		HexInt(0x3f100008): KnobInfo(HexInt(0x3f100008), 'SAG', 0, 1),
		HexInt(0x3f100007): KnobInfo(HexInt(0x3f100007), 'HUM', 0, 1),
	})
	amp_extra.append({})
	pp(amp_extra)
	# input dropdowns
	f.seek(0x00118c80)
	# TODO variax stuff, midi ch, etc
	# models
	f.seek(0x00119a08)
	while True:
		str_id, id = struct.unpack('4si', f.read(8))
		id = HexInt(id)
		str_id: bytes = str_id[::-1]
		if str_id == b'\0\0\0\0':
			continue
		name = mdls.get(str_id)
		if name is None:
			break
		models[id] = ModInfo(id, name, -1, {}, [], [])
	# amps, cabs & mics
	f.seek(0x0011a190)
	for _ in range(132):
		buf = f.read(0x60)
		id1, id2, pack, key, idk5, img_idx, idk6, def_cab, def_mic = struct.unpack('<3i4sihhii', buf[:0x20])
		# guess: id2 is fallback id if pack is unavailable
		key = key[::-1]
		if key == b'\0\0\0\0':
			continue
		assert idk5 == 0
		# assert idk6 == 1
		name = mdls[key]
		idks1 = buf[0x20:0x3c]
		types = [ buf[i:i+4][::-1] for i in range(0x3c, 0x5c, 4) ]
		has_extra, = struct.unpack('<i', buf[0x5c:0x60])
		print(f'{id1:08x}: {name:22} {img_idx} {idk6} cab:{def_cab:8x} mic:{def_mic:x} {types} {has_extra}')
		if id1 & 0xffff0000 == 0x00070000:
			assert idks1 == bytes.fromhex('0000003f0000003f0000003f0000003f0000003f0000003fcdcccc3d')
			params = { HexInt(id): KnobInfo(HexInt(id), prms[types[j]], 0, 1) for id,j in zip(range(0x3f100000, 0x3f100006), [1, 2, 3, 0, 4, 5]) }
			extra = amp_extra[amp_spec.get(id1, 0 if has_extra else -1)]
			models[HexInt(id1)] = AmpModInfo(HexInt(id1), name, img_idx, params | extra, [], [], def_cab, def_mic)
		else:
			assert idks1 in (
					bytes.fromhex('0000003f0000003f0000003f0000003f000000000000000000000000'),
					bytes.fromhex('00000000000000000000000000000000000000000000000000000000'),
					)
			models[HexInt(id1)] = ModInfo(HexInt(id1), name, img_idx, {}, [], [])

	# also seems to have 2 full presets, both called New Tone

	# data in 0x520f60 is supposed to have the presets, but it's filled by a fn at 0x4ca440

#print(stuff)


with open('dump', 'rb') as f:
	f.seek(0x00444f60)
	while True:
		# buf = f.read(0x31c)
		head = f.read(0x50)
		id, x, y, z = struct.unpack('<4i', head[:16])
		if id & 0xffff == 0xffff:
			break
		model = models[id]
		model.img_idx, = struct.unpack('<h', head[56:58])
		w, = struct.unpack('<i', head[0x4c:0x50])
		print(f'{model.name} {model.img_idx} {model.id:08x}')
		# print(head.hex())
		t1 = t2 = 0
		for i in range(6):
			# knobs
			buf = f.read(0x4c)
			idk = struct.unpack('15i4s3i', buf)
			pkey = idk[15][::-1]
			if pkey == b'\0\0\0\0':
				continue
			t1 += 1
			# 2,3: zero
			# 4: type
			#   - 1: float [0,1] -> [0%,100%]
			#   - 5:             -> [-12dB,12dB]
			#   - 6:             -> [-11dB,11dB]
			#   - 7:             -> [-18dB,18dB]
			#   - 8:             -> [-96dB,0dB]
			#   - 9:             -> [-80dB,0dB]
			#   - 10:            -> [0dB,24dB]
			#   - 13:            -> [0.1Hz,20Hz]
			#   - 14:            -> [0.1Hz,15Hz]
			#   - 15:            -> [0Hz,3520Hz]
			#   - 16:            -> [20ms,2000ms]
			#   - 17:            -> [0ms,200ms]
			#   - 18:            -> [0ms,800ms]
			#   - 19:            -> [0ms,4000ms]
			#   - 20:            -> [-24,+24]
			#   - 22:            -> [100%L,100%R]
			#   - 26:            -> [20Hz,500Hz]
			#   - 27:            -> [5kHz,20kHz]
			# 5,6,7: knob x,y,?
			# 8,9,10: text input box x,y,visible
			# 11,12,13,14,15: label x,y,w,h,text
			# 16,17,18: bracket x,y,?
			model.knobs[HexInt(idk[0])] = KnobInfo(HexInt(idk[0]), prms[pkey], 0, idk[4])
			print('- {0:08x} {1} {4:2} {20}'.format(*idk, pkey, prms[pkey]))
		for i in range(5):
			# dropdowns
			buf = f.read(0x34)
			idk = struct.unpack('i11i4s', buf)
			pkey = idk[12][::-1]
			if pkey == b'\0\0\0\0':
				continue
			t2 += 1
			# 5: dropdown nr
			# 6,7,8: dropdown x,y,?
			# 9,10,11,12,13: label x,y,w,h,text
			p = KnobInfo(HexInt(idk[0]), prms[pkey], idk[4], 0)
			if idk[0] & 0xffff0000 == 0x3f200000:
				model.tempo.append(p)
			else:
				model.knobs[HexInt(idk[0])] = p
			print('- {0:08x} {1:x} {2} {3} {4} {5:2} {14}'.format(*idk, pkey, prms[pkey]))
			# print('-', buf.hex(), prms[pkey])
		print('xxx', len(model.knobs), y, z, w, model.name)
		# print(head.hex(), t1, t2, t1+t2)

# cab params:
# 00135c40: 4700 0000 0c00 0000 3e00 0000 2a00 0000 4752 5444 0000 0000 4200 0100  G.......>...*...GRTD....B...
# 00135c5c: 7e00 0000 0c00 0000 7500 0000 2a00 0000 524c 5444 0100 0000 4200 0100  ~.......u...*...RLTD....B...
# 00135c78: b400 0000 0c00 0000 ac00 0000 2a00 0000 534c 5444 0200 0000 4200 0100  ............*...SLTD....B...
# 00135c94: eb00 0000 0c00 0000 e100 0000 2a00 0000 3443 5444 0300 0000 4200 0100  ............*...4CTD....B...

# exit(0)

def chunk_bytes(buf: bytes, n: int, start = 0, maxc = None):
	stop = len(buf) if maxc is None else start + n*maxc
	return (buf[i:i+n] for i in range(start, stop, n))

def set_defs(data: bytes):
	mod_id, = struct.unpack('i', data[:4])
	if mod_id & 0xffff == 0xffff:
		return
	n_knobs = data[0xf]
	models[mod_id].defs = list(chunk_bytes(data, 20, 0x10, n_knobs))

with open('defaults.bin', 'rb') as f:
	while data := f.read(0x1000):
		set_defs(data[0x028:0x128])
		set_defs(data[0x428:0x528])

imgs = { mod.img_idx for mod in models.values() } - {0}
with open('app.qrc', 'w') as f:
	f.write('<RCC><qresource prefix="/" compression-algorithm="none">\n')
	for i in imgs:
		f.write(f'<file>img/{i:03}.png</file>\n')
	f.write('</qresource></RCC>\n')

with open('data_gen.py', 'w') as f:
	f.write('from data import AmpModInfo, Dropdown, KnobInfo, ModInfo\n')
	f.write('\ndropdowns: list[Dropdown] = ')
	pp(dropdowns, f)
	f.write('\nmodels: dict[int, ModInfo] = ')
	pp(models, f, width=100)
	f.write('\ntempo_sync = dropdowns[4]\n')
