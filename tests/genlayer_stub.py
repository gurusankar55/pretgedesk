# Minimal offline stand-in for the `genlayer` module, so the real contract
# files can be imported and tested with plain Python (no Docker, no node).
import sys
import types


class _Addr:
    def __init__(self, h):
        self.as_hex = str(h)

    def __repr__(self):
        return self.as_hex


class _Msg:
    def __init__(self):
        self.sender_address = _Addr("0x" + "1" * 40)
        self.value = 0


class _Resp:
    def __init__(self, text):
        self.body = text.encode("utf-8")


class _Web:
    def __init__(self):
        self.pages = {}
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        if url not in self.pages:
            raise Exception("unreachable " + url)
        return _Resp(self.pages[url])

    def render(self, url, mode="text"):
        self.calls.append("render:" + url)
        if url not in self.pages:
            raise Exception("unreachable " + url)
        return self.pages[url]


class _Payee:
    def __init__(self, gl, to):
        self.gl = gl
        self.to = to

    def emit_transfer(self, value):
        self.gl.payments.append((self.to.as_hex.lower(), int(value)))


def _decorator(f):
    return f


class _Write:
    def __call__(self, f):
        return f

    payable = staticmethod(_decorator)


class _Public:
    write = _Write()
    view = staticmethod(_decorator)


class _EqP:
    def __init__(self, gl):
        self.gl = gl

    def strict_eq(self, fn):
        # leader and one validator both run the function; they must agree
        a = fn()
        b = fn()
        if a != b:
            raise Exception("validators disagree")
        self.gl.nondet_runs += 1
        return a


class _Evm:
    def contract_interface(self, cls):
        raise Exception("not in stub")


class _GL:
    def __init__(self):
        self.message = _Msg()
        self.message_raw = {}
        self.nondet = types.SimpleNamespace(web=_Web())
        self.public = _Public()
        self.eq_principle = _EqP(self)
        self.evm = _Evm()
        self.payments = []
        self.nondet_runs = 0

        class Contract:
            pass

        self.Contract = Contract

    def get_contract_at(self, to):
        return _Payee(self, to)


class TreeMap(dict):
    def __class_getitem__(cls, item):
        return cls


def install():
    gl = _GL()
    mod = types.ModuleType("genlayer")
    mod.gl = gl
    mod.TreeMap = TreeMap
    mod.u256 = int
    mod.Address = _Addr
    mod.__all__ = ["gl", "TreeMap", "u256", "Address"]
    sys.modules["genlayer"] = mod
    return gl
