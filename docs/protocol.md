# Instax SHARE Wi-Fi protocol

This document describes the protocol that the Instax SHARE SP-2 and SP-3 printers speak over Wi-Fi, as this library implements it. `instax/protocol.py` encodes and decodes the frames, and `instax/client.py` runs the print sequence.

Each fact carries one of three labels.

- **Verified** means it was observed on an SP-3 with firmware 01.02 during a successful print.
- **Original project** means it comes from [jpwsutton/instax_api](https://github.com/jpwsutton/instax_api), including the SP-2 frames in its test suite.
- **Unconfirmed** means no printer traffic has confirmed it yet.

## Network

The printer runs its own Wi-Fi access point named `INSTAX-` followed by 8 digits. It assigns client addresses by DHCP and listens on TCP `192.168.0.251:8080`. **Verified.**

The access point has no Wi-Fi password. **Verified.**

Every exchange is one command frame from the client followed by one response frame from the printer. The printer accepts a new TCP connection for each step and for each status poll. **Verified.**

## Frames

All integers are big-endian. The length field counts the whole frame. The checksum is the bitwise NOT of the 16-bit sum of every byte before it. **Verified.**

### Command

| Offset | Size | Content |
|---|---|---|
| 0 | 1 | `0x24` |
| 1 | 1 | Opcode |
| 2 | 2 | Frame length |
| 4 | 4 | Session id, chosen by the client |
| 8 | 2 | PIN |
| 10 | 2 | Zero |
| 12 | n | Payload |
| 12+n | 2 | Checksum |
| 14+n | 2 | `0x0D 0x0A` |

### Response

| Offset | Size | Content |
|---|---|---|
| 0 | 1 | `0x2A` |
| 1 | 1 | Opcode of the command it answers |
| 2 | 2 | Frame length |
| 4 | 4 | Session id of the command it answers |
| 8 | 4 | Unknown, always zero so far |
| 12 | 1 | Return code |
| 13 | 1 | Unknown, always zero so far |
| 14 | 1 | Eject flags |
| 15 | 1 | Status |
| 16 | n | Payload |
| 16+n | 2 | Checksum |
| 18+n | 2 | `0x0D 0x0A` |

Bit 2 of the eject flags is set while a print is ejecting. **Verified.**

The status byte holds the number of film sheets left in bits 0 to 3. **Verified.** Bits 4 to 6 hold the battery state. **Original project.** Bit 7 is set when the film cover is open. **Unconfirmed.**

A film count above 10 means the printer is out of film. **Unconfirmed.**

The battery state splits into a charge level from 0 to 3 in its low two bits and a USB charging flag in its high bit. **Unconfirmed.** The SP-3 reported 5 while plugged in and partly charged, which fits that reading.

### Return codes

| Code | Meaning | Label |
|---|---|---|
| `0x00` | Success | Verified |
| `0x7F` | Busy. Status polls return it while printing. | Verified |
| `0xA0` | Another device is using the printer | Original project |
| `0xA1` | The image data was rejected | Original project |
| `0xA2` | Battery empty | Original project |
| `0xA3` | Printing | Original project |
| `0xA4` | Ejecting | Original project |
| `0xA5` | Test mode | Original project |
| `0xB4` | Charging | Original project |
| `0xE0` | Connection error | Original project |
| `0xF0` to `0xF3` | The printer could not read the command | Original project |
| `0xF4` | Out of film | Original project |
| `0xF5` | Mechanism error | Original project |
| `0xF6` | Motor error | Original project |
| `0xF7` | Wrong PIN | Original project |
| `0xF8` | Sensor error | Original project |

The original project names these codes but does not say when the printer returns them. None of the error codes has been observed yet.

## Opcodes

| Opcode | Name | Command payload | Response payload | Label |
|---|---|---|---|---|
| `0x4F` | Specifications | none | u16 width at 0, u16 height at 2, u16 colors at 4, u16 chunk size at 12 | Verified |
| `0x50` | Reset | none | none | Verified |
| `0x51` | Transfer start | format (u8), options (u8), image length (u32), 6 zero bytes | u16 chunk size at 2 | Verified |
| `0x52` | Send chunk | chunk index (u32), then the chunk | the chunk index (u32) | Verified |
| `0x53` | Transfer end | none | none | Verified |
| `0xB0` | Print start | none | u32 estimated print time in tenths of a second | Verified |
| `0xB3` | Lock | state (u8, 1 to lock and 0 to unlock), 3 zero bytes | none | Verified |
| `0xB4` | Power off | 4 zero bytes | none | Unconfirmed |
| `0xB6` | Change PIN | 2 zero bytes, new PIN (u16). The header carries the old PIN. | none | Unconfirmed |
| `0xC0` | Version | none | u16 unknown, u16 firmware, u16 hardware | Verified |
| `0xC1` | Print count | none | u32 lifetime print count at 0 | Verified |
| `0xC2` | Model name | none | ASCII model name, such as `SP-3` | Verified |
| `0xC3` | Print status | none | none. The return code carries the state. | Verified |
| `0xC4` | Function version | 2 zero bytes, u16 key | u16 value at 2 | Original project |

Versions are formatted as two hex bytes, so a firmware field of `0x0102` reads as `01.02`.

The SP-3 sends these Specifications values. **Verified.**

| Offset | Size | SP-3 value | Meaning |
|---|---|---|---|
| 0 | 2 | 800 | Width |
| 2 | 2 | 800 | Height |
| 4 | 2 | 256 | Colors |
| 6 | 2 | 10 | Unknown |
| 12 | 2 | 60000 | Chunk size |
| 14 | 1 | 18 | Unknown |
| 16 | 4 | 154080 | Unknown |

The SP-2 frames in the original project send width 600, 16 at offset 14 and 0 at offset 16, with the other fields the same.

Lock gives one client exclusive use of the printer. **Unconfirmed.**

The Lock command and response frames in the original project's test suite show that the original client sent Lock as well.

## Image format

The client sends format 16 with options 0. The image is uncompressed 8-bit RGB at exactly the size Specifications reports, so 1,920,000 bytes on the SP-3. Rows go from the bottom of the print to the top, and each row holds all of its red values, then all green, then all blue. **Verified.**

The client sends every chunk at the full chunk size and zero-pads the last one. Transfer start declares the unpadded length. On the SP-3 the image is exactly 32 chunks, so this padding has not been exercised.

If the Transfer start response has no payload, the client uses 480-byte chunks. **Unconfirmed.**

The SP-1 uses a different image format, which this library does not implement. **Unconfirmed.**

## Print sequence

The client prints in this order. Each numbered group is one TCP connection. **Verified.**

1. Lock with state 1.
2. Model name, Print count, Specifications, Reset. The client stops here if the status byte shows the cover open or no film.
3. Transfer start, one Send chunk per chunk, Transfer end.
4. Version, repeated once a second while the printer reports printing or ejecting or the eject flag is set. The client then waits until at least one second has passed since Transfer end and sends Print start, repeated once a second while the printer reports printing or ejecting.
5. Print status, once a second, on a new connection each time. `0x7F` means the print is still running and `0x00` means it finished. The client also treats `0xA3` as still running.
6. Lock with state 0. The client sends this even when the print fails.

On the SP-3, the print took about as long as the Print start estimate (14 seconds), and every status poll during it returned `0x7F` with the eject flag set. The film count dropped by one on the final poll. **Verified.**

The retries in step 4 did not trigger on the SP-3. Whether the printer needs the one-second wait after Transfer end, and whether it answers `0xF4` instead of `0x00` after the last sheet, is **unconfirmed**. The client treats `0xF4` from Print status as a finished print.

The original project's client also sent Function version for keys 1 to 8 before printing. This client skips that, and the SP-3 printed without it. **Verified.**

## PIN

Every command carries the PIN in its header, and there is no pairing step. The SP-3 accepted the default PIN 1111. **Verified.**

The printer answers `0xF7` to a wrong PIN. **Original project.**

A printer with PIN protection turned off accepts any PIN. **Unconfirmed.**

## Open questions

- What response bytes 8 to 11 and 13 hold.
- What the Specifications fields at offsets 6, 14 and 16 mean.
- How the printer reports the error cases, such as no film, an open cover or a wrong PIN.
- Whether the battery decoding holds for values other than 5.

Running a command with `-v` logs every response frame in hex, which answers most of these when the situation comes up.
