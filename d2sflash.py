#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# d2sflash - firmware flasher for Lite-On MediaTek drives that use the DF 83 / F3 0E / 3B 05
# vendor commands (256 KiB SPI flash), on Linux. Developed and tested on the Lite-On / HP
# DH-16D2S (MT1309E, W25X20); nothing in it is tied to that model.
USAGE = '''usage: SGDEV=/dev/sgN d2sflash.py read <out.bin>                    read the whole flash (256 KiB)
       SGDEV=/dev/sgN d2sflash.py <image.bin>                       dry run: compare, write nothing
       SGDEV=/dev/sgN d2sflash.py <image.bin> go [allbanks] [force] write'''
# Uses SG_IO with exact transfer lengths, so it also works behind ASMedia AS2115 USB bridges.
#
# The drive never writes 0x0000-0x3FFF (boot loader and per-drive data): only the application
# area 0x4000-0x3FFFF is replaced, so an image built from another drive's firmware keeps this
# drive's own boot loader. Flash banks (64 KiB) are written in the order 1,2,3; the drive resets
# after bank 3, so an image that also differs in bank 0 (0x4000-0xFFFF, e.g. a change of firmware
# family) needs 'allbanks' (order 0,1,2,3). After writing, the drive stays not ready until it is
# power-cycled: power-cycle it and run the dry run again to verify.
#
# Safety:
# - Every flash read is done twice and must agree (a drive that is still starting up can return
#   wrong data with GOOD status).
# - The image must be for this drive: the vendor/product string the drive reports in INQUIRY is
#   looked up in the drive's current firmware, and the image must carry the same string at the
#   same offsets and start its application area with the same opcode. This rejects images of
#   other models and of same-named models with a different firmware layout. 'force' skips it.
# - Before writing, the current flash is saved to d2sflash-backup-<time>.bin.
# - A flash bank that fails to write is retried from its start. If it still fails, do NOT
#   power-cycle the drive: fix the cause and run the same command again.
import ctypes, errno, fcntl, os, struct, sys, time

FLASH = 0x40000
APP = 0x4000                  # first byte the drive lets us write
SG_IO = 0x2285
_fd = -1


def cam(cdb, din=0, dout=None, timeout=60):
    """Returns (ok, data, description, (sense key, asc, ascq))."""
    if dout is not None:
        n, direction = len(dout), -2
        buf = ctypes.create_string_buffer(bytes(dout), max(n, 1))
    else:
        n, direction = din, (-3 if din else -1)
        buf = ctypes.create_string_buffer(max(n, 1))
    sense = ctypes.create_string_buffer(32)
    c = ctypes.create_string_buffer(bytes(cdb))
    hdr = bytearray(struct.pack('iiBBHIPPPIIiPBBBBHHiII', ord('S'), direction, len(cdb), 32, 0, n,
                    ctypes.addressof(buf), ctypes.addressof(c), ctypes.addressof(sense),
                    timeout * 1000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    fcntl.ioctl(_fd, SG_IO, hdr)
    f = struct.unpack('iiBBHIPPPIIiPBBBBHHiII', bytes(hdr))
    status, host, drv, resid = f[13], f[17], f[18], f[19]
    # drv & 0xF includes DRIVER_SENSE: sense data with GOOD status still counts as a failure
    ok = status == 0 and host == 0 and (drv & 0xF) == 0 and resid == 0
    sb = sense.raw
    key = (sb[2] & 15, sb[12], sb[13])
    return ok, buf.raw[:din] if din else b'', 'sense %X/%02X/%02X st%d h%d d%d resid%d' % (key + (status, host, drv, resid)), key


def must(res, what):
    if not res[0]:
        raise SystemExit('%s FAILED: %s' % (what, res[2]))
    print('  ok:', what, flush=True)


def C(*b):
    return list(b) + [0] * (12 - len(b))


def wait_ready(limit=60):
    """Wait until the drive has finished starting up. 'No medium' counts as ready."""
    end = time.time() + limit
    while True:
        ok, _, err, key = cam([0, 0, 0, 0, 0, 0])
        if ok or (key[0] == 2 and key[1] == 0x3A):
            return
        if time.time() > end:
            raise SystemExit('drive not ready after %d s: %s' % (limit, err))
        time.sleep(1)


def inquiry():
    ok, d, err, _ = cam([0x12, 0, 0, 0, 0x24, 0], din=0x24)
    if not ok or len(d) < 0x24:
        raise SystemExit('INQUIRY failed: ' + err)
    return d[8:16], d[16:32], d[32:36]


def read_pass():
    out = bytearray()
    for a in range(0, FLASH, 0x80):
        ok, d, err, _ = cam(C(0xDF, 0x83, 0, 0, 0xFF, 0, (a >> 16) & 255, (a >> 8) & 255, a & 255), din=0x80)
        if not ok:
            raise SystemExit('read @%#x failed: %s' % (a, err))
        out += d
    return bytes(out)


def read_flash():
    """Read the flash until two consecutive passes agree."""
    wait_ready()
    prev = read_pass()
    for _ in range(4):
        cur = read_pass()
        if cur == prev:
            return cur
        n = sum(1 for i in range(FLASH) if cur[i] != prev[i])
        print('  two reads differ in %d bytes (drive still starting up?), reading again...' % n, flush=True)
        prev = cur
        time.sleep(2)
    raise SystemExit('flash reads keep changing; not trusting them')


def find_all(data, pat, start=0):
    out, i = [], data.find(pat, start)
    while i >= 0:
        out.append(i)
        i = data.find(pat, i + 1)
    return out


def check_image(ident, before, img):
    """Reasons why img does not look like firmware for the drive whose flash is before."""
    cur = find_all(before, ident, APP)
    if not cur:
        return ["the drive's own firmware does not contain its INQUIRY string %r (unsupported drive?)" % ident.decode('latin1')]
    why = []
    new = find_all(img, ident, APP)
    if not new:
        why.append('the image does not contain %r: it is for another model' % ident.decode('latin1'))
    elif new != cur:
        why.append('the image has the model string at %s, the drive at %s: different firmware layout'
                   % ([hex(o) for o in new], [hex(o) for o in cur]))
    if img[APP] != before[APP]:
        why.append('the application area starts with %02X in the image and %02X in the drive' % (img[APP], before[APP]))
    return why


def enable():
    r = cam(C(0xF3, 0x0E, 0x02), din=0x10)
    if r[0]:
        r = cam(C(0x1E, 0, 0, 0, 0x01))
    return r


def drain_ua():
    cam(C(0xDF, 0x83, 0, 0, 0xFF, 0, 0, 0, 0), din=0x80)


def write_bank(img, b, tries=3):
    begin = C(0x3B, 0x05, 0x01, 0, 0, 0, 0, 0, 0x10, 0x7F, 0, 0)
    for attempt in range(1, tries + 1):
        res = cam(begin, dout=bytes(16))
        step = 'begin'
        if res[0]:
            for i in range(16):
                addr = b * 0x10000 + i * 0x1000
                res = cam(C(0x3B, 0x05, 0x01, 0, i * 0x10, 0, 0, 0x10, 0, b, 0, 0), dout=img[addr:addr + 0x1000])
                step = 'write %d/16' % (i + 1)
                if not res[0]:
                    break
        if res[0]:
            res = cam(C(0x3B, 0x05, 0x01, 0, 0, 0, 0, 0, 0, 0x80, b, 0))
            step = 'commit'
        if res[0]:
            print('  ok: bank%d written and committed' % b, flush=True)
            return
        print('  bank%d %s failed (attempt %d/%d): %s' % (b, step, attempt, tries, res[2]), flush=True)
        drain_ua()
        enable()
    raise SystemExit('bank%d could not be written. DO NOT POWER-CYCLE THE DRIVE: a half-written bank will not '
                     'boot. Fix the cause (cable, bridge, power) and run the same command again.' % b)


def main():
    global _fd
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help') or (args[0] == 'read' and len(args) != 2):
        sys.exit(USAGE)
    dev = os.environ.get('SGDEV')
    if not dev:
        sys.exit('set SGDEV to the drive, e.g. SGDEV=/dev/sg2 (see lsscsi -g)\n' + USAGE)
    reading = args[0] == 'read'
    words = args[1:] if not reading else []
    if any(w not in ('go', 'allbanks', 'force') for w in words) or (words and words[0] != 'go'):
        sys.exit(USAGE)
    go, allbanks, force = 'go' in words, 'allbanks' in words, 'force' in words
    if not reading:
        img = open(args[0], 'rb').read()
        if len(img) != FLASH:
            sys.exit('%s is %d bytes; a flash image is %d bytes' % (args[0], len(img), FLASH))

    flags = os.O_RDWR | os.O_NONBLOCK
    try:
        # exclusive when writing: refuse a drive some other program (a dump) has open
        _fd = os.open(dev, flags | (os.O_EXCL if go else 0))
    except OSError as e:
        if e.errno == errno.EBUSY:
            sys.exit('%s is in use by another program; not flashing a drive that is being used' % dev)
        sys.exit('cannot open %s: %s' % (dev, e.strerror))

    vendor, product, rev = inquiry()
    ident = vendor + product
    print('drive: %r %r rev %r' % (vendor.decode('latin1'), product.decode('latin1'), rev.decode('latin1')), flush=True)
    print('reading current flash (twice)...', flush=True)
    before = read_flash()

    if reading:
        if not find_all(before, ident, APP):
            sys.exit("the data read does not contain the drive's INQUIRY string: this drive does not seem to "
                     'support the DF 83 flash read. Nothing saved.')
        open(args[1], 'wb').write(before)
        print('dumped to', args[1])
        return

    why = check_image(ident, before, img)
    for w in why:
        print('  image check:', w)
    diffs = [i for i in range(APP, FLASH) if before[i] != img[i]]
    bank_cnt = [sum(1 for i in diffs if i >> 16 == b) for b in range(4)]
    boot = sum(1 for i in range(APP) if before[i] != img[i])
    print('application 0x4000-0x3FFFF: %d bytes differ; per bank %s' % (len(diffs), bank_cnt), flush=True)
    print('bootloader/NV 0x0000-0x3FFF: %d bytes differ (never written by the drive; informational)' % boot, flush=True)
    if not go:
        print('DRY-RUN: nothing written' + ('; this image would be REFUSED' if why else ''))
        return
    if why and not force:
        sys.exit("REFUSING: the image does not match this drive (see 'image check' above). 'force' overrides.")
    if not diffs:
        print('application identical; nothing to do')
        return
    if bank_cnt[0] and not allbanks:
        sys.exit("REFUSING: image differs in flash-bank0 (0x4000-0xFFFF); add 'allbanks' to write it")

    backup = 'd2sflash-backup-%s.bin' % time.strftime('%Y%m%d-%H%M%S')
    open(backup, 'wb').write(before)
    print('current flash saved to', backup, flush=True)
    print('== FLASHING', args[0], '==', flush=True)
    must(enable(), 'flash enable (F3 0E 02) and LOCK')
    for b in ((0, 1, 2, 3) if bank_cnt[0] else (1, 2, 3)):
        if not bank_cnt[b]:
            print('  skip bank%d (identical)' % b)
            continue
        write_bank(img, b)
    res = cam(C(0x1E, 0, 0, 0, 0x00))
    print('  UNLOCK', 'ok' if res[0] else ('rc!=0 (UA after auto-reset is benign): ' + res[2]))
    print('written. Power-cycle the drive, then run the dry run (without go): it must report 0 bytes differ.')


if __name__ == '__main__':
    main()
