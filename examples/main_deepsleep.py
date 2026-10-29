# main.py - example using low_power.py with machine.deepsleep() (EM4, RAM lost)
# Copy to the board as main.py, alongside low_power.py.
#
# Each cycle: 5 s escape hatch, low-power setup, three blinks, then
# machine.deepsleep(20000). Waking from EM4 is like a reset, so this
# file runs again from the top. Expect ~2 uA during each sleep on battery.

import time
import machine

time.sleep(5)              # escape hatch: Ctrl-C now if you need the REPL

import low_power as lp     # import AFTER the escape hatch

usb = lp.setup()
if usb:
    print("Deep sleep for 20 s... (the REPL will disconnect)")

lp.blink(3)

machine.deepsleep(20_000)
