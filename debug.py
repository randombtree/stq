# -*- tab-width: 4; indent-tabs-mode: t; py-indent-offset: 4; -*-
# Author: Roger Blomgren <roger.blomgren@iki.fi>

import inspect, traceback
import os.path
import time

class debug:
	do_debug = True
	fast_time = True
	"""Use fast clock when printing debug lines"""
	clock_start = 0

	def __init__(self, debugstr):
		self.strace = None
		if debug.do_debug:
			self.strace = inspect.stack()
		if self.strace:
			for frame, fn, lno, fname, context, index in self.strace:
				# Don't print putput from debug routines, just in case
				# we choose to separate debugging output into several methods
				if fn[-8:] == "debug.py":
					continue

				clsname = None
				strtime = None

				# Get class name for debug output
				if "self" in frame.f_locals.keys():
					# Use -> to point out that it can be a closure,
					# that happens inside an instance method
					clsname = "%s->" % (frame.f_locals["self"].__class__.__name__,)
				else:
					clsname = ""


				if self.fast_time:
					t = time.time()
					if debug.clock_start == 0:
						debug.clock_start = t
					d = t - debug.clock_start
					strtime = "%3.3f " % (d,)
				else:
					# TODO
					strtime = ""
				print("%s%s:%d %s%s\t\"%s\"" % (
					strtime,
					os.path.basename(fn),
					lno,
					clsname,
					fname,
						debugstr))
				break

	@classmethod
	def setDebug(cls, do_debug):
		assert type(do_debug) == bool
		cls.do_debug = do_debug

	@classmethod
	def isDebug(cls):
		return cls.do_debug

	@classmethod
	def print_exception(cls, t=None):
		traceback.print_exc(t)
	@classmethod
	def print_strace(cls):
		traceback.print_stack()
	# /__init__
# /class debug
