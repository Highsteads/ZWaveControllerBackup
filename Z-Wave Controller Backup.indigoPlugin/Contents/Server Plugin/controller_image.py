#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    controller_image.py
# Description: Pure core of the Z-Wave Controller Backup plugin: Serial API framing,
#              controller identity, raw NVM read / write / verify, image checks,
#              sidecar files and the restore guards. Never imports indigo. Any
#              object with read() and write() is a port, so everything here runs
#              under tests against a scripted stick.
# Author:      CliveS & Claude Fable 5.1
# Date:        13-09-2026 12:20
# Version:     1.0.0
#
# Facts this file rests on (all verified 12-09-2026 against a live Aeotec Gen5,
# firmware 1.01, and against @zwave-js/serial 15.29.0):
#   * Serial API framing: SOF, LEN, TYPE, FUNC, payload, checksum (0xFF XOR every
#     byte from LEN to the end of the payload). ACK 0x06, NAK 0x15, CAN 0x18.
#   * Function ids as listed below. The stick answers a request with ACK then a
#     RESPONSE frame carrying the same function id; it also sends unsolicited
#     REQUEST frames (radio traffic) at any time, which must be ACKed and dropped.
#   * NVM read/write: offset is 3 bytes big-endian, length 2 bytes big-endian.
#     Some sticks choke on big reads, so the chunk adapts to what comes back;
#     an empty reply means "smaller", and 48 bytes is the size every 500-series
#     stick accepts (zwave-js uses 48 for the Aeotec Gen5 and the Z-Wave.me UZB).
#   * The write chunk is (largest read reply - 5), the 5 being the offset+length
#     header, exactly as zwave-js restoreNVMRaw500 does it.

import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import select
import subprocess
import termios
import time
import xml.etree.ElementTree as ET

VERSION = "1.0.0"

SOF, ACK, NAK, CAN = 0x01, 0x06, 0x15, 0x18
REQ, RES = 0x00, 0x01

F_GET_INIT_DATA      = 0x02
F_GET_CTRL_CAPS      = 0x05
F_GET_SERIALAPI_CAPS = 0x07
F_SOFT_RESET         = 0x08
F_GET_VERSION        = 0x15
F_MEMORY_GET_ID      = 0x20
F_NVM_GET_ID         = 0x29
F_EXT_NVM_READ       = 0x2A
F_EXT_NVM_WRITE      = 0x2B
F_GET_SUC_NODE_ID    = 0x56

# NVMSize code (GetNVMId payload[3]) -> bytes, from @zwave-js/serial GetNVMIdMessages.
NVM_SIZES = {14: 16 * 1024, 15: 32 * 1024, 16: 64 * 1024, 17: 128 * 1024, 18: 256 * 1024,
             19: 512 * 1024, 20: 1024 * 1024, 21: 2 * 1024 * 1024, 22: 4 * 1024 * 1024}

# Protocol string (what GetVersion reports, "Z-Wave 4.54") -> 500-series SDK version.
# From zwave-js ZWaveSDKVersions.js, itself from Silicon Labs INS13954-13 chapter 7.
# The SDK number is what decides whether an image layout matches another stick's.
PROTOCOL_TO_SDK = {
    "6.10": "6.84.0", "6.09": "6.82.1", "6.08": "6.82.0", "6.07": "6.81.6", "6.06": "6.81.5",
    "6.05": "6.81.4", "6.04": "6.81.3", "6.03": "6.81.2", "6.02": "6.81.1", "6.01": "6.81.0",
    "5.03": "6.71.3", "5.02": "6.71.2", "4.61": "6.71.1", "4.60": "6.71.0", "4.45": "6.70.1",
    "4.28": "6.70.0", "4.62": "6.61.1", "4.33": "6.61.0", "4.12": "6.60.0", "4.54": "6.51.10",
    "4.38": "6.51.9", "4.34": "6.51.8", "4.24": "6.51.7", "4.05": "6.51.6", "4.01": "6.51.4",
    "3.99": "6.51.3", "3.95": "6.51.2", "3.92": "6.51.1", "3.83": "6.51.0", "3.79": "6.50.1",
    "3.71": "6.50.0", "3.35": "6.10.0", "3.41": "6.2.0", "3.37": "6.1.3", "3.33": "6.1.2",
    "3.10": "6.1.0", "3.07": "6.0.5", "3.06": "6.0.4", "3.04": "6.0.3", "3.03": "6.0.2",
    "2.99": "6.0.1", "2.96": "6.0.0", "3.28": "5.3.0", "2.78": "5.2.3", "2.64": "5.2.2",
    "2.51": "5.2.1", "2.48": "5.2.0", "2.36": "5.1.0", "2.22": "5.0.1", "2.16": "5.0.0",
    "3.67": "4.55.0", "3.52": "4.54.2", "3.42": "4.54.1", "3.40": "4.54.0", "3.36": "4.53.1",
    "3.34": "4.53.0", "3.22": "4.52.1", "3.20": "4.52.0", "2.97": "4.51.0",
}

# (manufacturer, product type, product id) -> a name a person recognises.
KNOWN_MODELS = {
    (0x0086, 0x0001, 0x005A): "Aeotec Z-Stick Gen5",
    (0x0115, 0x0400, 0x0001): "Z-Wave.me UZB",
}
# Sticks that choke on large NVM reads; zwave-js starts these at 48 bytes.
CHUNK_48_MODELS = {(0x0086, 0x0001, 0x005A), (0x0115, 0x0400, 0x0001)}
# Sticks zwave-js never soft-resets (they do not come back): the replug does the job instead.
NO_SOFT_RESET_MODELS = {(0x0115, 0x0000, 0x0000), (0x0115, 0x0400, 0x0001), (0x0109, 0x1001, 0x0201)}
DEFAULT_CHUNK = 168
SMALL_CHUNK = 48

ZWAVE_PREFS_FILE = "com.perceptiveautomation.indigoplugin.zwave.indiPref"
LSOF = "/usr/sbin/lsof"   # absolute: the plugin host's PATH has no /usr/sbin


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------

def build_frame(func, payload=b""):
    """A REQUEST frame for `func` with `payload`."""
    body = bytes([REQ, func]) + bytes(payload)
    length = len(body) + 1
    chk = 0xFF
    for b in bytes([length]) + body:
        chk ^= b
    return bytes([SOF, length]) + body + bytes([chk])


def checksum_ok(length, body):
    chk = 0xFF
    for b in bytes([length]) + body[:-1]:
        chk ^= b
    return chk == body[-1]


class SerialPort:
    """Exclusive, non-blocking, 115200 8N1 raw port. Only opened while Indigo has
    let go of the stick; TIOCEXCL refuses anyone else while we hold it."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def open(self):
        fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, termios.TIOCEXCL)
            a = termios.tcgetattr(fd)
            a[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY | termios.INPCK | termios.ISTRIP
                      | termios.ICRNL | termios.INLCR | termios.IGNCR | termios.BRKINT)
            a[1] &= ~termios.OPOST
            a[2] |= (termios.CLOCAL | termios.CREAD)
            a[2] &= ~termios.CSIZE
            a[2] |= termios.CS8
            a[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CRTSCTS)
            a[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHOE | termios.ISIG | termios.IEXTEN)
            a[4] = a[5] = termios.B115200
            a[6][termios.VMIN] = 0
            a[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, a)
            termios.tcflush(fd, termios.TCIOFLUSH)
        except Exception:
            os.close(fd)
            raise
        self.fd = fd

    def close(self):
        if self.fd is not None:
            try:
                termios.tcflush(self.fd, termios.TCIOFLUSH)
            except Exception:
                pass
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def write(self, data):
        n = 0
        deadline = time.monotonic() + 2.0
        while n < len(data):
            try:
                n += os.write(self.fd, data[n:])
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise RuntimeError("serial write stalled for 2 s")
                time.sleep(0.005)

    def read(self, max_bytes=4096):
        try:
            return os.read(self.fd, max_bytes)
        except BlockingIOError:
            return b""

    def wait_readable(self, timeout):
        """Block until bytes arrive or `timeout` passes. select() wakes on the byte,
        where a short sleep inside the plugin host wakes late: macOS grants a sleeping
        thread generous timer slack, and 5 ms became 10-12 ms per chunk, which turned a
        35-second read into five minutes on the first live run (13-09-2026)."""
        if self.fd is None:
            return False
        try:
            ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        except (OSError, ValueError):
            return False
        return bool(ready)


def open_port(path, tries=15, pause=1.5):
    """Open the port, retrying while the previous holder lets go."""
    port = SerialPort(path)
    last = None
    for _ in range(tries):
        try:
            port.open()
            return port
        except OSError as e:
            last = e
            if e.errno in (errno.EBUSY, errno.EAGAIN, errno.EACCES):
                time.sleep(pause)
                continue
            raise
    raise RuntimeError(f"could not open {path}: {last}")


class SerialApi:
    """Request/response over a port with ACK handling. Unsolicited frames are
    ACKed and counted, never delivered."""

    def __init__(self, port, sleep=time.sleep):
        self.port = port
        self.buf = bytearray()
        self.unsolicited = 0
        self._sleep = sleep

    def reset_parser(self, quiet=0.5, limit=3.0):
        """Resynchronise after the previous holder let go: send NAK (zwave-js does the same
        on open), then swallow whatever the stick still has to say, ACKing every whole frame
        so it stops retransmitting, until the line has been quiet for `quiet` seconds.
        Opening 0.8 s after Indigo closed the port and talking straight away drew a CAN
        on every attempt (13-09-2026): the stick was still finishing a reply to Indigo."""
        self.port.write(bytes([NAK]))
        deadline = time.monotonic() + limit
        last_byte = time.monotonic()
        self.buf.clear()
        while time.monotonic() < deadline:
            kind, _fr = self._next_event(0.05)
            if kind is not None:
                last_byte = time.monotonic()
                continue
            if time.monotonic() - last_byte >= quiet:
                break
        self.buf.clear()

    def _next_event(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            while self.buf:
                b = self.buf[0]
                if b == ACK:
                    del self.buf[0]
                    return "ack", None
                if b == NAK:
                    del self.buf[0]
                    return "nak", None
                if b == CAN:
                    del self.buf[0]
                    return "can", None
                if b != SOF:
                    del self.buf[0]
                    continue
                if len(self.buf) < 2:
                    break
                length = self.buf[1]
                if len(self.buf) < 2 + length:
                    break
                body = bytes(self.buf[2:2 + length])
                del self.buf[:2 + length]
                if length < 3 or not checksum_ok(length, body):
                    self.port.write(bytes([NAK]))
                    continue
                self.port.write(bytes([ACK]))
                return "frame", {"type": body[0], "func": body[1], "payload": body[2:-1]}
            if time.monotonic() >= deadline:
                return None, None
            data = self.port.read()
            if data:
                self.buf += data
            else:
                waiter = getattr(self.port, "wait_readable", None)
                if waiter is not None:
                    waiter(min(0.25, deadline - time.monotonic()))
                else:
                    self._sleep(0.005)

    def _drain(self, quiet=0.2, limit=1.0):
        """Swallow (and ACK) anything the stick is sending until it goes quiet."""
        deadline = time.monotonic() + limit
        last = time.monotonic()
        while time.monotonic() < deadline:
            kind, _fr = self._next_event(0.05)
            if kind is not None:
                last = time.monotonic()
                if kind == "frame":
                    self.unsolicited += 1
            elif time.monotonic() - last >= quiet:
                return

    def request(self, func, payload=b"", ack_timeout=1.5, res_timeout=3.0, attempts=5):
        frame = build_frame(func, payload)
        outcome = []
        for attempt in range(1, attempts + 1):
            self.port.write(frame)
            deadline = time.monotonic() + ack_timeout
            acked = False
            resend = False
            while time.monotonic() < deadline:
                kind, fr = self._next_event(deadline - time.monotonic())
                if kind == "ack":
                    acked = True
                    break
                if kind in ("nak", "can"):
                    # CAN: the stick was sending at the same moment. Let it finish (and ACK
                    # what it sent) before trying again, with a growing pause, as zwave-js does.
                    outcome.append(kind.upper())
                    self._drain()
                    self._sleep(0.1 * attempt)
                    resend = True
                    break
                if kind == "frame":
                    if fr["type"] == RES and fr["func"] == func:
                        return fr["payload"]
                    self.unsolicited += 1
            if resend:
                continue
            if not acked:
                outcome.append("no ACK")
                self._sleep(0.2)
                continue
            deadline = time.monotonic() + res_timeout
            while time.monotonic() < deadline:
                kind, fr = self._next_event(deadline - time.monotonic())
                if kind == "frame":
                    if fr["type"] == RES and fr["func"] == func:
                        return fr["payload"]
                    self.unsolicited += 1
                    continue
                if kind is None:
                    outcome.append("no reply")
                    break
        raise RuntimeError(f"no response to function 0x{func:02X} after {attempts} attempts ({', '.join(outcome) or 'silence'})")

    def send(self, func, payload=b"", ack_timeout=1.5, attempts=3):
        """A request that has no response (soft reset). True once the stick ACKs it."""
        frame = build_frame(func, payload)
        for attempt in range(1, attempts + 1):
            self.port.write(frame)
            deadline = time.monotonic() + ack_timeout
            while time.monotonic() < deadline:
                kind, fr = self._next_event(deadline - time.monotonic())
                if kind == "ack":
                    return True
                if kind in ("nak", "can"):
                    self._sleep(0.1 * attempt)
                    break
                if kind == "frame":
                    self.unsolicited += 1
        return False


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def parse_node_bitmask(bm):
    return [bi * 8 + bit + 1 for bi, by in enumerate(bm) for bit in range(8) if by & (1 << bit)]


def protocol_string(library_string):
    """'Z-Wave 4.54' -> '4.54'; None if the string has no version in it."""
    m = re.search(r"(\d+\.\d+)", library_string or "")
    return m.group(1) if m else None


def sdk_version(library_string):
    return PROTOCOL_TO_SDK.get(protocol_string(library_string) or "")


def model_name(manufacturer_id, product_type, product_id):
    known = KNOWN_MODELS.get((manufacturer_id, product_type, product_id))
    if known:
        return known
    return f"Z-Wave controller {manufacturer_id:04X}:{product_type:04X}:{product_id:04X}"


def initial_chunk_for(identity):
    key = (identity.get("manufacturerId"), identity.get("productType"), identity.get("productId"))
    return SMALL_CHUNK if key in CHUNK_48_MODELS else DEFAULT_CHUNK


def soft_reset_allowed(identity):
    key = (identity.get("manufacturerId"), identity.get("productType"), identity.get("productId"))
    return key not in NO_SOFT_RESET_MODELS


def is_500_series(identity):
    """700 and 800 series sticks report 'Z-Wave 7.x'; their memory is read another way."""
    proto = protocol_string(identity.get("libraryVersionString"))
    if not proto:
        return False
    return int(proto.split(".")[0]) < 7


def software_description(identity):
    lib = identity.get("libraryVersionString") or "unknown"
    sdk = sdk_version(lib)
    return f"{lib} (SDK {sdk})" if sdk else lib


def read_identity(api):
    ident = {}
    p = api.request(F_GET_VERSION)
    s = p.split(b"\x00", 1)[0].decode("ascii", "replace")
    ident["libraryVersionString"] = s
    ident["libraryType"] = p[len(s) + 1] if len(p) > len(s) + 1 else None
    ident["protocolVersion"] = protocol_string(s)
    ident["sdkVersion"] = sdk_version(s)
    p = api.request(F_MEMORY_GET_ID)
    ident["homeId"] = p[0:4].hex().upper()
    ident["ownNodeId"] = p[4]
    flags = api.request(F_GET_CTRL_CAPS)[0]
    ident["controllerCapabilityFlags"] = flags
    ident["isSecondary"] = bool(flags & 0x01)
    ident["onOtherNetwork"] = bool(flags & 0x02)
    ident["sisPresent"] = bool(flags & 0x04)
    ident["wasRealPrimary"] = bool(flags & 0x08)
    ident["isSUC"] = bool(flags & 0x10)
    ident["sucNodeId"] = api.request(F_GET_SUC_NODE_ID)[0]
    p = api.request(F_GET_SERIALAPI_CAPS)
    ident["serialApiVersion"] = f"{p[0]}.{p[1]}"
    ident["manufacturerId"] = int.from_bytes(p[2:4], "big")
    ident["productType"] = int.from_bytes(p[4:6], "big")
    ident["productId"] = int.from_bytes(p[6:8], "big")
    ident["modelName"] = model_name(ident["manufacturerId"], ident["productType"], ident["productId"])
    p = api.request(F_GET_INIT_DATA)
    ident["initApiVersion"] = p[0]
    caps = p[1]
    ident["initIsPrimary"] = not bool(caps & 0b0100)
    ident["initIsSIS"] = bool(caps & 0b1000)
    nodes = []
    if len(p) > 2 and p[2] == 29 and len(p) >= 3 + 29:
        nodes = parse_node_bitmask(p[3:3 + 29])
        if len(p) >= 3 + 29 + 2:
            ident["chipType"] = p[3 + 29]
            ident["chipVersion"] = p[3 + 29 + 1]
    ident["nodeIds"] = nodes
    return ident


def read_nvm_id(api):
    p = api.request(F_NVM_GET_ID)
    code = p[3]
    size = NVM_SIZES.get(code)
    if not size:
        raise RuntimeError(f"unknown NVM size code {code}")
    return {"nvmManufacturerId": p[1], "memoryType": p[2], "memorySizeCode": code, "sizeBytes": size}


# ---------------------------------------------------------------------------
# NVM read, write, reset
# ---------------------------------------------------------------------------

def dump_nvm(api, size, initial_chunk, progress=None, should_stop=None):
    """Read the whole NVM. `progress(offset, size)` every ten percent."""
    data = bytearray()
    offset = 0
    chunk = min(initial_chunk, size)
    empties = 0
    next_pct = 10
    while offset < size:
        if should_stop and should_stop():
            raise RuntimeError("stopped")
        want = min(chunk, size - offset)
        resp = api.request(F_EXT_NVM_READ, offset.to_bytes(3, "big") + want.to_bytes(2, "big"))
        if len(resp) == 0:
            empties += 1
            if empties > 5:
                raise RuntimeError("the controller keeps answering NVM reads with nothing")
            chunk = SMALL_CHUNK
            continue
        empties = 0
        if len(resp) > want:
            raise RuntimeError(f"NVM read returned {len(resp)} bytes for a {want}-byte request")
        data += resp
        offset += len(resp)
        if chunk > len(resp):
            chunk = len(resp)
        if progress and offset * 100 // size >= next_pct:
            progress(offset, size)
            next_pct += 10
    return bytes(data)


def read_exact(api, offset, length):
    """Read exactly `length` bytes from `offset`, however the stick chunks them."""
    out = bytearray()
    while len(out) < length:
        want = length - len(out)
        resp = api.request(F_EXT_NVM_READ, (offset + len(out)).to_bytes(3, "big") + want.to_bytes(2, "big"))
        if not resp:
            resp = api.request(F_EXT_NVM_READ, (offset + len(out)).to_bytes(3, "big") + min(SMALL_CHUNK, want).to_bytes(2, "big"))
            if not resp:
                raise RuntimeError(f"NVM read at offset {offset + len(out)} returned nothing")
        out += resp[:want]
    return bytes(out)


def _write_piece(api, offset, piece):
    resp = api.request(F_EXT_NVM_WRITE, offset.to_bytes(3, "big") + len(piece).to_bytes(2, "big") + piece)
    return bool(resp) and resp[0] != 0


def _write_or_prove(api, offset, piece, skipped):
    """Write `piece`; if the controller refuses, accept it only when the bytes already
    match, else split it and try the halves. Raises when a single byte is refused
    and differs. The Aeotec Gen5 refuses the final 16 bytes of its NVM (measured
    13-09-2026) and zwave-js never looks at the result; this does."""
    if _write_piece(api, offset, piece):
        return
    if read_exact(api, offset, len(piece)) == piece:
        skipped.append((offset, len(piece)))
        return
    if len(piece) == 1:
        raise RuntimeError(f"the controller refused the write at offset {offset} and the byte there differs from the image")
    half = len(piece) // 2
    _write_or_prove(api, offset, piece[:half], skipped)
    _write_or_prove(api, offset + half, piece[half:], skipped)


def write_nvm(api, image, initial_chunk, progress=None, should_stop=None):
    """Write `image` from offset 0. Chunk = (largest read reply - 5), as zwave-js does.
    Returns (bytes covered, skipped) where skipped lists (offset, length) regions the
    controller refused to write but which already held the image's bytes."""
    probe = api.request(F_EXT_NVM_READ, (0).to_bytes(3, "big") + min(initial_chunk, len(image)).to_bytes(2, "big"))
    chunk = len(probe) - 5
    if chunk < 1:
        raise RuntimeError("could not size the write chunk from a probe read")
    offset = 0
    next_pct = 10
    skipped = []
    while offset < len(image):
        if should_stop and should_stop():
            raise RuntimeError("stopped")
        piece = image[offset:offset + chunk]
        _write_or_prove(api, offset, piece, skipped)
        offset += len(piece)
        if progress and offset * 100 // len(image) >= next_pct:
            progress(offset, len(image))
            next_pct += 10
    return offset, skipped


def soft_reset(api):
    """Ask the stick to restart. It ACKs and reboots; there is no response frame."""
    return api.send(F_SOFT_RESET)


# ---------------------------------------------------------------------------
# Image checks, sidecars, guards
# ---------------------------------------------------------------------------

def compare_images(a, b):
    n = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if first is None and len(a) != len(b):
        first = min(len(a), len(b))
    return {"differingBytes": n, "firstDifference": first}


def image_checks(image, size, home_id):
    """Cheap sanity on a fresh image. Returns (checks, problems)."""
    ff = image.count(0xFF) / len(image) if image else 1.0
    zero = image.count(0x00) / len(image) if image else 1.0
    home_bytes = bytes.fromhex(home_id) if home_id else b""
    hits = [m.start() for m in re.finditer(re.escape(home_bytes), image)] if home_bytes else []
    checks = {
        "sizeMatchesNvmId": len(image) == size,
        "fractionFF": round(ff, 4),
        "fraction00": round(zero, 4),
        "homeIdOffsets": hits[:10],
        "homeIdOccurrences": len(hits),
        "sha256": hashlib.sha256(image).hexdigest(),
    }
    problems = []
    if not checks["sizeMatchesNvmId"]:
        problems.append(f"the image is {len(image)} bytes but the controller's memory is {size}")
    if ff > 0.98 or zero > 0.98:
        problems.append("the image is almost entirely blank")
    if home_bytes and not hits:
        problems.append("the Home ID does not appear anywhere in the image")
    return checks, problems


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-") or "controller"


def image_filename(identity, when):
    return f"{slug(identity.get('modelName'))}_{identity.get('homeId', 'unknown')}_{when.strftime('%Y-%m-%d_%H%M')}"


def sidecar_for(identity, nvm, checks, image_path, port, taken_at, plugin_version, indigo_version, reads_identical):
    return {
        "format": "zwave-controller-backup-sidecar-1",
        "takenAt": taken_at.isoformat(timespec="seconds"),
        "imageFile": os.path.basename(image_path),
        "sizeBytes": nvm["sizeBytes"],
        "port": port,
        "identity": identity,
        "nvm": nvm,
        "checks": dict(checks, readsIdentical=reads_identical),
        "pluginVersion": plugin_version,
        "coreVersion": VERSION,
        "indigoVersion": indigo_version,
        "restoreRule": "raw write onto the same model running the same software version only",
    }


def sidecar_path_for(image_path):
    base, _ = os.path.splitext(image_path)
    return base + ".json"


def load_sidecar(image_path):
    with open(sidecar_path_for(image_path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def list_images(folder):
    """Newest first: (image_path, sidecar_dict) for every .bin with a readable sidecar."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        if not name.lower().endswith(".bin"):
            continue
        path = os.path.join(folder, name)
        try:
            side = load_sidecar(path)
        except (OSError, ValueError):
            continue
        out.append((path, side))
    out.sort(key=lambda item: item[1].get("takenAt", ""), reverse=True)
    return out


def restore_refusals(image, sidecar, identity, nvm, replacement_ok=False):
    """Every reason NOT to write this image onto this controller. Empty = go."""
    reasons = []
    ident_img = (sidecar or {}).get("identity") or {}
    if not ident_img:
        reasons.append("the image has no sidecar file describing which controller it came from")
        return reasons
    if len(image) != nvm["sizeBytes"]:
        reasons.append(f"the image is {len(image)} bytes but this controller's memory is {nvm['sizeBytes']} bytes")
    img_model = (ident_img.get("manufacturerId"), ident_img.get("productType"), ident_img.get("productId"))
    this_model = (identity.get("manufacturerId"), identity.get("productType"), identity.get("productId"))
    if img_model != this_model:
        reasons.append(f"the image came from {ident_img.get('modelName', 'another model')} and this controller is {identity.get('modelName')}")
    if ident_img.get("libraryVersionString") != identity.get("libraryVersionString"):
        reasons.append(
            f"the image came from software '{ident_img.get('libraryVersionString')}' and this controller runs "
            f"'{identity.get('libraryVersionString')}'; the memory layout differs between versions")
    if ident_img.get("homeId") != identity.get("homeId") and not replacement_ok:
        reasons.append(
            f"the image is for Home ID {ident_img.get('homeId')} and this controller is {identity.get('homeId')}; "
            f"tick 'Replacement stick' if that is deliberate")
    return reasons


# ---------------------------------------------------------------------------
# Indigo's own Z-Wave settings (read, never written)
# ---------------------------------------------------------------------------

def zwave_port_from_prefs(pref_path):
    """(port, connection_type, home_id) from Indigo's Z-Wave prefs file, or (None, None, None)."""
    try:
        root = ET.parse(pref_path).getroot()
    except (OSError, ET.ParseError):
        return None, None, None
    port = conn = home = None
    for el in root.iter():
        if el.tag == "interfacePort_serialPortLocal":
            port = (el.text or "").strip() or None
        elif el.tag == "interfacePort_serialConnType":
            conn = (el.text or "").strip() or None
        elif home is None and re.fullmatch(r"Home([0-9A-F]{8})_Node\d+", el.tag or ""):
            home = el.tag[4:12]
    return port, conn, home


def port_holders(port):
    """Pids holding the port open, via lsof. Empty when free or when lsof is missing."""
    try:
        out = subprocess.run([LSOF, "-t", port], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return out.split()


def now():
    return datetime.datetime.now()
