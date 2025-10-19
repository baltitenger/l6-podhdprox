#!/usr/bin/env python3

import asyncio
import sys

from PySide6 import QtAsyncio
from PySide6.QtWidgets import QApplication
from usb1 import HOTPLUG_EVENT_DEVICE_ARRIVED, USBContext, USBDevice # type: ignore

from model import Model, SetlistModel, WholePreset
from view import MainWindow, Slot
from usb_adapter import UsbAdapter
from pxio import parse_pxb

async def on_hotplug(dev: USBDevice):
	hdl = dev.open()
	ad = UsbAdapter(hdl, model)
	async with asyncio.TaskGroup() as tg:
		tg.create_task(ad.rx_loop())
		tg.create_task(ad.rx_preset())

def hotplug_callback(ctx: USBContext, dev: USBDevice, event: int):
	print(dev, event)
	if event == HOTPLUG_EVENT_DEVICE_ARRIVED:
		loop.create_task(on_hotplug(dev))
	# TODO handle disconnect

def usb_poller():
	while run:
		usb_ctx.handleEvents()

@Slot()
def stop_usb_poller():
	global run
	run = False
	usb_ctx.interruptEventHandler()

async def main(app: QApplication):
	global model, loop, run
	run = True
	loop = asyncio.get_event_loop()

	model = Model()

	usb_ctx.hotplugRegisterCallback(hotplug_callback, vendor_id=0x0e41, product_id=0x415a)
	asyncio.get_event_loop().run_in_executor(None, usb_poller)

	mw = MainWindow(model, stop_usb_poller)
	# FIXME temp
	with open('junk/reset.pxb', 'rb') as f:
		for i, (sl_name, presets) in enumerate(parse_pxb(f)):
			model.bank[i] = sl = SetlistModel(sl_name)
			sl.presets = list(presets)
	model.sel_list = 0
	model.sel_preset = 3
	model.preset = model.bank[0].presets[3] # type: ignore
	await mw.on_ev(WholePreset())
	mw.show()
	await asyncio.Future()

if __name__ == '__main__':
	with USBContext() as usb_ctx:
		QtAsyncio.run(main(QApplication(sys.argv)), handle_sigint=True)
