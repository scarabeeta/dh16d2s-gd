# GD0C patches

GD0C vs. stock HP EH33: 732 bytes in 18 places, banks 1 and 2. Common code, bank 0, bank 3 and 0x0000-0x3FFF unchanged.

## Addressing

MT1309E, 8051 with code banking (bank = P1[2:0]).

| Code | File offset |
|---|---|
| common 0x0000-0x3FFF | 0x04000 + a |
| bank n 0x4000-0xFFFF | 0x08000 + n * 0xC000 + (a - 0x4000) |

Bank 1: 0x14000 + (a - 0x4000). Bank 2: 0x20000 + (a - 0x4000). New code sits in the zero-filled tail of banks 1 and 2.

## Stock code used

| Address | What |
|---|---|
| bank1 0x843C | READ CD handler. CDB in IRAM 0x6E.., LBA in 0x70-0x73 |
| bank1 0x8579 | `LCALL 0x0D0B` -> bank3 0x9697, sector status into IRAM 0x79: 01 audio, 02 data, 0x40 beyond capacity |
| bank1 0x857E | status 01 -> 0x8584 (read), else 0x85B6 (error) |
| bank1 0x7EC9 | read engine. Target LBA - 3, decoder matches Q absolute time |
| XDATA 0x80A0-0x80A3 | capacity (lead-out + 150). < 45000 on a GD LD area |
| bank2 0xB0C9 | one seek pass. Target [0x8060..62], current [0x804B..4D], binary M:S:F, both restored on exit |
| bank2 0xC92B | near (< 60 s) / far decision |
| bank2 0xA328 | near count. Tables 0x40F3 / 0x41CF, minutes 0-109 only |
| bank2 0xB360 | far count, CD geometry (r0 25 mm, 1.6 um) |
| bank2 0xDEB1 / 0xDF4D | current position from Q into [0x804B..4D] |
| XDATA 0x8017 | seek minute limit, 110 |

## Changes

| File | Code | Bytes | Change | Since |
|---|---|---|---|---|
| 0x140E6 | bank1 0x40E6 | 4 | IDENTIFY revision `HE33` -> `DGC0` (byte-swapped) | GD01 |
| 0x1418C | bank1 0x418C | 4 | INQUIRY revision `EH33` -> `GD0C` | GD01 |
| 0x1425A | bank1 0x425A | 4 | KEY-DATA revision `EH33` -> `GD0C` | GD01 |
| 0x18518 | bank1 0x8518 | 1 | `06` -> `00`. No more reject below absolute minute 6; pre-gap readable to LBA -146 | GD06 |
| 0x1857A | bank1 0x857A | 10 | 0x8579 -> `LCALL 0xF5D6`. 0x857E -> `LJMP 0xF610`. 0x8581-83 NOP | GD0A, GD0B |
| 0x185C5 | bank1 0x85C5 | 3 | `SETB 2A.5; RET` -> `LJMP 0xF5C9`. Data sector requested as CD-DA comes back raw (scrambled), not 05/64. redumper reads this way | GD02 |
| 0x1F5C9 | bank1 0xF5C9 | 63 | 0xF5C9: status < 2 -> read, else stock error | GD02 |
| | bank1 0xF5D6 | | GD, LBA 44853-0xFFFFFF: status 0x40 without calling 0x0D0B. Saves ~0.6 ms per READ CD | GD0A |
| 0x1F610 | bank1 0xF610 | 118 | Gate. 01 -> read. Within capacity, not 01 -> stock error. Beyond capacity, read only: 44853 <= LBA < 600000; -0xB100 <= LBA < 0; LD lead-out (capacity < 0x10000, LBA - capacity + 150 < 256). Rest: 05/21 | GD01-GD0B |
| 0x26358 0x263EE 0x26432 | bank2 0xA358 0xA3EE 0xA432 | 3 x 4 | Target minute load -> `LCALL 0xF405` | GD01 |
| 0x26D3A | bank2 0xAD3A | 5 | Minute limit 110 -> 122 | GD01 |
| 0x27110 | bank2 0xB110 | 2 | 0xB10F `LCALL 0xC92B` -> `LCALL 0xF5C0` (stub chain, ends in 0xC92B) | GD05-GD0C |
| 0x29F19 | bank2 0xDF19 | 13 | Q TNO 0 branch -> `LCALL 0xF47B` | GD06 |
| 0x2A654 | bank2 0xE654 | 5 | Direction logic limit -> 123. Minutes 110-122 not treated as wrapped | GD01 |
| 0x2B405 | bank2 0xF405 | 12 | Near-table index = min(target minute, 109) | GD01 |
| 0x2B451 | bank2 0xF451 | 359 | Lead-in target (LBA < 0, minute >= 95): target and current minute +5 mod 100 | GD06 |
| | bank2 0xF47B | | In the GD HD lead-in, position = Q rel - 141:29:00 (min 09:00:00). Stock reports 0:00 there and the seek bounces | GD06-GD08 |
| | bank2 0xF510 | | Target minute 9-15 (HD start): from outside minutes 9-19 go via 14:28:50. From inside, target before 10:20 and > 40 s away: aim at the midpoint. B360 overshoots in the HD area | GD05, GD09 |
| 0x2B5C0 | bank2 0xF5C0 | 133 | Target minute 100-122, outward, > 40 s away: aim at the midpoint. Otherwise the first far jump lands past the HD end, loses Q, recovers via 1:01: 2.5-5 s | GD0C |

Seek stubs change the target for one B0C9 pass only; B0C9 restores it. Every GD rule checks capacity < 45000 first; CD, DVD and the LD area run stock code.

## Porting notes

- Read path: READ CD of LBA >= 44853 must pass the gate. Seek path: reach minutes 10-122 (limits, near tables, overshoot). The decoder needs no change.
- LBA 44850-44852 can't be read. The engine starts at LBA - 3, inside the HD lead-in, where the Q absolute field holds TOC pointers.
- XDATA is 512 bytes, 0x8200+ mirrors 0x8000. 0x81E4-0x81FF were free in EH33 (used for seek logs during development).
