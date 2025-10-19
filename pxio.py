from io import BufferedReader
from typing import Iterable

from structs import BEStruct, PresetState

def parse_pxe(rd: BufferedReader) -> PresetState:
	magic, = BEStruct.unpack('4s36x', rd.read(0x28))
	assert magic == b'H5EP'
	return PresetState(rd.read(0x1000), BEStruct)

type Setlist = tuple[str, Iterable[PresetState]]
def parse_pxs(rd: BufferedReader) -> Setlist:
	magic, name = BEStruct.unpack('4s36x16s', rd.read(0x38))
	assert magic == b'H5ES'
	return name, (parse_pxe(rd) for _ in range(64))

def parse_pxb(rd: BufferedReader) -> Iterable[Setlist]:
	magic, = BEStruct.unpack('4s36x', rd.read(0x28))
	assert magic == b'H5EB'
	return (parse_pxs(rd) for _ in range(8))

# TODO serialization
