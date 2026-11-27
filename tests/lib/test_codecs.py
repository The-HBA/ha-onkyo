"""Codecs: every value kind, the TX-RZ50's real answers, and bad input."""

from pathlib import Path

import pytest

from custom_components.onkyo_eiscp.lib import codecs
from custom_components.onkyo_eiscp.lib.codecs import (
    AudioInfo,
    DiracState,
    Tone,
    TonePart,
    VideoInfo,
    decode,
    encode,
)
from custom_components.onkyo_eiscp.lib.commands import COMMANDS, Command
from custom_components.onkyo_eiscp.lib.exceptions import CodecError

NRI = (Path(__file__).parents[1] / "fixtures" / "tx-rz50" / "nri.xml").read_text(encoding="utf-8")


def cmd(code: str) -> Command:
    return COMMANDS[code]


# ----- enum, hex, numbers ------------------------------------------------------------------


def test_enum_maps_to_the_option_key_and_back() -> None:
    assert decode(cmd("AMT"), "01") == "on"
    assert encode(cmd("AMT"), "off") == "00"
    assert decode(cmd("DIM"), "08") == "bright_led_off"
    assert encode(cmd("PWR"), "standby") == "00"


def test_enum_without_options_keeps_the_raw_parameter() -> None:
    assert decode(cmd("SLI"), "2B") == "2B"
    assert encode(cmd("SLI"), "2B") == "2B"
    assert decode(cmd("DIM"), "77") == "77"


def test_enum_accepts_a_raw_parameter_and_rejects_an_unknown_key() -> None:
    assert encode(cmd("AMT"), "01") == "01"
    with pytest.raises(CodecError):
        encode(cmd("AMT"), "loud")


def test_hex_volume() -> None:
    assert decode(cmd("MVL"), "7C") == 124
    assert encode(cmd("MVL"), 124) == "7C"
    assert encode(cmd("MVL"), 4) == "04"
    assert decode(cmd("VOC"), "05") == 5


def test_volume_helpers() -> None:
    assert codecs.volume_db(0x7C, half_db=True) == -20.0
    assert codecs.volume_db(0x7C, half_db=False) is None
    assert codecs.volume_fraction(100, 200) == 0.5
    assert codecs.volume_fraction(300, 200) == 1.0
    assert codecs.volume_fraction(5, 0) == 0.0
    assert codecs.volume_raw(0.5, 200) == 100
    assert codecs.volume_raw(2.0, 200) == 200
    assert codecs.volume_raw(-1.0, 200) == 0


@pytest.mark.parametrize(
    ("param", "db"), [("-0A", -5.0), ("-09", -4.5), ("000", 0.0), ("+18", 12.0), ("-1E", -15.0)]
)
def test_signed_hex_level_in_db(param: str, db: float) -> None:
    assert decode(cmd("SWL"), param) == db
    assert encode(cmd("SWL"), db) == param


def test_signed_hex_zero_forms_and_errors() -> None:
    assert decode(cmd("CTL"), "00") == 0
    assert encode(cmd("CTL"), 0) == "000"
    with pytest.raises(CodecError):
        decode(cmd("SWL"), "12")
    with pytest.raises(CodecError):
        decode(cmd("SWL"), "-ZZ")


@pytest.mark.parametrize(("param", "ms"), [("+005", 5), ("-100", -100), ("0000", 0), ("+500", 500)])
def test_signed_decimal_delay(param: str, ms: int) -> None:
    assert decode(cmd("AVS"), param) == ms
    assert encode(cmd("AVS"), ms) == param


def test_sleep_timer() -> None:
    assert decode(cmd("SLP"), "OFF") == 0
    assert decode(cmd("SLP"), "1E") == 30
    assert encode(cmd("SLP"), 0) == "OFF"
    assert encode(cmd("SLP"), 30) == "1E"
    assert encode(cmd("SLP"), 90) == "5A"


def test_tone_pair_and_one_sided_set() -> None:
    assert decode(cmd("TFR"), "B-2T00") == Tone(-2, 0)
    assert decode(cmd("TFR"), "B+AT-A") == Tone(10, -10)
    assert encode(cmd("TFR"), TonePart("bass", 1)) == "B+1"
    assert encode(cmd("TFR"), TonePart("treble", -10)) == "T-A"
    assert encode(cmd("TFR"), TonePart("treble", 0)) == "T00"
    with pytest.raises(CodecError):
        encode(cmd("TFR"), 1)
    for bad in ("B-2", "BxxT00", "B-2T0"):
        with pytest.raises(CodecError):
            decode(cmd("TFR"), bad)


def test_dirac_slots() -> None:
    assert decode(cmd("DSS"), "112") == DiracState("slot_3", ("slot_1", "slot_2", "slot_3"))
    assert decode(cmd("DSS"), "211").active == "slot_1"
    assert decode(cmd("DSS"), "121").active == "slot_2"
    assert decode(cmd("DSS"), "111") == DiracState("off", ("slot_1", "slot_2", "slot_3"))
    assert decode(cmd("DSS"), "102") == DiracState("slot_3", ("slot_1", "slot_3"))
    assert encode(cmd("DSS"), "off") == "C00"
    assert encode(cmd("DSS"), "slot_3") == "C03"
    with pytest.raises(CodecError):
        encode(cmd("DSS"), "slot_9")
    with pytest.raises(CodecError):
        decode(cmd("DSS"), "1x2")


# ----- text fields -------------------------------------------------------------------------


def test_audio_info() -> None:
    info = decode(cmd("IFA"), "HDMI 1,Dolby Atmos/TrueHD,48 kHz,,Dolby Atmos,6.1 ch,")
    assert info == AudioInfo("HDMI 1", "Dolby Atmos/TrueHD", "48 kHz", "", "Dolby Atmos", "6.1 ch")
    assert isinstance(info, AudioInfo)
    assert info.summary == "Dolby Atmos/TrueHD 48 kHz"


def test_audio_info_with_missing_fields_and_no_signal() -> None:
    info = codecs.parse_audio_info("ANALOG,,,,DTS Neural:X,6.1 ch,")
    assert info.input_format == ""
    assert info.summary == ""
    assert info.listening_mode == "DTS Neural:X"
    assert codecs.parse_audio_info("HDMI 1") == AudioInfo(input_port="HDMI 1")


def test_video_info() -> None:
    text = "HDMI 1,4K(3840x2160) 23 Hz,RGB,24bit,MAIN,4K(3840x2160) 23 Hz,RGB,24bit,,Dolby Vision,"
    info = decode(cmd("IFV"), text)
    assert isinstance(info, VideoInfo)
    assert info.input_resolution == "4K(3840x2160) 23 Hz"
    assert info.output == "MAIN"
    assert info.hdr == "Dolby Vision"
    assert info.summary == "4K(3840x2160) 23 Hz Dolby Vision"
    assert codecs.parse_video_info("HDMI 1,1080p").summary == "1080p"


def test_temperature() -> None:
    assert decode(cmd("TPD"), "F 86C 30") == 30.0
    assert decode(cmd("TPD"), "F 84C 29") == 29.0
    assert decode(cmd("TPD"), "-") is None


def test_plain_text_codes_stay_text() -> None:
    assert decode(cmd("FWV"), "R145111912840034") == "R145111912840034"


def test_front_display() -> None:
    assert decode(cmd("FLD"), "4D6F766965202020202D34342E30") == "Movie    -44.0"
    assert codecs.decode_display("2D3495") == "-4.5"  # \x95 is ".5"
    assert codecs.decode_display("2D3239" + "90") == "-29.0"
    assert codecs.decode_display("1213" + "41746D6F73") == "Atmos"  # Dolby logo dropped
    assert codecs.decode_display("") == ""
    with pytest.raises(CodecError):
        codecs.decode_display("XYZ")


def test_na_cannot_be_decoded() -> None:
    with pytest.raises(CodecError):
        decode(cmd("MVL"), "N/A")


def test_bad_values_raise_codec_error() -> None:
    with pytest.raises(CodecError):
        decode(cmd("MVL"), "ZZ")
    with pytest.raises(CodecError):
        encode(cmd("MVL"), "loud")
    with pytest.raises(CodecError):
        encode(cmd("MVL"), True)  # noqa: FBT003
    with pytest.raises(CodecError):
        encode(cmd("FLD"), "text")  # no encoder


# ----- NRI ---------------------------------------------------------------------------------


def test_device_info_from_the_fixture_nri() -> None:
    info = codecs.parse_device_info(NRI)
    assert (info.brand, info.model, info.year) == ("ONKYO", "TX-RZ50", "2021")
    assert info.mac == "0009B0000001"
    assert info.firmware == "R145-1119-1284-0034-0000"
    assert info.friendly_name == ""
    assert [(z.id, z.enabled, z.volume_max, z.volume_step) for z in info.zones] == [
        ("main", True, 100, 0),
        ("zone2", True, 100, 0),
        ("zone3", True, 100, 0),
        ("zone4", False, 0, 0),
    ]
    inputs = {item.code: item for item in info.inputs}
    assert inputs["10"].name == "Movie"
    assert inputs["2B"].code == "2B"  # upper case SLI form
    assert inputs["2E"].name == "BLUETOOTH"  # value="2" still counts as present
    assert inputs["05"].zones == {"main", "zone2"}
    assert inputs["03"].zones == {"main"}
    assert inputs["80"].zones == {"zone2", "zone3"}


def test_decode_nri_through_the_table() -> None:
    assert isinstance(decode(cmd("NRI"), NRI), codecs.DeviceInfo)


def test_bad_nri_documents() -> None:
    with pytest.raises(CodecError):
        codecs.parse_device_info("not xml")
    with pytest.raises(CodecError):
        codecs.parse_device_info("<response/>")
    odd = (
        "<response><device><zonelist>"
        '<zone id="x" value="q" volmax="z"/></zonelist></device></response>'
    )
    info = codecs.parse_device_info(odd)
    assert info.zones[0].id == "zonex"
    assert info.zones[0].volume_max == 0
    bad_mask = (
        "<response><device><selectorlist>"
        '<selector id="aa" zone="zz"/></selectorlist></device></response>'
    )
    assert codecs.parse_device_info(bad_mask).inputs[0].zones == frozenset()
