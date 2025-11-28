#!/usr/bin/env python3

import asyncio
import sys

from PySide6 import QtAsyncio
from PySide6.QtWidgets import QApplication, QMessageBox
from usb1 import HOTPLUG_EVENT_DEVICE_ARRIVED, USBContext, USBDevice, USBDeviceHandle, USBError

from model import Model, Startup
from usb_adapter import UsbAdapter
from util import make_callback
from view import MainWindow

class Main:
	async def on_hotplug(self, ctx: USBContext, dev: USBDevice, event: int):
		if event == HOTPLUG_EVENT_DEVICE_ARRIVED:
			try:
				hdl: USBDeviceHandle = dev.open()
				ad = UsbAdapter(hdl, self.model)
			except USBError as e:
				self.mw.show_msg_box(QMessageBox.Icon.Critical,
					'Failed connecting to USB device',
					f'Failed connecting to USB device with error {e}.\n'
					'Make sure no other program or driveris accessing the hardware '
					'and that you have sufficient privileges.')
				return
			async with asyncio.TaskGroup() as tg:
				tg.create_task(ad.rx_loop())
				await ad.on_ev(Startup())
			self.model.listeners.remove(ad)
			self.mw.show_msg_box(QMessageBox.Icon.Information, 'USB Disconnected',
				'The USB device was disconnected.')

	def usb_poller(self):
		while self.run:
			self.usb_ctx.handleEvents()

	def stop_usb_poller(self):
		self.run = False
		self.usb_ctx.interruptEventHandler()

	async def async_main(self, usb_ctx: USBContext, app: QApplication):
		self.run = True
		self.usb_ctx = usb_ctx

		self.model = Model()

		usb_ctx.hotplugRegisterCallback(make_callback(self.on_hotplug), vendor_id=0x0e41, product_id=0x415a)
		asyncio.get_event_loop().run_in_executor(None, self.usb_poller)

		self.mw = MainWindow(self.model, self.stop_usb_poller)

		self.mw.reload()
		self.mw.show()
		argv = app.arguments()[1:]
		if len(argv) == 0:
			pass
		elif len(argv) == 1:
			self.mw.do_load_file(argv[0])
		else:
			print("Expected at most 1 argument (file to load)")
			exit(1)

		await asyncio.Future()

def main():
	with USBContext() as usb_ctx:
		QtAsyncio.run(Main().async_main(usb_ctx, QApplication(sys.argv)), handle_sigint=True)

if __name__ == '__main__':
	main()
