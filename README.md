# DH-16D2S GD-ROM firmware

Modified firmware that lets the Lite-On / HP DH-16D2S read the high-density area of Dreamcast GD-ROMs. Based on HP firmware EH33. Current version: **GD0D**.

## Tested drives

The only two I have:

| Drive | Original firmware | Connection |
|---|---|---|
| HP DH-16D2S | EH33 | SATA |
| Lite-On DH-16D2S | JA12 | USB (ASMedia AS2115) |

Other DH-16D2S firmware families may work but are untested.

## Download

`DH16D2S_GD0D.bin`: https://archive.org/details/dh-16-d-2-s-gd-0-d

SHA-256 `ea6a1f8a79902951d0b16a86005d648077852633e07396e42def40efb10b2c6c`

GD0D vs GD0C: reads at the very start of the track 1 pre-gap (LBA -150 to -141) no longer seek into the lead-in and fail; see Known limits. Previous version: [GD0C](https://archive.org/details/dh-16-d-2-s-gd-0-c).

0x0000-0x3FFF is filled with FF on purpose: the drive never writes this area (boot loader and per-drive data), so one file fits both drives. Do not burn it with a chip programmer.

Changes against EH33: [PATCHES.md](PATCHES.md).

## Flashing (Linux)

Needs Python 3 and access to the drive's `/dev/sgN` (`lsscsi -g`).

```
SGDEV=/dev/sgN python3 d2sflash.py read backup.bin          # back up first
SGDEV=/dev/sgN python3 d2sflash.py DH16D2S_GD0D.bin         # dry run
SGDEV=/dev/sgN python3 d2sflash.py DH16D2S_GD0D.bin go      # flash
```

- Coming from JA12 (or any non-EH33 firmware), add `allbanks` after `go`.
- After flashing, power-cycle the drive, then run the dry run again: it should report 0 bytes differ.
- The drive should report revision `GD0D`.
- Lite-On Flash Utility does not work for this.

## Dumping

As in Redump's GD-ROM guide: LD area with redumper (as a CD), HD area with dreamdump.

LD area. redumper does not know the drive yet, so give the settings:

```
redumper disc --drive=/dev/sgN --drive-type=GENERIC --drive-read-offset=6 \
  --drive-sector-order=DATA_C2_SUB --drive-pregap-start=-146
```

- SATA: official redumper, with C2.
- USB bridges: needs redumper with the exact READ CD length change ([superg/redumper#459](https://github.com/superg/redumper/pull/459)) and `--drive-sector-order=DATA_SUB` (no C2 over USB).

HD area. dreamdump lists the drive since commit cbaec9b (revision GD0C). For GD0D give the settings until it lists that revision too:

```
dreamdump disc --drive=/dev/sgN --sector-order=DATA_C2_SUB --read-offset=6 --read-at-once=16
```

Works on SATA and USB. Do not raise `--read-at-once` above 16: the drive rejects READ CD transfers over 64 KB.

redumper alone can also dump the whole disc in one pass: add `--rings --skip=<LD lead-out + 100>-44852` to the redumper command above.

## Known limits

- LBA 44850-44852 (start of the HD pre-gap) cannot be read; the first readable HD sector is 44853.
- LBA -149 and -148 (track 1 pre-gap) cannot be read after a seek: the decoder locks a few sectors too late. Read in order from -150 they are fine. Neither is part of a Redump dump.
- SET CD SPEED is ignored; the drive reads at 16x.
- About 1 in 10 long random seeks takes ~2 s (servo recovery). Sequential dumping is not affected.

## Evidence

Dumps matching Redump (logs in Releases):

1. HP, SATA, redumper (local build with a DH16D2S entry), no drive options: Aero Dancing i (Japan)
2. HP, SATA, redumper b746 with the settings above: Aero Dancing i (Japan)
3. Lite-On, USB, redumper + #459: Harusame Youbi (Japan)
4. HP, SATA, GD0D, redumper b746 (LD area) + dreamdump cbaec9b (HD area): Aero Dancing i (Japan)

1-3 were made with GD0C. dreamdump 0.6.0 also matched on both drives with GD0C (HD area tracks).

## Recovery

If the drive stops booting, write your `backup.bin` back with a CH341A programmer (3.3 V) to the W25X20 flash chip.

## License

`d2sflash.py` and the documentation in this repository: GPL-3.0-or-later (see `LICENSE`). The firmware image is a modified HP/Lite-On firmware and is not covered by this license.

## Disclaimer

Use at your own risk. I am not responsible for bricked drives or lost data.
