from io import BufferedReader, BufferedWriter
from typing import Iterable

from structs import BEStruct, PresetState, Setlist

ver = bytes.fromhex('0000 0001')
magics = (
	bytes.fromhex('0014 0006 0262 0000'),
	bytes.fromhex('0227 0000'),
	bytes.fromhex('7d01 002e'),
)
padlen = 0x10

def parse_pxe(rd: BufferedReader) -> PresetState:
	magic, = BEStruct.unpack('4s36x', rd.read(0x28))
	assert magic == b'H5EP'
	return PresetState().load(rd.read(0x1000), BEStruct)

def parse_pxs(rd: BufferedReader) -> Setlist:
	magic, rawname = BEStruct.unpack('4s36x16s', rd.read(0x38))
	assert magic == b'H5ES'
	name = rawname.rstrip(b'\0 ').decode()
	return Setlist(name, [parse_pxe(rd) for _ in range(64)])

def parse_pxb(rd: BufferedReader) -> list[Setlist]:
	magic, = BEStruct.unpack('4s36x', rd.read(0x28))
	assert magic == b'H5EB'
	return [parse_pxs(rd) for _ in range(8)]

def parse_any_px(rd: BufferedReader) -> PresetState | Setlist | list[Setlist]:
	magic = rd.peek(4)[:4]
	if magic == b'H5EP':
		return parse_pxe(rd)
	elif magic == b'H5ES':
		return parse_pxs(rd)
	elif magic == b'H5EB':
		return parse_pxb(rd)
	else:
		assert False, 'Unknown file magic'

def write_pxe(wr: BufferedWriter, p: PresetState):
	wr.write(b'H5EP' + ver + b''.join(reversed(magics)) + bytes(padlen))
	wr.write(p.dump(BEStruct))

def write_pxs(wr: BufferedWriter, sl: Setlist):
	wr.write(b'H5ES' + ver + b''.join(magics) + bytes(padlen) + BEStruct.pack('16s', sl.name.encode()))
	for p in sl.presets:
		write_pxe(wr, p)

def write_pxb(wr: BufferedWriter, b: Iterable[Setlist]):
	wr.write(b'H5EB' + ver + b''.join(magics) + bytes(padlen))
	for sl in b:
		write_pxs(wr, sl)
