#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    fake_stick.py
# Description: Scripted controllers behind a read()/write() port, for the contract
#              tests. FakeStick answers the Serial API functions the plugin uses
#              with payloads shaped exactly like the live Aeotec Gen5's (captured
#              12-09-2026), serves NVM reads from a bytearray, applies writes to
#              it, and can inject unsolicited frames, a corrupt frame, a CAN, or
#              empty NVM replies to exercise the parser's rough edges. FakeStick700
#              does the same for the 700/800 series with payloads captured from a
#              Zooz ZST39 LR and a Silicon Labs 700 stick (14-09-2026), including
#              the unwritten final chunk and the hang a write into the tail causes.
# Author:      CliveS & Claude Fable 5.1; 700/800 series Autolog & Claude Opus 5
# Date:        14-09-2026 16:30
# Version:     1.1.0

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PLUGIN = os.path.join(ROOT, "Z-Wave Controller Backup.indigoPlugin", "Contents", "Server Plugin")


def load_core():
    spec = importlib.util.spec_from_file_location("controller_image", os.path.join(SERVER_PLUGIN, "controller_image.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ci = load_core()

GEN5 = {
    "library": b"Z-Wave 4.54\x00" + bytes([1]),          # library string + type (static controller)
    "homeId": bytes.fromhex("E0BB7FA8"), "ownNode": 1,
    "caps": 0x18,                                           # wasRealPrimary | SUC
    "suc": 1,
    "serialapi": bytes([1, 1, 0x00, 0x86, 0x00, 0x01, 0x00, 0x5A]) + bytes(32),
    "nvmid": bytes([0x00, 31, 129, 18]),                    # manufacturer, type, size code 18 = 256 KB
    "nodes": [1, 18, 28, 35, 41, 42, 44, 78, 88, 91, 98, 100, 102, 103, 104, 135, 141, 149, 157, 158, 186, 188, 223],
    "chip": (5, 0),
}


def response_frame(func, payload):
    body = bytes([ci.RES, func]) + bytes(payload)
    length = len(body) + 1
    chk = 0xFF
    for b in bytes([length]) + body:
        chk ^= b
    return bytes([ci.SOF, length]) + body + bytes([chk])


def request_frame(func, payload):
    return ci.build_frame(func, payload)


def node_bitmask(nodes):
    bm = bytearray(29)
    for n in nodes:
        bm[(n - 1) // 8] |= 1 << ((n - 1) % 8)
    return bytes(bm)


class FakeStick:
    """A port whose other end is a 500-series controller."""

    def __init__(self, nvm=None, profile=GEN5, max_read=48, refuse_writes=False, refuse_tail=0):
        self.profile = dict(profile)
        self.nvm = bytearray(nvm if nvm is not None else self.default_nvm())
        self.max_read = max_read
        self.refuse_writes = refuse_writes
        self.refuse_tail = refuse_tail          # the Gen5 refuses writes touching its last 16 bytes
        self.inbox = bytearray()       # bytes the plugin wrote to us, awaiting parse
        self.outbox = bytearray()      # bytes we hand back on read()
        self.requests = []             # (func, payload) as received
        self.acks_received = 0
        self.naks_received = 0
        self.write_count = 0
        self.reads_before_empty = None  # after N reads answer one empty chunk (chunk fallback)
        self.corrupt_next_response = False
        self.can_next_request = False
        self.unsolicited_before_next = []   # list of (func, payload) REQUEST frames to emit first

    @staticmethod
    def default_nvm(size=256 * 1024):
        data = bytearray(b"\xff" * size)
        data[0:6] = b"ZeNsYs"
        data[8:12] = GEN5["homeId"]
        for i in range(12, 32825):
            data[i] = (i * 7) & 0xFF
        return data

    # --- port interface ---

    def open(self):
        pass

    def close(self):
        pass

    def read(self, max_bytes=4096):
        out = bytes(self.outbox[:max_bytes])
        del self.outbox[:max_bytes]
        return out

    def write(self, data):
        self.inbox += data
        self._pump()

    # --- the controller ---

    def _pump(self):
        while self.inbox:
            b = self.inbox[0]
            if b == ci.ACK:
                self.acks_received += 1
                del self.inbox[0]
                continue
            if b == ci.NAK:
                self.naks_received += 1
                del self.inbox[0]
                continue
            if b != ci.SOF:
                del self.inbox[0]
                continue
            if len(self.inbox) < 2:
                return
            length = self.inbox[1]
            if len(self.inbox) < 2 + length:
                return
            body = bytes(self.inbox[2:2 + length])
            del self.inbox[:2 + length]
            func, payload = body[1], body[2:-1]
            self.requests.append((func, payload))
            if self.can_next_request:
                self.can_next_request = False
                self.outbox += bytes([ci.CAN])
                continue
            self.outbox += bytes([ci.ACK])
            for ufunc, upayload in self.unsolicited_before_next:
                self.outbox += request_frame(ufunc, upayload)
            self.unsolicited_before_next = []
            resp = self._respond(func, payload)
            if resp is not None:
                frame = response_frame(func, resp)
                if self.corrupt_next_response:
                    self.corrupt_next_response = False
                    bad = bytearray(frame)
                    bad[-1] ^= 0x55
                    self.outbox += bytes(bad) + frame     # the corrupt one, then a good one after the NAK
                else:
                    self.outbox += frame

    def _respond(self, func, payload):
        p = self.profile
        if func == ci.F_GET_VERSION:
            return p["library"]
        if func == ci.F_MEMORY_GET_ID:
            return p["homeId"] + bytes([p["ownNode"]])
        if func == ci.F_GET_CTRL_CAPS:
            return bytes([p["caps"]])
        if func == ci.F_GET_SUC_NODE_ID:
            return bytes([p["suc"]])
        if func == ci.F_GET_SERIALAPI_CAPS:
            return p["serialapi"]
        if func == ci.F_GET_INIT_DATA:
            return bytes([5, 0b1000, 29]) + node_bitmask(p["nodes"]) + bytes(p["chip"])
        if func == ci.F_NVM_GET_ID:
            return p["nvmid"]
        if func == ci.F_EXT_NVM_READ:
            offset = int.from_bytes(payload[0:3], "big")
            length = int.from_bytes(payload[3:5], "big")
            if self.reads_before_empty is not None:
                if self.reads_before_empty == 0:
                    self.reads_before_empty = None
                    return b""
                self.reads_before_empty -= 1
            length = min(length, self.max_read)
            return bytes(self.nvm[offset:offset + length])
        if func == ci.F_EXT_NVM_WRITE:
            if self.refuse_writes:
                return bytes([0])
            offset = int.from_bytes(payload[0:3], "big")
            length = int.from_bytes(payload[3:5], "big")
            if self.refuse_tail and offset + length > len(self.nvm) - self.refuse_tail:
                return bytes([0])
            data = payload[5:5 + length]
            self.nvm[offset:offset + len(data)] = data
            self.write_count += 1
            return bytes([1])
        if func == ci.F_SOFT_RESET:
            return None
        return b""


# ---------------------------------------------------------------- 700 / 800 series

# Payloads captured 14-09-2026. ZST39: GetVersion "Z-Wave 7.24" type 7, GetSerialApiCapabilities
# 01 46 027A 0004 0610 + bitmask (advertises 0x2E, 0x3D and 0x09), GetSerialApiInitData api 10,
# GetProtocolVersion 00 07 18 02 + build + git hash. The 700 stick is the same shape with
# "Z-Wave 7.17", ids 0000:0004:0004, api 9, and no 0x3D in its bitmask.
ZST39 = {
    "library": b"Z-Wave 7.24\x00" + bytes([7]),
    "homeId": bytes.fromhex("E2DAD17B"), "ownNode": 1,
    "caps": 0x18, "suc": 1,
    "serialapi": bytes.fromhex("0146027a00040610f6873e88cf2bc05fe3d7fde0970f008000808680ba0d00f00000ee7fc0000000"),
    "protocol": bytes.fromhex("00071802abcd") + b"8bcd01f6b2a24ecc",
    "init_api": 10,
    "nodes": [1, 2, 3, 4, 5, 6, 7, 9, 11, 15],
    "chip": (8, 0),
    "nvm_size": 40960,
}
STICK700 = {
    "library": b"Z-Wave 7.17\x00" + bytes([7]),
    "homeId": bytes.fromhex("E1C3BDE8"), "ownNode": 1,
    "caps": 0x1C, "suc": 1,
    "serialapi": bytes.fromhex("0711000000040004f6873e88cf2bc04ffbd7fde00700008000808680ba05007000002e7fc0000000"),
    "protocol": bytes.fromhex("00071101abcd") + b"0123456789abcdef",
    "init_api": 9,
    "nodes": [1, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 38, 92, 93, 105, 106, 111, 114, 116, 120, 128],
    "chip": (7, 0),
    "nvm_size": 49152,
}


class FakeStick700(FakeStick):
    """A port whose other end is a 700 or 800 series controller. NVM3 is served through
    0x2E and, when the profile advertises it, 0x3D, in `chunk`-byte replies (64 on both
    real sticks). The write that reaches the end of the NVM is answered 'end of file' and
    dropped, as the real ones do; a write ending inside the last two bytes hangs the stick
    (no ACK, ever), as the ZST39 did. A soft reset is answered, after the ACK, with an
    unsolicited SerialAPIStarted, and it turns the radio back on and appends a small
    housekeeping object into the first erased space, as the firmware does on restart."""

    SERIAL_API_STARTED = bytes.fromhex("0700010100085e989f556c568f7401031d0000")   # captured from the ZST39

    def __init__(self, nvm=None, profile=ZST39, chunk=64, node_id_bits=8, housekeeping=b"\xd7\x00\x8a\x8a\xfe\x00\x00\x00\x03\x06\x00\x00\x00\x03"):
        super().__init__(nvm=nvm if nvm is not None else self.default_nvm700(profile), profile=profile)
        self.chunk = chunk
        self.node_id_bits = node_id_bits
        self.housekeeping = housekeeping
        self.radio_on = True
        self.watchdog_on = True
        self.nvm_open = False
        self.hung = False
        self.resets = 0
        self.tail_writes_declined = 0
        self.empty_probe_replies = 0    # answer this many 255-byte reads with nothing (SDK quirk)

    @staticmethod
    def default_nvm700(profile):
        """Something NVM3-shaped enough for the checks: page headers, objects with the Home ID
        in them, erased space at the end of each 8 KB page, and a data tail like the ZST39's."""
        size = profile["nvm_size"]
        data = bytearray(b"\xff" * size)
        page = 8192
        for p in range(size // page):
            base = p * page
            data[base:base + 20] = bytes.fromhex("01009ab20c0000c8f3ffff17ffffffff3990ffff")
            for i in range(20, page // 2):
                data[base + i] = (i * 13 + p) & 0xFF
            data[base + 64:base + 68] = profile["homeId"]
        data[size - 64:size] = bytes.fromhex("0000000000000253bc01400bfd05") + bytes(50)
        return data

    def _node_id(self, n):
        return n.to_bytes(2, "big") if self.node_id_bits == 16 else bytes([n])

    def _pump(self):
        if self.hung:
            self.inbox.clear()
            return
        super()._pump()

    def _respond(self, func, payload):
        p = self.profile
        if func == ci.F_MEMORY_GET_ID:
            return p["homeId"] + self._node_id(p["ownNode"])
        if func == ci.F_GET_SUC_NODE_ID:
            return self._node_id(p["suc"])
        if func == ci.F_GET_INIT_DATA:
            return bytes([p["init_api"], 0b1000, 29]) + node_bitmask(p["nodes"]) + bytes(p["chip"])
        if func == ci.F_GET_PROTOCOL_VER:
            return p["protocol"]
        if func == ci.F_SET_RF_RECEIVE_MODE:
            self.radio_on = bool(payload[0])
            return bytes([1])
        if func == ci.F_STOP_WATCHDOG:
            self.watchdog_on = False
            return None
        if func == ci.F_SOFT_RESET:
            self.resets += 1
            self.radio_on = self.watchdog_on = True
            self.nvm_open = False
            self._append_housekeeping()
            self.outbox += request_frame(ci.F_SERIAL_API_STARTED, self.SERIAL_API_STARTED)
            return None
        if func in (ci.F_NVM_OPERATIONS, ci.F_EXT_NVM_OPERATIONS):
            return self._nvm_op(func, payload)
        if func in (ci.F_NVM_GET_ID, ci.F_EXT_NVM_READ, ci.F_EXT_NVM_WRITE):
            return b""          # a 700 stick has none of the 500-series NVM functions
        return super()._respond(func, payload)

    def _append_housekeeping(self):
        """What the firmware does on restart: a new object in the first erased run it finds."""
        if not self.housekeeping:
            return
        run = bytes(b"\xff" * (len(self.housekeeping) + 8))
        at = bytes(self.nvm).find(run, 8192)
        if at >= 0:
            self.nvm[at:at + len(self.housekeeping)] = self.housekeeping

    def _nvm_op(self, func, payload):
        if func == ci.F_EXT_NVM_OPERATIONS and 0x3D not in ci.parse_function_bitmask(self.profile["serialapi"]):
            return bytes([0x04, 0])             # sub-command not supported
        w = 4 if func == ci.F_EXT_NVM_OPERATIONS else 2
        op = payload[0]
        size = len(self.nvm)

        def reply(status, offset_or_size, data=b""):
            out = bytes([status, len(data)]) + offset_or_size.to_bytes(w, "big") + data
            if op == ci.NVM_OP_OPEN and func == ci.F_EXT_NVM_OPERATIONS:
                out = bytes([status, 1]) + offset_or_size.to_bytes(w, "big") + bytes([0x0F])
            return out

        if op == ci.NVM_OP_OPEN:
            self.nvm_open = True
            return reply(ci.NVM_ST_OK, size)
        if op == ci.NVM_OP_CLOSE:
            self.nvm_open = False
            return reply(ci.NVM_ST_OK, 0)
        if not self.nvm_open:
            return reply(0x02, 0)               # operation mismatch
        length = payload[1]
        offset = int.from_bytes(payload[2:2 + w], "big")
        if op == ci.NVM_OP_READ:
            if length == 0xFF and self.empty_probe_replies:
                self.empty_probe_replies -= 1
                return reply(ci.NVM_ST_OK, offset)
            n = min(length, self.chunk, size - offset)
            data = bytes(self.nvm[offset:offset + n])
            return reply(ci.NVM_ST_EOF if offset + n >= size else ci.NVM_ST_OK, offset, data)
        if op == ci.NVM_OP_WRITE:
            data = payload[2 + w:2 + w + length]
            end = offset + len(data)
            if end >= size:
                self.tail_writes_declined += 1
                return reply(ci.NVM_ST_EOF, offset)            # the last chunk: not written
            if end > size - 2 or offset >= size - 2:
                self.hung = True                                # what the ZST39 did to a 1-byte write at size-2
                return None
            self.nvm[offset:end] = data
            self.write_count += 1
            return reply(ci.NVM_ST_OK, offset)
        return reply(0x04, 0)
