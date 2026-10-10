#!/usr/bin/env python3
# d2sflash - firmware flasher for the Lite-On / HP DH-16D2S (MediaTek MT1309E, W25X20 flash) on Linux.
# usage: SGDEV=/dev/sgN d2sflash.py read <out.bin>              read the whole flash (256 KiB)
#        SGDEV=/dev/sgN d2sflash.py <image.bin>                 dry run: compare, write nothing
#        SGDEV=/dev/sgN d2sflash.py <image.bin> go [allbanks]   write
# Uses SG_IO with exact transfer lengths, so it also works behind ASMedia AS2115 USB bridges.
# The drive never writes 0x0000-0x3FFF (boot loader and per-drive data): only the application
# area 0x4000-0x3FFFF is replaced, so an image built from another drive's firmware keeps this
# drive's own boot loader. Banks are written in the order 1,2,3; the drive resets after bank 3,
# so an image that also differs in bank 0 (0x4000-0xFFFF, e.g. a change of firmware family) needs
# 'allbanks' (order 0,1,2,3). After writing, the drive stays not ready until it is power-cycled:
# power-cycle it and run the dry run again to verify.
# Safety gates: the drive must report DH16D2S and the image must carry the DH16D2S identification.
import ctypes, fcntl, os, struct, sys, time
DEV = os.environ.get('SGDEV') or sys.exit('set SGDEV to the drive, e.g. SGDEV=/dev/sg2 (see lsscsi -g)')
FLASH = 0x40000
SG_IO = 0x2285
_fd = os.open(DEV, os.O_RDWR | os.O_NONBLOCK)

def cam(cdb, din=0, dout=None, timeout=60):
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
    ok = status == 0 and host == 0 and (drv & 0xF) == 0 and resid == 0
    sb = sense.raw
    return ok, buf.raw[:din] if din else b'', 'sense %X/%02X/%02X st%d h%d d%d resid%d' % (sb[2] & 15, sb[12], sb[13], status, host, drv, resid)

def must(res, what):
    ok, _, err = res
    if not ok:
        raise SystemExit('%s FAILED: %s' % (what, err[-300:]))
    print('  ok:', what, flush=True)

def C(*b):
    return list(b) + [0] * (12 - len(b))

def enable():
    must(cam(C(0xF3, 0x0E, 0x02), din=0x10), 'flash-enable F3 0E 02')
    must(cam(C(0x1E, 0, 0, 0, 0x01)), 'LOCK')

def drain_ua():
    cam(C(0xDF, 0x83, 0, 0, 0xFF, 0, 0, 0, 0), din=0x80)

def read_flash():
    out = bytearray()
    for a in range(0, FLASH, 0x80):
        ok, d, err = cam(C(0xDF, 0x83, 0, 0, 0xFF, 0, (a >> 16) & 255, (a >> 8) & 255, a & 255), din=0x80)
        if not ok:
            raise SystemExit('read @%#x failed: %s' % (a, err[-200:]))
        out += d
    return bytes(out)

def diff(a, b):
    return [i for i in range(FLASH) if a[i] != b[i]]

def inquiry():
    ok, d, err = cam([0x12, 0, 0, 0, 0x24, 0], din=0x24)
    return d[8:16].decode('latin1'), d[16:32].decode('latin1'), d[32:36].decode('latin1')

if sys.argv[1] == 'read':
    open(sys.argv[2], 'wb').write(read_flash()); print('dumped'); sys.exit()
img = open(sys.argv[1], 'rb').read()
assert len(img) == FLASH
go = len(sys.argv) > 2 and sys.argv[2] == 'go'
allbanks = len(sys.argv) > 3 and sys.argv[3] == 'allbanks'
vendor, product, rev = inquiry()
print('drive: %r %r rev %r' % (vendor, product, rev), flush=True)
# safety gate: same model on both sides (a D1S image on a D2S bricked a drive before)
if 'DH16D2S' not in product:
    raise SystemExit('REFUSING: drive is not a DH-16D2S')
if b'DH16D2S' not in img[0x14000:0x15000]:
    raise SystemExit('REFUSING: image has no DH-16D2S identification block at 0x14000')
print('reading current flash...', flush=True)
before = read_flash()
d = diff(before, img)
app = [i for i in d if i >= 0x4000]
bank_cnt = [sum(1 for i in app if i >> 16 == b) for b in range(4)]
print('application 0x4000-0x3FFFF: %d bytes differ; per bank %s' % (len(app), bank_cnt), flush=True)
print('bootloader/NV 0x0000-0x3FFF: %d bytes differ (never written by the drive; informational)' % (len(d) - len(app)), flush=True)
if not go:
    print('DRY-RUN: nothing written'); sys.exit()
if not app:
    print('application identical; nothing to do'); sys.exit()
if bank_cnt[0] and not allbanks:
    raise SystemExit("REFUSING: image differs in flash-bank0 (0x4000-0xFFFF); add 'allbanks' to write it")
print('== FLASHING', sys.argv[1], '==', flush=True)
enable()
for b in ((0, 1, 2, 3) if bank_cnt[0] else (1, 2, 3)):
    if not bank_cnt[b]:
        print('  skip bank%d (identical)' % b); continue
    res = cam(C(0x3B, 0x05, 0x01, 0, 0, 0, 0, 0, 0x10, 0x7F, 0, 0), dout=bytes(16))
    if not res[0]:
        print('  bank%d begin failed, draining UA + re-enable, retry: %s' % (b, res[2][-120:]))
        drain_ua(); enable()
        res = cam(C(0x3B, 0x05, 0x01, 0, 0, 0, 0, 0, 0x10, 0x7F, 0, 0), dout=bytes(16))
    must(res, 'bank%d begin(CTRL16)' % b)
    for i in range(16):
        addr = b * 0x10000 + i * 0x1000
        must(cam(C(0x3B, 0x05, 0x01, 0, i * 0x10, 0, 0, 0x10, 0, b, 0, 0), dout=img[addr:addr + 0x1000]), 'bank%d write %d/16' % (b, i + 1))
    must(cam(C(0x3B, 0x05, 0x01, 0, 0, 0, 0, 0, 0, 0x80, b, 0)), 'bank%d commit(CTRL0)' % b)
res = cam(C(0x1E, 0, 0, 0, 0x00))
print('  UNLOCK', 'ok' if res[0] else ('rc!=0 (UA after auto-reset is benign): ' + res[2][-120:]))
print('verifying...', flush=True)
time.sleep(2)
drain_ua()
try:
    after = read_flash()
except SystemExit:
    sys.exit('written. The drive does not answer until it is power-cycled: power it off and on, '
             'then run the dry run (without go) to verify.')
d2 = [i for i in diff(after, img) if i >= 0x4000]
print('VERIFY OK: application matches the image.' if not d2 else 'VERIFY MISMATCH: %d bytes (first %#x)' % (len(d2), d2[0]))
