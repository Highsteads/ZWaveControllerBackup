#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    fake_stick.py
# Description: A scripted 500-series controller behind a read()/write() port, for
#              the contract tests. Answers the Serial API functions the plugin
#              uses with payloads shaped exactly like the live Aeotec Gen5's
#              (captured 12-09-2026), serves NVM reads from a bytearray, applies
#              writes to it, and can inject unsolicited frames, a corrupt frame,
#              a CAN, or empty NVM replies to exercise the parser's rough edges.
# Author:      CliveS & Claude Fable 5.1
# Date:        13-09-2026 12:30
# Version:     1.0.0

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
