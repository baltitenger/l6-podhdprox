#!/usr/bin/env python3

import asyncio
import sys

from PySide6 import QtAsyncio
from PySide6.QtWidgets import QApplication
from usb1 import HOTPLUG_EVENT_DEVICE_ARRIVED, USBContext, USBDevice

from model import Model
from usb_adapter import UsbAdapter
from util import make_callback
from view import MainWindow, Slot

async def on_hotplug(ctx: USBContext, dev: USBDevice, event: int):
	if event == HOTPLUG_EVENT_DEVICE_ARRIVED:
		hdl = dev.open()
		ad = UsbAdapter(hdl, model)
		async with asyncio.TaskGroup() as tg:
			tg.create_task(ad.rx_loop())
			await ad.rx_preset()
	# TODO handle disconnect

def usb_poller():
	while run:
		usb_ctx.handleEvents()

def stop_usb_poller():
	global run
	run = False
	usb_ctx.interruptEventHandler()

async def async_main(app: QApplication):
	global model, run
	run = True

	model = Model()

	usb_ctx.hotplugRegisterCallback(make_callback(on_hotplug), vendor_id=0x0e41, product_id=0x415a)
	asyncio.get_event_loop().run_in_executor(None, usb_poller)

	mw = MainWindow(model, stop_usb_poller)

	mw.reload()
	mw.show()
	argv = app.arguments()[1:]
	if len(argv) == 0:
		pass
	elif len(argv) == 1:
		mw.do_load_file(argv[0])
	else:
		print("Expected at most 1 argument (file to load)")
		exit(1)

	await asyncio.Future()

def main():
	global usb_ctx
	with USBContext() as usb_ctx:
		QtAsyncio.run(async_main(QApplication(sys.argv)), handle_sigint=True)

if __name__ == '__main__':
	main()
