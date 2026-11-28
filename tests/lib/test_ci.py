"""CI (config) commands: codec, guards, and a receiver talking to the simulator."""

import json

import pytest
from lib_helpers import FIXTURE

from custom_components.onkyo_eiscp.lib import (
    CiNotAppliedError,
    CiRefusedError,
    CodecError,
    FrameParser,
    NoReplyError,
    Receiver,
    ci,
    encode,
    parse_data,
)
from tools.eiscp_sim import SimServer

RECORDS = json.loads((FIXTURE / "ci.json").read_text(encoding="utf-8"))["records"]

# ----- frame ------------------------------------------------------------------------------------


def test_frame_parses_ci_code_with_prefix() -> None:
    message = parse_data("!1sLCCMMMM1FL+07\x1a\r\n")
    assert (message.code, message.param) == ("sLCC", "MMMM1FL+07")
    message = parse_data("!1sST-PM001\x1a\r\n")
    assert (message.code, message.param) == ("sST-", "PM001")
    assert parse_data("!1MVL28\r").code == "MVL"


def test_frame_round_trip_keeps_trailing_spaces() -> None:
    parser = FrameParser()
    (message,) = parser.feed(encode("sNMCSLAUXNMAUX          "))
    assert message.code == "sNMC"
    assert message.param == "SLAUXNMAUX          "


# ----- decode and encode ------------------------------------------------------------------------


@pytest.mark.parametrize("raw", RECORDS)
def test_every_fixture_record_round_trips(raw: str) -> None:
    record = ci.decode(raw)
    assert record.encode() == raw
    assert record.code in ci.FAMILIES, record.code


def test_decode_keyed_records() -> None:
    lcc = ci.decode("sLCCMMMM1FL+07CT000FR+09HL000HR0002L0002R000SR+07BR+03BL+02SL+06SW-30S2000")
    assert lcc.key == {"MM": "MM1"}
    assert lcc.get("FL") == "+07"
    assert lcc.get("2L") == "000"
    assert lcc.get("SW") == "-30"
    assert "MM" not in lcc.fields
    coc = ci.decode("sCOCDB001MMMM1XT000DL000XMINDFR070CTNONH1NONH2NONSR070SB070LF120")
    assert coc.key == {"MM": "MM1", "XM": "IND"}
    assert coc.get("DB") == "001"
    assert coc.get("LF") == "120"
    toc = ci.decode("sTOCHO001DV001US000SR002ZH000LGENGOD001MO001SS000SLCD HS001")
    assert toc.key == {"SL": "CD"}
    assert toc.get("SL") == "CD "
    assert toc.get("LG") == "ENG"


def test_decode_names_and_odd_widths() -> None:
    nmc = ci.decode("sNMCSLBD NMMovie        ")
    assert nmc.get("NM") == "Movie        "
    assert ci.decode("sSLCSLTUNVSLAS").get("VS") == "LAS"
    wsc = next(ci.decode(r) for r in RECORDS if r.startswith("sWSCSO000"))
    assert wsc.get("OZ") == "000"
    assert len(wsc.get("CD") or "") == 68
    ntc = next(ci.decode(r) for r in RECORDS if r.startswith("sNTC"))
    assert ntc.get("PP") == "1F90    "


def test_decode_unknown_family_uses_width_three() -> None:
    record = ci.decode("sXYZAB001CD002")
    assert record.items == (("AB", "001"), ("CD", "002"))
    assert record.spec is None


def test_decode_rejects_garbage() -> None:
    with pytest.raises(CodecError):
        ci.decode("LCCMMMM1")
    with pytest.raises(CodecError):
        ci.decode("sLCCMM")


def test_signed_helpers() -> None:
    assert ci.format_signed(7) == "+07"
    assert ci.format_signed(-30) == "-30"
    assert ci.format_signed(0) == "000"
    assert ci.parse_signed("-30") == -30
    assert ci.parse_signed("000") == 0
    assert ci.format_number(80) == "080"
    with pytest.raises(CodecError):
        ci.format_signed(100)
    with pytest.raises(CodecError):
        ci.parse_signed("7")


# Messages the survey sent to the real receiver (captures sessions 40 to 52).
SURVEY_SETS = [
    ("NMC", {"NM": "AUX2"}, {"SL": "AUX"}, "sNMCSLAUXNMAUX2         "),
    ("APC", {"AP": "001"}, None, "sAPCAP001"),
    ("AKC", {"DF": "000"}, {"SL": "AUX"}, "sAKCSLAUXDF000"),
    ("VLC", {"VD": "ABS"}, None, "sVLCVDABS"),
    ("ISC", {"AX": "001"}, None, "sISCAX001"),
    ("HLC", {"AL": "001"}, {"SL": "AUX"}, "sHLCSLAUXAL001"),
    ("DSC", {"AR": "001"}, None, "sDSCAR001"),
    ("MZC", {"MV": "080"}, {"ZN": "002"}, "sMZCZN002MV080"),
    ("WSC", {"OZ": "001"}, {"SO": "000"}, "sWSCSO000OZ001"),
    ("IVC", {"IV": "080"}, {"SL": "CD"}, "sIVCSLCD IV080"),
    ("SLC", {"AS": "HDM"}, {"SL": "CD"}, "sSLCSLCD ASHDM"),
    ("AAC", {"CD": "NON"}, None, "sAACCDNON"),
    ("HIC", {"CD": "HI6"}, None, "sHICCDHI6"),
    ("DIC", {"CD": "O2N"}, None, "sDICCDO2N"),
    ("VIC", {"CD": "CV1"}, None, "sVICCDCV1"),
    ("TOC", {"HS": "000"}, {"SL": "CD"}, "sTOCSLCD HS000"),
    ("TOC", {"SS": "003"}, {"SL": "CD"}, "sTOCSLCD SS003"),
    ("EQC", {"B1": "+02"}, {"PS": "003", "CH": "FRT"}, "sEQCPS003CHFRTB1+02"),
    ("SWC", {"L1": "-02"}, None, "sSWCL1-02"),
    ("SWC", {"F1": "080"}, None, "sSWCF1080"),
    ("SCC", {"BR": "001"}, None, "sSCCBR001"),
    ("LCC", {"SW": "-29"}, {"MM": "MM1"}, "sLCCMMMM1SW-29"),
    ("SDC", {"FR": "003"}, {"MM": "MM1"}, "sSDCMMMM1FR003"),
    ("COC", {"FR": "080"}, {"MM": "MM1", "XM": "IND"}, "sCOCMMMM1XMINDFR080"),
]


@pytest.mark.parametrize(("code", "changes", "key", "expected"), SURVEY_SETS)
def test_encode_set_matches_the_survey(
    code: str, changes: dict[str, str], key: dict[str, str] | None, expected: str
) -> None:
    assert ci.encode_set(code, changes, key) == expected


def test_encode_set_pads_names_and_several_fields() -> None:
    assert ci.encode_set("NMC", {"NM": "AUX"}, {"SL": "AUX"}) == "sNMCSLAUXNMAUX          "
    assert ci.encode_set("LCC", {"FL": "+07", "FR": "000"}, {"MM": "OFF"}) == "sLCCMMOFFFL+07FR000"


def test_query_message() -> None:
    assert ci.query_message("APC") == "sAPCQSTN"
    assert ci.query_message("NMC", {"SL": "BD"}) == "sNMCQSTNSLBD "
    assert ci.query_message("COC", {"MM": "MM3", "XM": "DBC"}) == "sCOCQSTNMMMM3XMDBC"
    assert ci.query_message("EQC", {"PS": "001", "CH": "SWF"}) == "sEQCQSTNPS001CHSWF"
    assert ci.query_message("MNC") == "sMN-QSTN"
    assert ci.reply_code("MNC") == "sMNC"


def test_query_needs_its_key() -> None:
    with pytest.raises(CodecError):
        ci.query_message("TOC")
    with pytest.raises(CodecError):
        ci.query_message("COC", {"MM": "MM1"})
    with pytest.raises(CodecError):
        ci.query_message("APC", {"SL": "BD"})
    with pytest.raises(CodecError):
        ci.query_message("TOC", {"SL": "B*D"})


# ----- guards -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "changes", "key"),
    [
        ("CFC", {"IM": "004"}, None),
        ("NTC", {"IP": "C0A80002"}, None),
        ("N2C", {"FN": "x"}, None),
        ("LKC", {"LK": "001"}, None),
        ("LLC", {"LL": "001"}, None),
        ("TNC", {"FS": "010"}, None),
        ("MNC", {"MV": "001"}, None),
        ("ST-", {"PM": "000"}, None),
        ("XYZ", {"AB": "001"}, None),
    ],
)
def test_encoder_refuses_read_only_and_unknown_families(
    code: str, changes: dict[str, str], key: dict[str, str] | None
) -> None:
    with pytest.raises(CiRefusedError):
        ci.encode_set(code, changes, key)


def test_encoder_refuses_read_only_fields() -> None:
    with pytest.raises(CiRefusedError):
        ci.encode_set("APC", {"NS": "000"})  # network standby could cut Home Assistant off
    with pytest.raises(CiRefusedError):
        ci.encode_set("SDC", {"UN": "FTS"}, {"MM": "MM1"})
    with pytest.raises(CiRefusedError):
        ci.encode_set("MMC", {"XI": "000"})


def test_layout_and_network_are_not_exposed() -> None:
    for code in ("CFC", "NTC", "N2C", "LKC"):
        assert code not in ci.EXPOSED
    for code in ("SLC", "HIC", "VIC", "DIC", "AAC", "ISC", "TOC", "LCC", "SDC", "COC", "EQC"):
        assert code in ci.EXPOSED
    for code in ("SWC", "SCC", "AKC", "HLC", "VLC", "APC", "MZC"):
        assert code in ci.EXPOSED


@pytest.mark.parametrize(
    ("code", "changes", "key"),
    [
        ("LCC", {"FL": "7"}, {"MM": "MM1"}),  # wrong width
        ("LCC", {"FL": "+7a"}, {"MM": "MM1"}),
        ("LCC", {"XX": "+07"}, {"MM": "MM1"}),  # no such field
        ("LCC", {}, {"MM": "MM1"}),  # nothing to change
        ("LCC", {"FL": "+07"}, None),  # key missing
        ("SWC", {"L1": "+02"}, None),  # the receiver ignores a boost
        ("SLC", {"AS": "XXX"}, {"SL": "CD"}),
        ("NMC", {"NM": "a name that is far too long"}, {"SL": "CD"}),
        ("HIC", {"CD": "HDMI"}, None),
    ],
)
def test_encoder_rejects_bad_values(
    code: str, changes: dict[str, str], key: dict[str, str] | None
) -> None:
    with pytest.raises(CodecError):
        ci.encode_set(code, changes, key)


@pytest.mark.parametrize("code", sorted(ci.CALIBRATION))
def test_plan_set_returns_the_restore_command_for_calibration(code: str) -> None:
    before = next(ci.decode(r) for r in RECORDS if r.startswith(f"s{code}") and "MM1" in r)
    field = {"LCC": "SW", "SDC": "FR", "COC": "FR"}[code]
    new = {"LCC": "-29", "SDC": "003", "COC": "080"}[code]
    change = ci.plan_set(before, {field: new})
    assert change.calibration
    assert change.set_message.startswith(f"s{code}MMMM1")
    assert change.set_message.endswith(field + new)
    assert change.restore_message.endswith(field + (before.get(field) or "?"))
    assert change.old == {field: before.get(field)}
    assert change.restore_message.startswith(change.set_message[: len(f"s{code}MMMM1")])


def test_plan_set_restore_for_names_keeps_the_padding() -> None:
    before = ci.decode("sNMCSLAUXNMAUX          ")
    change = ci.plan_set(before, {"NM": "AUX2"})
    assert change.set_message == "sNMCSLAUXNMAUX2         "
    assert change.restore_message == "sNMCSLAUXNMAUX          "
    assert not change.calibration


def test_plan_set_refuses_what_it_cannot_restore() -> None:
    swf = ci.decode("sEQCPS001CHSWFB1000B2000B3000B4000B5000")
    with pytest.raises(CodecError):
        ci.plan_set(swf, {"B9": "+02"})  # not in the subwoofer record
    aux = ci.decode("sTOCHO001DV001US000SR002ZH000LGENGOD001MO001SS000SLAUX")
    with pytest.raises(CodecError):
        ci.plan_set(aux, {"HS": "000"})  # AUX has no HS to restore
    cfc = ci.decode("sCFCSC610SW001H1TMDH2RHIZS000ZP000SB000BA000IM006")
    with pytest.raises(CiRefusedError):
        ci.plan_set(cfc, {"IM": "004"})


def test_key_combinations_cover_each_family() -> None:
    combos = list(ci.key_combinations(["COC", "EQC", "APC"]))
    assert len(combos) == 4 * 2 + 3 * 7 + 1
    assert ("COC", {"MM": "MM1", "XM": "DBC"}) in combos
    assert ("APC", {}) in combos


# ----- receiver and simulator -------------------------------------------------------------------


async def test_ci_read_returns_decoded_records(receiver: Receiver) -> None:
    lcc = await receiver.ci_read("LCC", {"MM": "MM3"})
    assert lcc.get("SW") == "-10"
    assert (await receiver.ci_read("APC")).get("PO") == "001"
    assert (await receiver.ci_read("NMC", {"SL": "BD"})).get("NM") == "Movie        "
    assert (await receiver.ci_read("MNC")).get("MN") == "TX-RZ50 DSxx "
    # a CI read does not become receiver state
    assert not any(code.startswith("s") for code in receiver.values)


async def test_ci_read_without_its_key_or_for_an_unknown_record_gets_no_reply(
    receiver: Receiver,
) -> None:
    client = receiver._require_client()
    with pytest.raises(NoReplyError):
        await client.request("sTOCQSTN", "sTOC", 0.2)
    with pytest.raises(NoReplyError):
        await receiver.ci_read("NMC", {"SL": "NET"})


# One set per exposed family: (code, key, field, new value).
FAMILY_SETS = [
    ("SLC", {"SL": "CD"}, "AS", "HDM"),
    ("HIC", None, "CD", "HI6"),
    ("DIC", None, "CD", "O2N"),
    ("AAC", None, "CD", "NON"),
    ("ISC", None, "AX", "001"),
    ("TOC", {"SL": "CD"}, "HS", "000"),
    ("LCC", {"MM": "MM1"}, "SW", "-29"),
    ("SDC", {"MM": "MM1"}, "FR", "003"),
    ("COC", {"MM": "MM1", "XM": "IND"}, "FR", "080"),
    ("EQC", {"PS": "003", "CH": "FRT"}, "B1", "+02"),
    ("SWC", None, "L1", "-02"),
    ("SCC", None, "BR", "001"),
    ("AKC", {"SL": "AUX"}, "DF", "000"),
    ("HLC", {"SL": "AUX"}, "AL", "001"),
    ("VLC", None, "VD", "ABS"),
    ("APC", None, "AP", "001"),
    ("MZC", {"ZN": "002"}, "MV", "080"),
    ("NMC", {"SL": "AUX"}, "NM", "AUX2"),
    ("IVC", {"SL": "CD"}, "IV", "080"),
    ("HDC", None, "LS", "000"),
    ("BTC", None, "UA", "001"),
    ("WSC", {"SO": "000"}, "OZ", "001"),
]


OPTION_SETS = [
    ("DSC", None, "AR", "001"),
    ("TXC", None, "TS", "001"),
    ("SVC", None, "SV", "000"),
    ("MMC", None, "MI", "001"),
    ("DLC", None, "CS", "001"),
    ("DTC", None, "AS", "000"),
    ("TGC", None, "DL", "001"),
    ("PZC", None, "PZ", "001"),
    ("RMC", None, "ID", "002"),
    ("UDC", None, "UN", "000"),
]


@pytest.mark.parametrize(("code", "key", "name", "value"), FAMILY_SETS)
async def test_every_exposed_family_sets_and_restores(
    receiver: Receiver, code: str, key: dict[str, str] | None, name: str, value: str
) -> None:
    before = await receiver.ci_read(code, key)
    change = await receiver.ci_set(code, {name: value}, key)
    assert change.after is not None
    assert change.after.get(name) == change.changes[name]
    assert change.after.get(name) != before.get(name)
    assert (await receiver.ci_read(code, key)).get(name) == change.changes[name]
    restored = await receiver.ci_restore(change)
    assert restored == before
    assert await receiver.ci_read(code, key) == before


def test_every_exposed_family_is_covered_by_a_round_trip() -> None:
    tested = {code for code, *_ in FAMILY_SETS + OPTION_SETS} | {"VIC"}  # VIC: sets are ignored
    assert set(ci.EXPOSED) <= tested


@pytest.mark.parametrize(("code", "key", "name", "value"), OPTION_SETS)
async def test_option_families_round_trip(
    receiver: Receiver, code: str, key: dict[str, str] | None, name: str, value: str
) -> None:
    before = await receiver.ci_read(code, key)
    change = await receiver.ci_set(code, {name: value}, key)
    assert change.after is not None
    assert change.after.get(name) == value
    assert await receiver.ci_restore(change) == before


async def test_a_set_the_receiver_ignores_raises(receiver: Receiver) -> None:
    before = await receiver.ci_read("VIC")
    with pytest.raises(CiNotAppliedError):
        await receiver.ci_set("VIC", {"CD": "CV1"})
    assert await receiver.ci_read("VIC") == before


async def test_refused_families_send_nothing(receiver: Receiver, sim: SimServer) -> None:
    before = await receiver.ci_read("CFC")
    with pytest.raises(CiRefusedError):
        await receiver.ci_set("CFC", {"IM": "004"})
    with pytest.raises(CiRefusedError):
        await receiver.ci_set("NTC", {"IP": "00000001"})
    assert await receiver.ci_read("CFC") == before
    # the simulator would ignore a CFC set as the real receiver does: check it directly
    assert sim.receiver.ci.handle("sCFC", "IM004") == []
    assert (await receiver.ci_read("CFC")).get("IM") == "006"


async def test_global_fields_are_shared_by_every_record(receiver: Receiver) -> None:
    change = await receiver.ci_set("TOC", {"SS": "003"}, {"SL": "CD"})
    assert (await receiver.ci_read("TOC", {"SL": "GAM"})).get("SS") == "003"
    await receiver.ci_restore(change)
    assert (await receiver.ci_read("TOC", {"SL": "GAM"})).get("SS") == "000"


async def test_a_set_changes_only_the_named_fields_and_record(receiver: Receiver) -> None:
    mm3 = await receiver.ci_read("LCC", {"MM": "MM3"})
    mm1 = await receiver.ci_read("LCC", {"MM": "MM1"})
    change = await receiver.ci_set("LCC", {"SW": "-29"}, {"MM": "MM1"})
    assert change.calibration
    assert await receiver.ci_read("LCC", {"MM": "MM3"}) == mm3
    after = await receiver.ci_read("LCC", {"MM": "MM1"})
    assert after.get("SW") == "-29"
    assert {n: v for n, v in after.items if n != "SW"} == {n: v for n, v in mm1.items if n != "SW"}
    await receiver.ci_restore(change)
    assert await receiver.ci_read("LCC", {"MM": "MM1"}) == mm1


async def test_a_coc_set_changes_only_its_crossover_mode(receiver: Receiver) -> None:
    dbc = await receiver.ci_read("COC", {"MM": "MM1", "XM": "DBC"})
    change = await receiver.ci_set("COC", {"FR": "080"}, {"MM": "MM1", "XM": "IND"})
    assert await receiver.ci_read("COC", {"MM": "MM1", "XM": "DBC"}) == dbc
    await receiver.ci_restore(change)


async def test_a_value_the_receiver_rejects_is_ignored_by_the_simulator(
    receiver: Receiver, sim: SimServer
) -> None:
    before = await receiver.ci_read("SWC")
    sim.receiver.ci.handle("sSWC", "L1+02")
    sim.receiver.ci.handle("sMMC", "XI000")
    sim.receiver.ci.handle("sMMC", "MI9")
    assert await receiver.ci_read("SWC") == before
    assert (await receiver.ci_read("MMC")).get("XI") == "001"


async def test_sets_get_no_reply_on_the_wire(receiver: Receiver) -> None:
    seen = await receiver.send_raw("sAPCAP001", wait=0.2)
    assert seen == []
    assert (await receiver.ci_read("APC")).get("AP") == "001"
    await receiver.send_raw("sAPCAP000", wait=0.1)


async def test_a_reply_for_another_key_is_never_used(receiver: Receiver) -> None:
    client = receiver._require_client()
    other = (await receiver.ci_read("LCC", {"MM": "MM3"})).encode()[len("sLCC") :]

    async def stale(message: str, reply_code: str, timeout: float = 2.0) -> str:  # noqa: ASYNC109
        return other

    client.request = stale  # type: ignore[method-assign]
    with pytest.raises(NoReplyError):
        await receiver.ci_read("LCC", {"MM": "MM1"})
    with pytest.raises(NoReplyError):
        await receiver.ci_set("LCC", {"SW": "-29"}, {"MM": "MM1"})


async def test_a_partly_applied_set_keeps_its_restore_command(
    receiver: Receiver, sim: SimServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = sim.receiver.ci
    original = store._apply

    def skip_levels(family: str, name: str, *args: object, **kwargs: object) -> None:
        if name != "L1":
            original(family, name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "_apply", skip_levels)
    before = await receiver.ci_read("SWC")
    with pytest.raises(CiNotAppliedError) as raised:
        await receiver.ci_set("SWC", {"F1": "080", "L1": "-02"})
    change = raised.value.change
    assert isinstance(change, ci.CiChange)
    assert change.after is not None
    assert change.after.get("F1") == "080"
    await receiver.ci_restore(change)
    assert await receiver.ci_read("SWC") == before
