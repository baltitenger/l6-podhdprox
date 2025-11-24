from __future__ import annotations
import asyncio
from typing import cast

from usb1 import TRANSFER_COMPLETED, USBDeviceHandle, USBTransfer

from structs import LEStruct
from util import chunk_bytes, make_callback

struct = LEStruct

class Transport:
	def __init__(self, hdl: USBDeviceHandle) -> None:
		hdl.claimInterface(1)

		self.in_xfer = hdl.getTransfer()
		self.in_xfer.setBulk(0x81, 0x100, make_callback(self.on_recv))

		self.out_xfer = hdl.getTransfer()
		self.out_max_size = hdl.getDevice().getMaxPacketSize(0x01)
		self.out_xfer.setBulk(0x01, self.out_max_size, make_callback(self.on_send))

		self.send_lk = asyncio.Lock()

	async def on_recv(self, xfer: USBTransfer):
		fut = cast(asyncio.Future[bytes], xfer.getUserData())
		if xfer.getStatus() != TRANSFER_COMPLETED:
			fut.set_exception(ValueError('USB recv error', xfer.getStatus()))
		else:
			buf = cast(bytearray, xfer.getBuffer())
			fut.set_result(bytes(buf[:xfer.getActualLength()]))

	async def rx0(self):
		fut: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()
		self.in_xfer.setUserData(fut)
		self.in_xfer.submit()
		return await fut

	async def rx1(self) -> tuple[int, bytes]:
		chunk = await self.rx0()
		len1, x, flags, y = struct.unpack('4b', chunk[:4])
		assert x == 0 and y == 0, 'weird header1'
		data = chunk[4:]
		while len(data) < len1:
			data += await self.rx0()
		assert len(data) == len1
		return flags, data

	async def rx2(self):
		flag1, chunk1 = await self.rx1()
		assert flag1 == 1, 'expected start of packet'
		len2, magic = struct.unpack('2h', chunk1[:4])
		assert magic == 0x090a
		len2 *= 4
		data = chunk1[4:]
		while len(data) < len2:
			flag2, chunk2 = await self.rx1()
			assert flag2 == 4, 'expected continuation packet'
			data += chunk2
		assert len(data) == len2
		return data

	async def rx_loop(self):
		while True:
			try:
				pkt = await self.rx2()
				is_resp, x, y, typ = struct.unpack('4b', pkt[:4])
				data = pkt[4:]
				assert x == 0x40 and y == 0x00, 'weird header3'
			except AssertionError as e:
				print('Ignoring malformed usb message:', e)
				continue
			await self.on_pkt(is_resp, typ, data)

	async def on_pkt(self, is_resp: int, cmd: int, data: bytes): ...

	async def on_send(self, xfer: USBTransfer):
		fut = cast(asyncio.Future[None], xfer.getUserData())
		if xfer.getStatus() != TRANSFER_COMPLETED:
			fut.set_exception(ValueError('USB send error', xfer.getStatus()))
		else:
			fut.set_result(None)

	async def tx0(self, data: bytes):
		self.fut = asyncio.get_event_loop().create_future()
		fut = asyncio.Future[None]()
		self.out_xfer.setUserData(fut)
		self.out_xfer.setBuffer(data)
		self.out_xfer.submit()
		return await fut

	async def send_cmd(self, cmd: int, data: bytes):
		data = struct.pack('4B', 1, 9, 0, cmd) + data
		assert len(data) % 4 == 0
		data = struct.pack('2H', len(data)//4, 0x400a) + data
		# make sure we don't intermix different packet chunks
		async with self.send_lk:
			first = True
			for chunk in chunk_bytes(data, 0xfc):
				x, y = 0, 0 # seemingly ignored
				hdr = struct.pack('4B', len(chunk), x, 1 if first else 4, y)
				for chunk0 in chunk_bytes(hdr+chunk, self.out_max_size):
					await self.tx0(chunk0)
				first = False

