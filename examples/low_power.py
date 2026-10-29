# low_power.py - proven power fixes for the Seeed XIAO MG24 (plain, not Sense)
#
# For MicroPython v1.29.0 + PR #16864 + lightsleep fixes (mg24-sleep branch),
# built with CONFIG_PM_DEVICE_SYSTEM_MANAGED=n.
#
# Usage (in main.py, AFTER the 5 s escape hatch):
#
#     import low_power as lp
#     usb = lp.setup()
#     while True:
#         ...do work...
#         lp.lightsleep(60_000)
#
# Measured on battery, in lightsleep (EM2, RAM kept): 6.6 uA.

import time
import machine
from machine import mem32, Pin

# ---------------------------------------------------------------
# GPIO register helpers
# ---------------------------------------------------------------
GPIO  = 0x5003C000
PORTS = {"A": 0, "B": 1, "C": 2, "D": 3}

def _port_base(port):
    return GPIO + 0x30 + PORTS[port] * 0x30   # ports start 0x30 in

def disable(port, pin):
    """Set a pin to mode 0 (DISABLED). Undone by a reset."""
    base = _port_base(port)
    if pin < 8:
        addr, shift = base + 0x04, pin * 4          # MODEL
    else:
        addr, shift = base + 0x0C, (pin - 8) * 4    # MODEH
    mem32[addr] = mem32[addr] & ~(0xF << shift)

def dout(port, pin, value):
    """Set or clear a pin's DOUT bit (in DISABLED mode, 1 = weak pull-up)."""
    addr = _port_base(port) + 0x10
    if value:
        mem32[addr] = mem32[addr] | (1 << pin)
    else:
        mem32[addr] = mem32[addr] & ~(1 << pin)

# ---------------------------------------------------------------
# USB detection (PA8 = serial to the bridge chip, PA9 = serial from it)
# ---------------------------------------------------------------
_PA       = _port_base("A")
_PA_MODEH = _PA + 0x0C        # PA8 mode = bits 0-3, PA9 mode = bits 4-7
_PA_DOUT  = _PA + 0x10
_PA_DIN   = _PA + 0x14

# Zephyr's setting for PA8, captured at import (before anything changes it)
_PA8_ORIGINAL = mem32[_PA_MODEH] & 0xF

def usb_present():
    """Return True if USB is plugged in. Leaves PA8 on only if it is."""
    modeh = mem32[_PA_MODEH]
    d     = mem32[_PA_DOUT]

    # 1. Stop PA8 back-powering the bridge chip and let it drain
    mem32[_PA_MODEH] = modeh & ~0xF
    time.sleep_ms(300)

    # 2. PA9 -> input with weak pull-down (mode 2 = INPUTPULL, DOUT bit = 0)
    mem32[_PA_DOUT]  = d & ~(1 << 9)
    mem32[_PA_MODEH] = (mem32[_PA_MODEH] & ~0xF0) | (2 << 4)
    time.sleep_ms(5)

    # 3. Read it: high means the bridge chip is powered, i.e. USB is there
    present = bool((mem32[_PA_DIN] >> 9) & 1)

    # 4-5. Restore PA9 exactly as it was, then PA8 only if USB is there
    mem32[_PA_DOUT]  = d
    mem32[_PA_MODEH] = (mem32[_PA_MODEH] & ~0xF0) | (modeh & 0xF0)
    if present:
        mem32[_PA_MODEH] = (mem32[_PA_MODEH] & ~0xF) | _PA8_ORIGINAL
    return present

# ---------------------------------------------------------------
# On-board SPI flash, Puya P25Q32SH (from Seeed's schematic):
#   CS = PA6, CLK = PA0, DI (MOSI) = PB0, DO (MISO) = PB1
# NOTE: Seeed's Demo 3 uses PA3/PA4/PA5, which are the header SPI pins
# and are NOT connected to the flash.
# MicroPython's /flash filesystem is in the MG24's own flash, not this chip.
# ---------------------------------------------------------------
_flash_cs  = Pin(("gpioa", 6), Pin.OUT, value=1)   # high = not selected
_flash_sck = Pin(("gpioa", 0), Pin.OUT, value=0)
_flash_di  = Pin(("gpiob", 0), Pin.OUT, value=0)
_flash_do  = None

def _xfer(byte):
    """Send one byte and read one back, SPI mode 0, bit by bit."""
    r = 0
    for i in range(8):
        _flash_di.value((byte >> (7 - i)) & 1)
        _flash_sck.value(1)
        r = (r << 1) | _flash_do.value()
        _flash_sck.value(0)
    return r

def _flash_cmd(c, n=0):
    global _flash_do
    _flash_do = Pin(("gpiob", 1), Pin.IN, Pin.PULL_UP)   # (re)enable DO input
    _flash_cs.value(0)
    _xfer(c)
    data = bytes(_xfer(0) for _ in range(n))
    _flash_cs.value(1)
    return data

def flash_wake():
    """Release the flash from deep power-down."""
    _flash_cmd(0xAB)
    time.sleep_ms(1)

def flash_id():
    """JEDEC ID as hex. '856016' = Puya, 4 MB. 'ffffff' = asleep or absent."""
    return _flash_cmd(0x9F, 3).hex()

def flash_sleep():
    """Put the flash into deep power-down (saves ~7.6 uA). CS stays high."""
    _flash_cmd(0xAB)                 # make sure it's listening first
    time.sleep_ms(1)
    _flash_cmd(0xB9)
    time.sleep_ms(1)
    disable("B", 1)                  # DO floats while asleep
    dout("B", 1, 0)

# ---------------------------------------------------------------
# RF antenna switch power (PB5). Off saves ~81 uA.
# Switch it ON before using the radio, OFF afterwards.
# ---------------------------------------------------------------
_rf_pw = Pin(("gpiob", 5), Pin.OUT, value=0)

def rf_power(on):
    _rf_pw.value(1 if on else 0)

# ---------------------------------------------------------------
# LED (PA7, active-low)
# ---------------------------------------------------------------
_led = Pin(("gpioa", 7), Pin.OUT, value=1)

def blink(times=1, on_ms=180, off_ms=240):
    for _ in range(times):
        _led.value(0)
        time.sleep_ms(on_ms)
        _led.value(1)
        time.sleep_ms(off_ms)

# ---------------------------------------------------------------
# The main entry points
# ---------------------------------------------------------------
_usb = False

def setup():
    """Apply every proven fix. Returns True if USB is plugged in.

    On battery: PA8 off (~10 mA), debug pins off (~80 uA), PA9 disabled and
    PA8/PA9 pull-ups cleared (~32 uA). Always: RF switch power off (~81 uA),
    flash in deep power-down (~7.6 uA).
    """
    global _usb
    _usb = usb_present()
    if not _usb:
        mem32[GPIO + 0x440] = 0      # debug pins off (DBGROUTEPEN)
        disable("A", 9)              # PA9 floats with the bridge chip off
        dout("A", 9, 0)
        dout("A", 8, 0)              # no pull-up on PA8
    rf_power(False)
    flash_sleep()
    return _usb

def lightsleep(ms):
    """EM2 sleep with RAM kept. Execution carries on afterwards."""
    machine.lightsleep(ms)
    if not _usb:
        disable("A", 8)              # belt and braces: keep PA8 off
