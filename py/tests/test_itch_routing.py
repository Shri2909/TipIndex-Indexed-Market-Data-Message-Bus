"""V03: explicit routing boundaries, encoding, and late directory state."""

from tiplog_py.itch import Router, encode_symbol


def message(kind, locate, symbol=None):
    sizes = {"R": 39, "H": 25, "L": 26, "K": 28, "A": 36, "D": 19,
             "S": 12, "V": 35, "W": 12, "P": 44, "Q": 40, "I": 50}
    symbol_positions = {"R": 11, "H": 11, "L": 15, "K": 11, "A": 24, "P": 24, "Q": 19, "I": 28}
    payload = bytearray(sizes[kind])
    payload[0] = ord(kind)
    payload[1:3] = locate.to_bytes(2, "big")
    if symbol is not None:
        begin = symbol_positions[kind]
        payload[begin:begin + 8] = symbol.ljust(8, b" ")
    return bytes(payload)


def test_v03_directory_locate_only_and_nonstandard_symbol_positions():
    router = Router()
    assert router.route(message("D", 7)) == "itch/_unmapped/L7/D"
    assert router.route(message("R", 7, b"AB.C")) == "itch/AB.C/stock/directory"
    assert router.route(message("D", 7)) == "itch/AB.C/modify/delete"
    for kind, suffix in [("L", "stock/mp_position"), ("A", "add/anon"),
                         ("P", "trade/noncross"), ("Q", "trade/cross"), ("I", "noii")]:
        assert router.route(message(kind, 7, b"AB.C")) == f"itch/AB.C/{suffix}"
    assert router.symbol_mismatches == 0
    assert router.unknown_locate_messages == 1


def test_v03_symbol_messages_without_directory_stay_unmapped():
    router = Router()
    assert router.route(message("A", 99, b"AAPL")) == "itch/_unmapped/L99/A"
    assert router.summary()["directory_entries"] == 0


def test_v03_k_routes_by_symbol_even_with_zero_or_unmapped_locate():
    router = Router()
    assert router.route(message("K", 0, b"IPO.A")) == "itch/IPO.A/stock/ipo_quoting"
    assert router.route(message("K", 99, b"IPO.B")) == "itch/IPO.B/stock/ipo_quoting"
    assert router.nonzero_k_locates == 1
    assert router.unknown_locate_messages == 0


def test_v03_market_routes_are_independent_of_directory():
    router = Router()
    assert router.route(message("S", 0)) == "itch/_market/system_event"
    assert router.route(message("V", 0)) == "itch/_market/mwcb/decline_level"
    assert router.route(message("W", 7)) == "itch/_market/mwcb/status"
    assert router.nonzero_market_locates == 1


def test_v03_mismatch_and_directory_conflicts_preserve_first_day_mapping():
    router = Router()
    router.route(message("R", 7, b"AAA"))
    assert router.route(message("A", 7, b"BBB")) == "itch/AAA/add/anon"
    assert router.route(message("R", 7, b"BBB")) == "itch/AAA/stock/directory"
    assert router.route(message("D", 7)) == "itch/AAA/modify/delete"
    assert router.symbol_mismatches == 2
    assert router.directory_conflicts == 1


def test_v03_percent_encoding_is_injective_and_preserves_dot():
    assert encode_symbol(b"AB.C    ") == "AB.C"
    assert encode_symbol(b"A/B%_x  ") == "A%2FB%25%5F%78"


def test_v03_hflat_uses_message_type_as_third_segment():
    router = Router("H-flat")
    assert router.route(message("R", 7, b"AB.C")) == "itch/AB.C/R"
    assert router.route(message("D", 7)) == "itch/AB.C/D"
    assert router.route(message("K", 0, b"IPO.A")) == "itch/IPO.A/K"
    assert router.route(message("V", 0)) == "itch/_market/V"
