#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_controller_image.py
# Description: Contract tests for the pure core against the scripted stick:
#              framing vectors, the parser under unsolicited / corrupt / CAN
#              traffic, identity from Gen5-shaped payloads, adaptive reads, the
#              write path, image checks, sidecars and every restore guard.
# Author:      CliveS & Claude Fable 5.1
# Date:        14-09-2026 16:30
# Version:     1.1.0

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_stick import GEN5, STICK700, ZST39, FakeStick, FakeStick700, ci, request_frame, response_frame  # noqa: E402


def api_for(stick):
    api = ci.SerialApi(stick, sleep=lambda s: None)
    return api


# ---------------------------------------------------------------- framing

def test_memory_get_id_frame_is_the_well_known_vector():
    assert ci.build_frame(0x20) == bytes.fromhex("01030020DC")


def test_read_request_layout_is_offset3_length2():
    fr = ci.build_frame(ci.F_EXT_NVM_READ, (0x10).to_bytes(3, "big") + (48).to_bytes(2, "big"))
    assert fr[2:9] == bytes([ci.REQ, ci.F_EXT_NVM_READ, 0x00, 0x00, 0x10, 0x00, 0x30])
    assert ci.checksum_ok(fr[1], fr[2:])


def test_parser_acks_and_drops_an_unsolicited_frame():
    stick = FakeStick()
    stick.unsolicited_before_next = [(0x04, bytes([0x00, 0x05, 0x03, 0x20, 0x01, 0xFF]))]
    api = api_for(stick)
    payload = api.request(ci.F_MEMORY_GET_ID)
    assert payload == GEN5["homeId"] + bytes([1])
    assert api.unsolicited == 1
    assert stick.acks_received == 2        # one for the unsolicited frame, one for our response


def test_parser_naks_a_corrupt_frame_and_takes_the_good_one():
    stick = FakeStick()
    stick.corrupt_next_response = True
    api = api_for(stick)
    assert api.request(ci.F_MEMORY_GET_ID) == GEN5["homeId"] + bytes([1])
    assert stick.naks_received == 1


def test_parser_resends_after_a_can():
    stick = FakeStick()
    stick.can_next_request = True
    api = api_for(stick)
    assert api.request(ci.F_GET_SUC_NODE_ID) == bytes([1])
    assert [f for f, _ in stick.requests] == [ci.F_GET_SUC_NODE_ID, ci.F_GET_SUC_NODE_ID]


def test_no_response_raises_after_five_attempts():
    class Mute(FakeStick):
        def _respond(self, func, payload):
            return None
    api = ci.SerialApi(Mute(), sleep=lambda s: None)
    try:
        api.request(ci.F_GET_SUC_NODE_ID, ack_timeout=0.01, res_timeout=0.01)
    except RuntimeError as e:
        assert "5 attempts" in str(e)
    else:
        raise AssertionError("a silent stick must raise")


def test_soft_reset_is_acked_without_a_response():
    stick = FakeStick()
    api = api_for(stick)
    assert ci.soft_reset(api) is True
    assert stick.requests[-1][0] == ci.F_SOFT_RESET


# ---------------------------------------------------------------- identity

def test_identity_from_gen5_shaped_payloads():
    ident = ci.read_identity(api_for(FakeStick()))
    assert ident["libraryVersionString"] == "Z-Wave 4.54"
    assert ident["protocolVersion"] == "4.54"
    assert ident["sdkVersion"] == "6.51.10"
    assert ident["homeId"] == "E0BB7FA8" and ident["ownNodeId"] == 1
    assert ident["isSUC"] and ident["wasRealPrimary"] and not ident["isSecondary"]
    assert ident["sucNodeId"] == 1
    assert (ident["manufacturerId"], ident["productType"], ident["productId"]) == (0x86, 0x01, 0x5A)
    assert ident["modelName"] == "Aeotec Z-Stick Gen5"
    assert ident["nodeIds"] == GEN5["nodes"]
    assert ident["initIsPrimary"] and ident["initIsSIS"]
    assert (ident["chipType"], ident["chipVersion"]) == (5, 0)
    assert ci.is_500_series(ident)
    assert ci.software_description(ident) == "Z-Wave 4.54 (SDK 6.51.10)"


def test_a_700_series_stick_is_recognised_and_refused():
    ident = {"libraryVersionString": "Z-Wave 7.19"}
    assert not ci.is_500_series(ident)
    assert not ci.is_500_series({"libraryVersionString": ""})


def test_gen5_plus_maps_to_sdk_6_81():
    assert ci.sdk_version("Z-Wave 6.07") == "6.81.6"


def test_chunk_size_is_48_for_the_gen5_and_168_otherwise():
    assert ci.initial_chunk_for({"manufacturerId": 0x86, "productType": 1, "productId": 0x5A}) == 48
    assert ci.initial_chunk_for({"manufacturerId": 0x12, "productType": 1, "productId": 1}) == 168


def test_nvm_id_size_code_18_is_256k():
    nvm = ci.read_nvm_id(api_for(FakeStick()))
    assert nvm["sizeBytes"] == 262144 and nvm["memorySizeCode"] == 18


# ---------------------------------------------------------------- reads

def test_dump_reads_the_whole_memory_exactly():
    stick = FakeStick()
    image = ci.dump_nvm(api_for(stick), 262144, 48)
    assert image == bytes(stick.nvm)


def test_dump_adapts_to_a_stick_that_answers_with_fewer_bytes():
    stick = FakeStick(max_read=32)
    api = api_for(stick)
    image = ci.dump_nvm(api, 4096, 168)
    assert image == bytes(stick.nvm[:4096])
    lengths = {int.from_bytes(p[3:5], "big") for f, p in stick.requests if f == ci.F_EXT_NVM_READ}
    assert max(lengths) == 168 and 32 in lengths   # first ask was big, then it settled on what came back


def test_dump_falls_back_to_48_after_an_empty_reply():
    stick = FakeStick(max_read=168)
    stick.reads_before_empty = 2
    image = ci.dump_nvm(api_for(stick), 2048, 168)
    assert image == bytes(stick.nvm[:2048])
    lengths = [int.from_bytes(p[3:5], "big") for f, p in stick.requests if f == ci.F_EXT_NVM_READ]
    assert 48 in lengths


def test_dump_stops_when_asked():
    stick = FakeStick()
    try:
        ci.dump_nvm(api_for(stick), 262144, 48, should_stop=lambda: True)
    except RuntimeError as e:
        assert "stopped" in str(e)
    else:
        raise AssertionError("should_stop must abort the read")


def test_progress_is_reported_every_ten_percent():
    seen = []
    ci.dump_nvm(api_for(FakeStick()), 4800, 48, progress=lambda d, t: seen.append(d * 100 // t))
    assert seen[0] == 10 and seen[-1] == 100 and len(seen) == 10


# ---------------------------------------------------------------- writes

def test_write_uses_probe_minus_five_and_lands_every_byte():
    stick = FakeStick()
    original = bytes(stick.nvm)
    new = bytearray(original)
    new[12:1012] = bytes((i * 3) & 0xFF for i in range(1000))
    api = api_for(stick)
    written, skipped = ci.write_nvm(api, bytes(new), 48)
    assert written == len(new) and skipped == []
    assert bytes(stick.nvm) == bytes(new)
    sizes = {int.from_bytes(p[3:5], "big") for f, p in stick.requests if f == ci.F_EXT_NVM_WRITE}
    assert max(sizes) == 43                     # 48-byte probe reply minus the 5-byte header


def test_write_refused_by_the_controller_raises_when_the_bytes_differ():
    stick = FakeStick(refuse_writes=True)
    image = bytearray(stick.nvm)
    image[20] ^= 0xFF
    try:
        ci.write_nvm(api_for(stick), bytes(image), 48)
    except RuntimeError as e:
        assert "refused the write at offset 20" in str(e) and "differs" in str(e)
    else:
        raise AssertionError("a refused write of differing bytes must raise")


def test_write_refused_everywhere_but_already_matching_is_not_a_failure():
    stick = FakeStick(refuse_writes=True)
    written, skipped = ci.write_nvm(api_for(stick), bytes(stick.nvm), 48)
    assert written == len(stick.nvm)
    assert sum(n for _o, n in skipped) == len(stick.nvm)     # every piece proven by read-back


# ---------------------------------------------------------------- checks, sidecars, guards

def test_image_checks_pass_on_a_real_shaped_image():
    stick = FakeStick()
    checks, problems = ci.image_checks(bytes(stick.nvm), 262144, "E0BB7FA8")
    assert problems == []
    assert checks["homeIdOffsets"] == [8] and checks["sizeMatchesNvmId"]


def test_image_checks_flag_blank_wrong_size_and_missing_home_id():
    _c, problems = ci.image_checks(b"\xff" * 1000, 262144, "E0BB7FA8")
    assert any("blank" in p for p in problems)
    assert any("262144" in p for p in problems)
    assert any("Home ID" in p for p in problems)


def test_compare_images_counts_and_locates():
    d = ci.compare_images(b"abcdef", b"abXdeY")
    assert d == {"differingBytes": 2, "firstDifference": 2}
    assert ci.compare_images(b"abc", b"abc") == {"differingBytes": 0, "firstDifference": None}
    assert ci.compare_images(b"abc", b"abcd")["differingBytes"] == 1


def test_image_filename_is_model_home_and_time():
    ident = {"modelName": "Aeotec Z-Stick Gen5", "homeId": "E0BB7FA8"}
    when = datetime.datetime(2026, 9, 13, 12, 5)
    assert ci.image_filename(ident, when) == "Aeotec-Z-Stick-Gen5_E0BB7FA8_2026-09-13_1205"


def _sidecar(tmp_path, ident=None, size=262144):
    ident = ident or ci.read_identity(api_for(FakeStick()))
    nvm = {"nvmManufacturerId": 31, "memoryType": 129, "memorySizeCode": 18, "sizeBytes": size}
    image = os.path.join(tmp_path, "img.bin")
    with open(image, "wb") as fh:
        fh.write(bytes(FakeStick.default_nvm(size)))
    side = ci.sidecar_for(ident, nvm, {"sha256": "x"}, image, "/dev/cu.usbmodem101",
                          datetime.datetime(2026, 9, 13, 12, 0), "1.0.0", "2025.2.0", True)
    with open(ci.sidecar_path_for(image), "w") as fh:
        json.dump(side, fh)
    return image, side, ident, nvm


def test_sidecar_round_trips_and_lists_newest_first(tmp_path):
    a, _s, _i, _n = _sidecar(tmp_path)
    older = os.path.join(tmp_path, "older.bin")
    with open(older, "wb") as fh:
        fh.write(b"\x00" * 10)
    with open(ci.sidecar_path_for(older), "w") as fh:
        json.dump({"takenAt": "2026-01-01T00:00:00", "identity": {}}, fh)
    with open(os.path.join(tmp_path, "stray.bin"), "wb") as fh:
        fh.write(b"\x00")                       # no sidecar: must be ignored
    listed = ci.list_images(str(tmp_path))
    assert [os.path.basename(p) for p, _ in listed] == ["img.bin", "older.bin"]
    assert ci.load_sidecar(a)["identity"]["homeId"] == "E0BB7FA8"


def test_restore_guards_pass_for_the_same_stick(tmp_path):
    image, side, ident, nvm = _sidecar(tmp_path)
    assert ci.restore_refusals(open(image, "rb").read(), side, ident, nvm) == []


def test_restore_guard_refuses_a_missing_sidecar(tmp_path):
    image, side, ident, nvm = _sidecar(tmp_path)
    reasons = ci.restore_refusals(open(image, "rb").read(), None, ident, nvm)
    assert len(reasons) == 1 and "sidecar" in reasons[0]


def test_restore_guard_refuses_a_size_mismatch(tmp_path):
    image, side, ident, nvm = _sidecar(tmp_path)
    reasons = ci.restore_refusals(open(image, "rb").read(), side, ident, dict(nvm, sizeBytes=131072))
    assert any("131072" in r for r in reasons)


def test_restore_guard_refuses_another_model(tmp_path):
    image, side, ident, nvm = _sidecar(tmp_path)
    other = dict(ident, productId=0x01, modelName="Z-Wave controller 0086:0001:0001")
    reasons = ci.restore_refusals(open(image, "rb").read(), side, other, nvm)
    assert any("another model" in r or "came from" in r for r in reasons)


def test_restore_guard_refuses_another_software_version(tmp_path):
    image, side, ident, nvm = _sidecar(tmp_path)
    other = dict(ident, libraryVersionString="Z-Wave 6.07")
    reasons = ci.restore_refusals(open(image, "rb").read(), side, other, nvm)
    assert any("memory layout differs" in r for r in reasons)


def test_restore_guard_home_id_needs_the_replacement_tick(tmp_path):
    image, side, ident, nvm = _sidecar(tmp_path)
    other = dict(ident, homeId="11223344")
    data = open(image, "rb").read()
    assert any("Replacement stick" in r for r in ci.restore_refusals(data, side, other, nvm))
    assert ci.restore_refusals(data, side, other, nvm, replacement_ok=True) == []


# ---------------------------------------------------------------- Indigo prefs, port holders

def test_zwave_port_and_home_id_read_from_indigo_prefs(tmp_path):
    pref = os.path.join(tmp_path, "zwave.indiPref")
    with open(pref, "w") as fh:
        fh.write('<?xml version="1.0"?><Prefs type="dict">'
                 '<HomeE0BB7FA8_Node005 type="bool">true</HomeE0BB7FA8_Node005>'
                 '<interfacePort_serialConnType type="string">local</interfacePort_serialConnType>'
                 '<interfacePort_serialPortLocal type="string">/dev/cu.usbmodem101</interfacePort_serialPortLocal>'
                 '</Prefs>')
    assert ci.zwave_port_from_prefs(pref) == ("/dev/cu.usbmodem101", "local", "E0BB7FA8")
    assert ci.zwave_port_from_prefs(os.path.join(tmp_path, "missing")) == (None, None, None)


def test_every_home_id_in_indigo_prefs_is_known_not_just_the_first(tmp_path):
    """A real prefs file (14-09-2026) carried five Home IDs from past networks; the first was
    not the live one, and the plugin warned about a mismatch that was not there."""
    pref = os.path.join(tmp_path, "zwave.indiPref")
    with open(pref, "w") as fh:
        fh.write('<?xml version="1.0"?><Prefs type="dict">'
                 '<Home0161EC56_Node003 type="bool">true</Home0161EC56_Node003>'
                 '<HomeE1C3BDE8_Node012 type="bool">true</HomeE1C3BDE8_Node012>'
                 '<HomeE1C3BDE8_Node013 type="bool">true</HomeE1C3BDE8_Node013>'
                 '</Prefs>')
    assert ci.zwave_home_ids_from_prefs(pref) == {"0161EC56", "E1C3BDE8"}
    assert ci.zwave_home_ids_from_prefs(os.path.join(tmp_path, "missing")) == set()


def test_folder_path_is_cleaned_and_must_be_absolute():
    """Pasted in shell quotes, a relative path put the images inside the plugin bundle (14-09-2026)."""
    assert ci.clean_folder_path("'/Users/me/Z-Wave Backups'") == "/Users/me/Z-Wave Backups"
    assert ci.clean_folder_path('  "/Users/me/x"  ') == "/Users/me/x"
    assert ci.clean_folder_path("~/x").startswith("/") and ci.clean_folder_path("~/x").endswith("/x")
    assert ci.clean_folder_path("relative/path") == ""
    assert ci.clean_folder_path("'relative'") == ""
    assert ci.clean_folder_path("") == "" and ci.clean_folder_path(None) == ""


def test_port_holders_is_empty_when_lsof_is_unavailable(monkeypatch):
    monkeypatch.setattr(ci, "LSOF", "/nonexistent/lsof")
    assert ci.port_holders("/dev/cu.nothing") == []


def test_frames_helpers_agree_with_the_core():
    # the fake's frame builders must produce what the core parses, or every test above lies
    fr = response_frame(0x20, b"\x01\x02")
    assert ci.checksum_ok(fr[1], fr[2:])
    assert request_frame(0x20, b"") == ci.build_frame(0x20)


def test_soft_reset_is_skipped_only_for_the_known_bad_sticks():
    assert ci.soft_reset_allowed({"manufacturerId": 0x86, "productType": 1, "productId": 0x5A})
    assert not ci.soft_reset_allowed({"manufacturerId": 0x0115, "productType": 0x0400, "productId": 0x0001})
    assert not ci.soft_reset_allowed({"manufacturerId": 0x0109, "productType": 0x1001, "productId": 0x0201})


def test_parser_waits_on_the_port_when_it_can_rather_than_sleeping():
    class WaitingStick(FakeStick):
        def __init__(self):
            super().__init__()
            self.waits = []
            self.held = None
        def write(self, data):
            # hold the reply back until the parser waits for it, as a real port would
            self.inbox += data
            self.held = True
        def wait_readable(self, timeout):
            self.waits.append(timeout)
            if self.held:
                self.held = False
                self._pump()
            return bool(self.outbox)
    stick = WaitingStick()
    slept = []
    api = ci.SerialApi(stick, sleep=lambda s: slept.append(s))
    assert api.request(ci.F_GET_SUC_NODE_ID) == bytes([1])
    assert stick.waits and all(0 < w <= 0.25 for w in stick.waits)
    assert slept == []                       # never fell back to sleeping


def test_real_port_wait_readable_returns_false_when_closed():
    port = ci.SerialPort("/dev/null-not-a-port")
    assert port.wait_readable(0.01) is False


def test_write_accepts_a_refused_tail_that_already_matches():
    """The Gen5 refuses the last 16 bytes of its NVM (13-09-2026). They are blank flash in
    every image, so a refusal there is only a fault if the bytes differ."""
    stick = FakeStick(refuse_tail=16)
    image = bytes(stick.nvm)
    written, skipped = ci.write_nvm(api_for(stick), image, 48)
    assert written == len(image)
    assert skipped == [(262128, 16)]


def test_write_refused_tail_that_differs_is_a_real_failure():
    stick = FakeStick(refuse_tail=16)
    image = bytearray(stick.nvm)
    image[-1] = 0x00                    # the image wants something the stick will not take
    try:
        ci.write_nvm(api_for(stick), bytes(image), 48)
    except RuntimeError as e:
        assert "differs from the image" in str(e)
    else:
        raise AssertionError("a refused write of differing bytes must raise")


def test_read_exact_assembles_across_chunks():
    stick = FakeStick(max_read=48)
    assert ci.read_exact(api_for(stick), 100, 200) == bytes(stick.nvm[100:300])


def test_reset_parser_swallows_a_stick_still_talking_and_acks_it():
    stick = FakeStick()
    # the stick is mid-reply to the previous host when we open: two whole frames already queued
    stick.outbox += response_frame(0x02, bytes([5, 8, 29]) + bytes(29) + bytes([5, 0]))
    stick.outbox += request_frame(0x04, bytes([0, 5, 3, 0x20, 1, 0xFF]))
    api = ci.SerialApi(stick, sleep=lambda s: None)
    api.reset_parser(quiet=0.01, limit=0.5)
    assert stick.naks_received == 1              # the resync NAK
    assert stick.acks_received == 2              # both stale frames ACKed so they are not resent
    assert api.buf == bytearray()
    assert api.request(ci.F_GET_SUC_NODE_ID) == bytes([1])


def test_request_survives_a_burst_of_cans_then_succeeds():
    class Colliding(FakeStick):
        def __init__(self):
            super().__init__()
            self.cans_left = 3
        def _pump(self):
            # answer the first three requests with CAN plus the frame that caused it
            while self.inbox and self.cans_left and self.inbox[0] == ci.SOF and len(self.inbox) >= 2 + self.inbox[1]:
                length = self.inbox[1]
                del self.inbox[:2 + length]
                self.cans_left -= 1
                self.outbox += bytes([ci.CAN]) + request_frame(0x04, bytes([0, 5, 3, 0x20, 1, 0xFF]))
            super()._pump()
    stick = Colliding()
    api = ci.SerialApi(stick, sleep=lambda s: None)
    assert api.request(ci.F_GET_SUC_NODE_ID) == bytes([1])
    assert api.unsolicited == 3                  # each collision's frame was taken in and ACKed


def test_request_failure_names_what_happened():
    class Muted(FakeStick):
        def _respond(self, func, payload):
            return None
    api = ci.SerialApi(Muted(), sleep=lambda s: None)
    try:
        api.request(ci.F_GET_SUC_NODE_ID, ack_timeout=0.01, res_timeout=0.01, attempts=2)
    except RuntimeError as e:
        assert "2 attempts" in str(e) and "no reply" in str(e)
    else:
        raise AssertionError("must raise")


# ---------------------------------------------------------------- 700 / 800 series

def test_identity_from_zst39_shaped_payloads():
    ident = ci.read_identity(api_for(FakeStick700()))
    assert ident["libraryVersionString"] == "Z-Wave 7.24"
    assert ident["protocolVersionFull"] == "7.24.2"
    assert ident["homeId"] == "E2DAD17B" and ident["ownNodeId"] == 1 and ident["sucNodeId"] == 1
    assert ident["modelName"] == "Zooz ZST39 LR"
    assert (ident["chipType"], ident["chipVersion"]) == (8, 0)
    assert ident["nodeIds"] == ZST39["nodes"]
    assert 0x2E in ident["supportedFunctionIds"] and 0x3D in ident["supportedFunctionIds"]
    assert not ci.is_500_series(ident) and ci.is_700_series(ident)
    assert ci.series_of(ident) == 800
    assert ci.nvm_function_for(ident) == ci.F_EXT_NVM_OPERATIONS
    assert ci.software_description(ident) == "Z-Wave 7.24 (SDK 7.24.2)"


def test_identity_from_a_700_stick_uses_the_16_bit_function():
    ident = ci.read_identity(api_for(FakeStick700(profile=STICK700)))
    assert ident["libraryVersionString"] == "Z-Wave 7.17" and ident["protocolVersionFull"] == "7.17.1"
    assert ci.series_of(ident) == 700
    assert 0x3D not in ident["supportedFunctionIds"]
    assert ci.nvm_function_for(ident) == ci.F_NVM_OPERATIONS
    assert ident["modelName"] == "Silicon Labs 700 series stick"


def test_node_ids_are_parsed_by_length_in_16_bit_mode():
    """zwave-js leaves 700+ sticks in 16-bit node id mode; MemoryGetId then answers 6 bytes."""
    ident = ci.read_identity(api_for(FakeStick700(node_id_bits=16)))
    assert ident["ownNodeId"] == 1 and ident["sucNodeId"] == 1
    assert ci.node_id_from(bytes.fromhex("e2dad17b01"), 4) == 1
    assert ci.node_id_from(bytes.fromhex("e2dad17b0001"), 4) == 1
    assert ci.node_id_from(bytes.fromhex("e2dad17b0102"), 4) == 0x0102


def test_function_bitmask_bit_n_minus_1_is_function_n():
    caps = bytes(8) + bytes([0b00000001, 0b10000000]) + bytes(30)
    assert ci.parse_function_bitmask(caps) == [1, 16]


def test_500_series_identity_is_unchanged_by_the_new_fields():
    ident = ci.read_identity(api_for(FakeStick()))
    assert ident["protocolVersionFull"] is None and ident["supportedFunctionIds"] == []
    assert ci.series_of(ident) == 500 and not ci.is_700_series(ident)


def test_nvm_session_turns_the_radio_off_and_the_reset_brings_the_stick_back():
    stick = FakeStick700()
    api = api_for(stick)
    ci.begin_nvm_session_700(api)
    assert not stick.radio_on and not stick.watchdog_on
    assert ci.end_nvm_session_700(api) is True          # SerialAPIStarted seen
    assert stick.radio_on and stick.watchdog_on and stick.resets == 1


def test_dump_700_reads_the_whole_nvm_in_the_sticks_chunk_via_0x3d():
    stick = FakeStick700()
    api = api_for(stick)
    size = ci.read_nvm_id_700(api, ci.F_EXT_NVM_OPERATIONS)["sizeBytes"]
    assert size == 40960
    img = ci.dump_nvm_700(api, ci.F_EXT_NVM_OPERATIONS, size)
    assert img == bytes(stick.nvm)
    reads = [pl for f, pl in stick.requests if f == ci.F_EXT_NVM_OPERATIONS and pl[0] == ci.NVM_OP_READ]
    assert reads[0][1] == 0xFF and reads[1][1] == 64          # probe, then the stick's chunk
    assert stick.requests[-1] == (ci.F_EXT_NVM_OPERATIONS, bytes([ci.NVM_OP_CLOSE]))


def test_dump_700_via_0x2e_uses_two_byte_offsets():
    stick = FakeStick700(profile=STICK700)
    api = api_for(stick)
    size = ci.read_nvm_id_700(api, ci.F_NVM_OPERATIONS)["sizeBytes"]
    img = ci.dump_nvm_700(api, ci.F_NVM_OPERATIONS, size)
    assert img == bytes(stick.nvm) and len(img) == 49152
    reads = [pl for f, pl in stick.requests if f == ci.F_NVM_OPERATIONS and pl[0] == ci.NVM_OP_READ]
    assert len(reads[1]) == 1 + 1 + 2 and int.from_bytes(reads[1][2:4], "big") == 64


def test_dump_700_falls_back_to_48_when_the_probe_comes_back_empty():
    stick = FakeStick700()
    stick.empty_probe_replies = 1
    api = api_for(stick)
    img = ci.dump_nvm_700(api, ci.F_EXT_NVM_OPERATIONS, 40960)
    assert img == bytes(stick.nvm)
    reads = [pl for f, pl in stick.requests if f == ci.F_EXT_NVM_OPERATIONS and pl[0] == ci.NVM_OP_READ]
    assert reads[1][1] == 48


def test_dump_700_refuses_a_size_that_moved():
    import pytest
    with pytest.raises(RuntimeError):
        ci.dump_nvm_700(api_for(FakeStick700()), ci.F_EXT_NVM_OPERATIONS, 12345)


def test_write_700_lands_every_byte_but_the_declined_tail_and_never_touches_the_last_two():
    stick = FakeStick700()
    original = bytes(stick.nvm)
    image = bytearray(original)
    for i in range(20, 4000):
        image[i] ^= 0x5A
    api = api_for(stick)
    written, declined = ci.write_nvm_700(api, ci.F_EXT_NVM_OPERATIONS, bytes(image))
    assert (written, declined) == (40960 - 64, 64)
    assert stick.tail_writes_declined == 1
    assert not stick.hung                                   # no split-and-retry into the tail
    assert bytes(stick.nvm[:-64]) == bytes(image[:-64])
    assert bytes(stick.nvm[-64:]) == original[-64:]         # the tail is what it was
    writes = [pl for f, pl in stick.requests if f == ci.F_EXT_NVM_OPERATIONS and pl[0] == ci.NVM_OP_WRITE]
    assert all(pl[1] == 64 for pl in writes)


def test_write_700_refuses_an_image_of_the_wrong_size():
    import pytest
    with pytest.raises(RuntimeError):
        ci.write_nvm_700(api_for(FakeStick700()), ci.F_EXT_NVM_OPERATIONS, b"\xff" * 100)


def test_a_write_into_the_tail_would_hang_the_fake_as_it_hung_the_real_stick():
    """Documents the hazard the write path is built to avoid."""
    stick = FakeStick700()
    nvm = ci.Nvm700(api_for(stick))
    nvm.open()
    import pytest
    with pytest.raises(RuntimeError):
        nvm.write(40960 - 2, b"\x00")
    assert stick.hung


def test_compare_700_explains_housekeeping_and_tail_but_not_real_differences():
    image = bytes([0x11] * 100 + [0xFF] * 50 + [0x22] * 64)
    current = bytearray(image)
    current[110:120] = b"\xd7" * 10               # the firmware wrote into erased space
    current[-64:] = b"\xff" * 64                   # the declined tail
    d = ci.compare_images_700(image, bytes(current), declined_tail=64)
    assert (d["housekeepingBytes"], d["tailBytes"], d["unexplainedBytes"]) == (10, 64, 0)
    current[5] = 0x00                              # a real difference
    d = ci.compare_images_700(image, bytes(current), declined_tail=64)
    assert d["unexplainedBytes"] == 1 and d["firstDifference"] == 5
    assert ci.compare_images_700(image, image)["differingBytes"] == 0


def test_restore_guard_refuses_a_different_full_sdk_on_the_same_library_string(tmp_path):
    ident = ci.read_identity(api_for(FakeStick700()))
    nvm = {"sizeBytes": 40960}
    image = b"\xff" * 40960
    side = {"identity": dict(ident)}
    assert ci.restore_refusals(image, side, ident, nvm) == []
    side["identity"]["protocolVersionFull"] = "7.19.0"
    reasons = ci.restore_refusals(image, side, ident, nvm)
    assert len(reasons) == 1 and "7.19.0" in reasons[0]


def test_image_checks_pass_on_an_nvm3_shaped_image():
    stick = FakeStick700()
    checks, problems = ci.image_checks(bytes(stick.nvm), 40960, "E2DAD17B")
    assert problems == [] and checks["homeIdOccurrences"] >= 1
