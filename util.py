import asyncio

def chunk_bytes(buf: bytes, n: int, start = 0, maxc = None):
	stop = len(buf) if maxc is None else start + n*maxc
	return (buf[i:i+n] for i in range(start, stop, n))

def make_callback(cb):
	loop = asyncio.get_event_loop()
	def inner(*args, **kwargs):
		asyncio.run_coroutine_threadsafe(cb(*args, **kwargs), loop)
	return inner
