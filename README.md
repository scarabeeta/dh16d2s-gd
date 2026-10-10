# DH-16D2S GD-ROM firmware

Modified firmware that lets the Lite-On / HP DH-16D2S read the high-density area of Dreamcast GD-ROMs. Based on HP firmware EH33. Current version: **GD0C**.

## Tested drives

The only two I have:

| Drive | Original firmware | Connection |
|---|---|---|
| HP DH-16D2S | EH33 | SATA |
| Lite-On DH-16D2S | JA12 | USB (ASMedia AS2115) |

Other DH-16D2S firmware families may work but are untested.

## Download

`DH16D2S_GD0C.bin`: https://archive.org/details/dh-16-d-2-s-gd-0-c

SHA-256 `77afdfb37426830fc796f84deee6df9d64463eb413aba78b77b19a014e2db350`

0x0000-0x3FFF is filled with FF on purpose: the drive never writes this area (boot loader and per-drive data), so one file fits both drives. Do not burn it with a chip programmer.

## Flashing (Linux)

Needs Python 3 and access to the drive's `/dev/sgN` (`lsscsi -g`).

```
SGDEV=/dev/sgN python3 d2sflash.py read backup.bin          # back up first
SGDEV=/dev/sgN python3 d2sflash.py DH16D2S_GD0C.bin         # dry run
SGDEV=/dev/sgN python3 d2sflash.py DH16D2S_GD0C.bin go      # flash
```

- Coming from JA12 (or any non-EH33 firmware), add `allbanks` after `go`.
- After flashing, power-cycle the drive, then run the dry run again: it should report 0 bytes differ.
- The drive should report revision `GD0C`.
- Lite-On Flash Utility does not work for this.

## Dumping

redumper detects the drive (DH16D2S / GD0C). Use `--rings` and skip the gap between the two areas:

```
redumper disc --drive=/dev/sgN --rings --skip=<LD lead-out + 100>-44852
```

- SATA: official redumper, with C2.
- USB bridges: needs redumper with the exact READ CD length change ([superg/redumper#459](https://github.com/superg/redumper/pull/459)) and `--drive-sector-order=DATA_SUB` (no C2 over USB).
- Manual settings for other tools: read offset +6, sector order DATA_C2_SUB, pre-gap start -146.

## Known limits

- LBA 44850-44852 (start of the HD pre-gap) cannot be read; the first readable HD sector is 44853.
- SET CD SPEED is ignored; the drive reads at 16x.
- About 1 in 10 long random seeks takes ~2 s (servo recovery). Sequential dumping is not affected.

## Evidence

Dumps matching Redump (logs in Releases):

1. HP, SATA, redumper with the DH16D2S entry, no drive options: Aero Dancing i (Japan)
2. HP, SATA, redumper b746: Aero Dancing i (Japan)
3. Lite-On, USB, redumper + #459: Harusame Youbi (Japan)

dreamdump 0.7.0 (`--sector-order=DATA_C2_SUB --read-offset=6 --read-at-once=16`) also matches on the HP.

## Recovery

If the drive stops booting, write your `backup.bin` back with a CH341A programmer (3.3 V) to the W25X20 flash chip.

## Disclaimer

Use at your own risk. I am not responsible for bricked drives or lost data.
