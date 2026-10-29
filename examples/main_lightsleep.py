# main.py - example using low_power.py with machine.lightsleep() (EM2, RAM kept)
# Copy to the board as main.py, alongside low_power.py.
# Expect ~6.6 uA between blinks on battery.

import time
time.sleep(5)              # escape hatch: Ctrl-C now if you need the REPL

import low_power as lp     # import AFTER the escape hatch

usb = lp.setup()
lp.blink(3)                # "started"

if usb:
    print("USB: True. Flash ID while asleep:", lp.flash_id(), "(expect ffffff)")

while True:
    lp.lightsleep(10_000)
    lp.blink(1)
