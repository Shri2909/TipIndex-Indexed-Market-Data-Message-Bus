"""Day-specific locate routing and approved H-spec/H-flat hierarchies (DD-01)."""

from .protocol import SYMBOL_OFFSETS, validate_message


SUFFIXES = {
    "R": "stock/directory", "H": "stock/trading_action", "Y": "stock/reg_sho",
    "L": "stock/mp_position", "K": "stock/ipo_quoting", "J": "stock/luld_collar",
    "h": "stock/op_halt", "A": "add/anon", "F": "add/attributed",
    "E": "modify/executed", "C": "modify/executed_px", "X": "modify/cancel",
    "D": "modify/delete", "U": "modify/replace", "P": "trade/noncross",
    "Q": "trade/cross", "B": "trade/broken", "I": "noii", "N": "rpii", "O": "dlcr",
    "S": "system_event", "V": "mwcb/decline_level", "W": "mwcb/status",
}
MARKET_TYPES = frozenset("SVW")
SAFE = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.")


def encode_symbol(symbol: bytes | str) -> str:
    """Trim trailing spaces; percent-encode every byte outside [A-Z0-9.]."""
    if isinstance(symbol, str):
        symbol = symbol.encode("ascii")
    symbol = symbol.rstrip(b" ")
    if not symbol:
        raise ValueError("empty stock symbol")
    return "".join(chr(value) if value in SAFE else f"%{value:02X}" for value in symbol)


class Router:
    def __init__(self, hierarchy: str = "H-spec"):
        if hierarchy not in ("H-spec", "H-flat"):
            raise ValueError("hierarchy must be H-spec or H-flat")
        self.hierarchy = hierarchy
        self.directory: list[bytes | None] = [None] * 65536
        self.cache: dict[tuple[int, str], str] = {}
        self.unknown_locate_messages = 0
        self.symbol_mismatches = 0
        self.directory_conflicts = 0
        self.nonzero_market_locates = 0
        self.nonzero_k_locates = 0
        self.directory_zero_locates = 0
        self.symbol_messages_crosschecked = 0

    def route(self, payload: bytes, *, validated: bool = False) -> str:
        kind = chr(payload[0]) if validated else validate_message(payload)
        locate = (payload[1] << 8) | payload[2]
        symbol_offset = SYMBOL_OFFSETS.get(kind)
        symbol = payload[symbol_offset:symbol_offset + 8] if symbol_offset is not None else None
        if kind == "R":
            if locate == 0:
                self.directory_zero_locates += 1
            old = self.directory[locate]
            if old is None:
                # Earlier unknown messages remain unknown: no retrospective rewrite.
                self.directory[locate] = symbol
            elif old != symbol:
                self.directory_conflicts += 1
        if kind in MARKET_TYPES:
            self.nonzero_market_locates += locate != 0
            return f"itch/_market/{self._suffix(kind)}"
        if kind == "K":
            self.nonzero_k_locates += locate != 0
            return f"itch/{encode_symbol(symbol)}/{self._suffix(kind)}"
        mapped = self.directory[locate]
        if mapped is None:
            self.unknown_locate_messages += 1
            return f"itch/_unmapped/L{locate}/{kind}"
        if symbol is not None:
            self.symbol_messages_crosschecked += 1
            self.symbol_mismatches += symbol != mapped
        key = (locate, kind)
        path = self.cache.get(key)
        if path is None:
            path = f"itch/{encode_symbol(mapped)}/{self._suffix(kind)}"
            self.cache[key] = path
        return path

    def _suffix(self, kind: str) -> str:
        return SUFFIXES[kind] if self.hierarchy == "H-spec" else kind

    def summary(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in (
            "unknown_locate_messages", "symbol_mismatches", "directory_conflicts",
            "nonzero_market_locates", "nonzero_k_locates", "directory_zero_locates",
            "symbol_messages_crosschecked")} | {
                "directory_entries": sum(value is not None for value in self.directory)}
