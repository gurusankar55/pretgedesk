import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import genlayer_stub  # noqa: E402

GEN = 10 ** 18
T0 = 1_800_000_000
DOMAIN = "gurusankar55.github.io"
PAGE_URL = "https://gurusankar55.github.io/pretgedesk/tge-demo.html"
TOKEN = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
OTHER = "0x" + "ab" * 20
SELLER = "0x" + "a1" * 20
BUYER = "0x" + "b2" * 20
STRANGER = "0x" + "c3" * 20
SELLER_CHAIN = "0x4B063d567910269f7714603A0501A560691DA31f"
BUYER_CHAIN = "0xA849bbaD82F9edafDf9A5550CC874276138779d9"
TX = "0xd385c5f5dbd68b7bc8f68b5c8eca7797a87cf2e841fed5b91384aec31cec493e"


def load(path):
    gl = genlayer_stub.install()
    name = "c_" + os.path.basename(path).replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, gl


def page(addresses=(TOKEN,), symbol="USDC"):
    body = "<html><body><h1>%s is live</h1>" % symbol
    for a in addresses:
        body += "<p>Official contract: <code>%s</code></p>" % a
    return body + "</body></html>"


def token_json(addr, symbol="USDC", decimals="6", typ="ERC-20"):
    return json.dumps({"address_hash": addr, "symbol": symbol, "decimals": decimals, "type": typ, "name": symbol})


def tx_json(ts="2030-01-01T00:00:00.000000Z", frm=SELLER_CHAIN, to=BUYER_CHAIN, value="1000",
            token=TOKEN, status="ok", result="success", conf=50, h=TX, overflow=False, transfers=None):
    if transfers is None:
        transfers = [{
            "from": {"hash": frm}, "to": {"hash": to},
            "token": {"address_hash": token, "symbol": "USDC", "decimals": "6"},
            "total": {"decimals": "6", "value": value}, "type": "token_transfer",
        }]
    return json.dumps({"hash": h, "status": status, "result": result, "timestamp": ts,
                       "confirmations": conf, "token_transfers": transfers,
                       "token_transfers_overflow": overflow})


def iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


class Base(unittest.TestCase):
    PATH = os.path.join(ROOT, "contracts", "pretge_desk.py")

    def setUp(self):
        self.mod, self.gl = load(self.PATH)
        self.clock = [T0]
        self.mod._now = lambda: self.clock[0]
        self.c = self.mod.PreTGEDesk.__new__(self.mod.PreTGEDesk)
        for name, ann in self.mod.PreTGEDesk.__annotations__.items():
            if ann is genlayer_stub.TreeMap:
                setattr(self.c, name, genlayer_stub.TreeMap())
        self.c.__init__()
        self.deposits = 0
        self.web = self.gl.nondet.web
        self.ex = self.mod.EXPLORER
        self.web.pages[PAGE_URL] = page()
        self.web.pages[self.ex + "/api/v2/tokens/" + TOKEN] = token_json(TOKEN)

    # helpers
    def as_(self, who, value=0):
        self.gl.message.sender_address = genlayer_stub._Addr(who)
        self.gl.message.value = value
        self.deposits += value
        return self.c

    def paid(self):
        return sum(v for _, v in self.gl.payments)

    def paid_to(self, who):
        return sum(v for t, v in self.gl.payments if t == who.lower())

    def market(self, tw=None, dl=None):
        tw = tw or self.mod.MIN_TGE_WINDOW_S * 10
        dl = dl or self.mod.MIN_DELIVERY_S * 2
        return self.as_(STRANGER).create_market("usdc", "Demo USDC", DOMAIN, tw, dl)

    def offer(self, mid, amount="0.001", price="1"):
        p = self.mod.parse_amount18(price)
        return self.as_(SELLER, p).create_offer(mid, amount, price, SELLER_CHAIN)

    def fill(self, oid, price="1"):
        return self.as_(BUYER, self.mod.parse_amount18(price)).fill_offer(oid, BUYER_CHAIN)

    def go_live(self, mid):
        r = self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL)
        self.assertEqual(r, "VERIFIED:6")
        self.clock[0] += self.mod.CHALLENGE_S
        self.assertEqual(json.loads(self.c.get_market(mid))["current_status"], "LIVE")

    def set_tx(self, **kw):
        self.web.pages[self.ex + "/api/v2/transactions/" + TX] = tx_json(**kw)

    def assert_balanced(self):
        # every GEN that came in has gone out, nothing left behind
        self.assertEqual(self.paid(), self.deposits)


class PureHelpers(Base):
    def test_amount_parse_and_rounding(self):
        m = self.mod
        self.assertEqual(m.parse_amount18("1.5"), 15 * 10 ** 17)
        self.assertEqual(m.parse_amount18("abc"), -1)
        self.assertEqual(m.parse_amount18("1.2.3"), -1)
        self.assertEqual(m.parse_amount18("0." + "1" * 19), -1)
        self.assertEqual(m.required_raw(m.parse_amount18("0.001"), 6), 1000)
        self.assertEqual(m.required_raw(m.parse_amount18("1000"), 18), 1000 * GEN)
        # 0.0000001 of a 6-decimals token rounds UP to 1 base unit
        self.assertEqual(m.required_raw(m.parse_amount18("0.0000001"), 6), 1)

    def test_url_on_domain(self):
        f = self.mod.url_on_domain
        self.assertTrue(f("https://gurusankar55.github.io/x", DOMAIN))
        self.assertTrue(f("https://docs.project.xyz/a", "project.xyz"))
        self.assertFalse(f("http://project.xyz/a", "project.xyz"))
        self.assertFalse(f("https://project.xyz.evil.io/a", "project.xyz"))
        self.assertFalse(f("https://evilproject.xyz/a", "project.xyz"))
        self.assertFalse(f("https://project.xyz@evil.io/a", "project.xyz"))
        self.assertFalse(f("https://project.xyz:8443/a", "project.xyz"))

    def test_symbol_whole_word(self):
        self.assertTrue(self.mod.symbol_on_page("buy USDC now", "USDC"))
        self.assertFalse(self.mod.symbol_on_page("buy USDCX now", "USDC"))


class Production(Base):
    def test_rules(self):
        r = json.loads(self.c.get_rules())
        self.assertEqual(r["build"], "production")
        self.assertEqual(r["chain"], "base")
        self.assertFalse(r["allow_past_tx"])
        self.assertFalse(r["shared_pool"])
        self.assertIsNone(r["owner"])

    def test_market_validation(self):
        c = self.as_(STRANGER)
        with self.assertRaises(Exception):
            c.create_market("US DC", "x", DOMAIN, 7200, 7200)
        with self.assertRaises(Exception):
            c.create_market("USDC", "x", "https://" + DOMAIN, 7200, 7200)
        with self.assertRaises(Exception):
            c.create_market("USDC", "x", DOMAIN, 60, 7200)  # too short in production
        with self.assertRaises(Exception):
            c.create_market("USDC", "x", DOMAIN, 7200, 8 * 86400)
        for shared in ["github.io", "vercel.app", "x.com", "gitbook.io"]:
            with self.assertRaises(Exception):
                c.create_market("USDC", "x", shared, 7200, 7200)
        mid = c.create_market("usdc", "x", "WWW." + DOMAIN.upper(), 7200, 7200)
        self.assertEqual(json.loads(c.get_market(mid))["official_domain"], DOMAIN)

    def test_offer_needs_bond_and_refunds_extra(self):
        mid = self.market()
        with self.assertRaises(Exception):
            self.as_(SELLER, GEN // 2).create_offer(mid, "10", "1", SELLER_CHAIN)
        self.deposits -= GEN // 2  # that tx reverted
        oid = self.as_(SELLER, 3 * GEN).create_offer(mid, "10", "1", SELLER_CHAIN)
        self.assertEqual(self.paid_to(SELLER), 2 * GEN)
        o = json.loads(self.c.get_offer(oid))
        self.assertEqual(o["bond_wei"], str(GEN))
        self.assertTrue(o["can_fill"])

    def test_fill_rules(self):
        mid = self.market()
        oid = self.offer(mid)
        with self.assertRaises(Exception):
            self.as_(SELLER, GEN).fill_offer(oid, BUYER_CHAIN)
        with self.assertRaises(Exception):
            self.as_(BUYER, GEN).fill_offer(oid, SELLER_CHAIN)
        with self.assertRaises(Exception):
            self.as_(BUYER, GEN // 2).fill_offer(oid, BUYER_CHAIN)
        self.deposits -= 2 * GEN + GEN // 2  # reverted txs
        self.as_(BUYER, 2 * GEN).fill_offer(oid, BUYER_CHAIN)
        self.assertEqual(self.paid_to(BUYER), GEN)  # extra back
        with self.assertRaises(Exception):
            self.as_(STRANGER, GEN).fill_offer(oid, BUYER_CHAIN)
        self.deposits -= GEN

    def test_cancel_open_offer(self):
        mid = self.market()
        oid = self.offer(mid)
        with self.assertRaises(Exception):
            self.as_(STRANGER).cancel_offer(oid)
        self.assertEqual(self.as_(SELLER).cancel_offer(oid), "CANCELLED")
        self.assert_balanced()
        with self.assertRaises(Exception):
            self.as_(SELLER).cancel_offer(oid)

    def test_propose_input_checks_run_no_validators(self):
        mid = self.market()
        c = self.as_(STRANGER)
        for url in ["https://evil.io/x", "https://gurusankar55.github.io.evil.io/x",
                    "https://gurusankar55.github.io@evil.io/x", "http://gurusankar55.github.io/x"]:
            with self.assertRaises(Exception):
                c.propose_tge(mid, TOKEN, url)
        with self.assertRaises(Exception):
            c.propose_tge(mid, "0x123", PAGE_URL)
        self.assertEqual(self.gl.nondet_runs, 0)

    def test_propose_fails_safely(self):
        mid = self.market()
        self.web.pages[PAGE_URL] = page(addresses=())
        self.assertEqual(self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL), "ADDRESS_NOT_ON_PAGE")
        self.web.pages[PAGE_URL] = page(symbol="SOMETHING")
        self.assertEqual(self.c.propose_tge(mid, TOKEN, PAGE_URL), "SYMBOL_NOT_ON_PAGE")
        self.web.pages[PAGE_URL] = page()
        self.web.pages[self.ex + "/api/v2/tokens/" + TOKEN] = token_json(TOKEN, symbol="FAKE")
        self.assertEqual(self.c.propose_tge(mid, TOKEN, PAGE_URL), "SYMBOL_MISMATCH:FAKE")
        self.web.pages[self.ex + "/api/v2/tokens/" + TOKEN] = json.dumps({"message": "Not found"})
        self.assertEqual(self.c.propose_tge(mid, TOKEN, PAGE_URL), "NOT_A_TOKEN")
        self.web.pages[self.ex + "/api/v2/tokens/" + TOKEN] = token_json(TOKEN, typ="ERC-721")
        self.assertEqual(self.c.propose_tge(mid, TOKEN, PAGE_URL), "NOT_A_TOKEN")
        del self.web.pages[PAGE_URL]
        self.assertEqual(self.c.propose_tge(mid, TOKEN, PAGE_URL), "UNKNOWN")
        self.assertEqual(json.loads(self.c.get_market(mid))["current_status"], "PRE")

    def test_pending_blocks_trading_then_live(self):
        mid = self.market()
        oid = self.offer(mid)
        self.assertEqual(self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL), "VERIFIED:6")
        m = json.loads(self.c.get_market(mid))
        self.assertEqual(m["current_status"], "PENDING_LIVE")
        with self.assertRaises(Exception):
            self.fill(oid)
        self.deposits -= GEN
        with self.assertRaises(Exception):
            self.offer(mid)
        self.deposits -= GEN
        with self.assertRaises(Exception):
            self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL)
        self.clock[0] += self.mod.CHALLENGE_S
        self.assertTrue(self.c.is_live(mid))
        # open offer at TGE: anyone can settle it, seller gets the bond back
        self.assertEqual(self.as_(STRANGER).settle(oid), "CANCELLED")
        self.assert_balanced()

    def test_challenge_makes_market_ambiguous_and_refunds(self):
        mid = self.market()
        oid = self.offer(mid)
        self.fill(oid)
        self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL)
        with self.assertRaises(Exception):
            self.c.challenge_tge(mid, TOKEN, PAGE_URL)  # same address
        # a challenge with an address that does not pass changes nothing
        self.web.pages[self.ex + "/api/v2/tokens/" + OTHER] = token_json(OTHER)
        self.assertEqual(self.c.challenge_tge(mid, OTHER, PAGE_URL), "ADDRESS_NOT_ON_PAGE")
        self.assertEqual(json.loads(self.c.get_market(mid))["current_status"], "PENDING_LIVE")
        # the page lists a second token with the same ticker
        self.web.pages[PAGE_URL] = page(addresses=(TOKEN, OTHER))
        self.assertEqual(self.c.challenge_tge(mid, OTHER, PAGE_URL), "AMBIGUOUS")
        self.clock[0] += 10 * self.mod.CHALLENGE_S
        self.assertFalse(self.c.is_live(mid))
        self.assertEqual(self.c.settle(oid), "REFUNDED")
        self.assertEqual(self.paid_to(BUYER), GEN)
        self.assertEqual(self.paid_to(SELLER), GEN)
        self.assert_balanced()

    def test_challenge_after_window_rejected(self):
        mid = self.market()
        self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL)
        self.clock[0] += self.mod.CHALLENGE_S
        with self.assertRaises(Exception):
            self.c.challenge_tge(mid, OTHER, PAGE_URL)

    def test_delivery_success_pays_seller_once(self):
        mid = self.market()
        oid = self.offer(mid)
        self.fill(oid)
        with self.assertRaises(Exception):
            self.as_(SELLER).submit_delivery(oid, TX)  # not live yet
        self.go_live(mid)
        self.set_tx(ts=iso(self.clock[0] + 5))
        self.assertEqual(self.as_(SELLER).submit_delivery(oid, TX), "DELIVERED")
        self.assertEqual(self.paid_to(SELLER), 2 * GEN)
        self.assert_balanced()
        with self.assertRaises(Exception):
            self.c.submit_delivery(oid, TX)
        with self.assertRaises(Exception):
            self.c.settle(oid)
        # the same tx can't be used for another trade
        oid2 = None
        mid2 = self.market()
        oid2 = self.offer(mid2)
        self.fill(oid2)
        self.as_(STRANGER).propose_tge(mid2, TOKEN, PAGE_URL)
        self.clock[0] += self.mod.CHALLENGE_S
        with self.assertRaises(Exception):
            self.as_(SELLER).submit_delivery(oid2, TX)

    def test_delivery_rejections_move_nothing(self):
        mid = self.market()
        oid = self.offer(mid)
        self.fill(oid)
        filled = self.clock[0]
        self.go_live(mid)
        c = self.as_(SELLER)
        later = iso(self.clock[0] + 5)
        cases = [
            (dict(ts=iso(filled - 100)), "SENT_BEFORE_TRADE"),
            (dict(ts=later, to=SELLER_CHAIN), "NO_MATCHING_TRANSFER"),
            (dict(ts=later, frm=BUYER_CHAIN, to=BUYER_CHAIN), "NO_MATCHING_TRANSFER"),
            (dict(ts=later, token=OTHER), "NO_MATCHING_TRANSFER"),
            (dict(ts=later, value="999"), "AMOUNT_TOO_LOW:999"),
            (dict(ts=later, result="error"), "TX_FAILED_OR_PENDING"),
            (dict(ts=later, conf=2), "NOT_ENOUGH_CONFIRMATIONS"),
            (dict(ts=iso(self.clock[0] + 10 ** 6)), "SENT_AFTER_DEADLINE"),
        ]
        for kw, want in cases:
            self.set_tx(**kw)
            self.assertEqual(c.submit_delivery(oid, TX), want, kw)
        self.web.pages[self.ex + "/api/v2/transactions/" + TX] = json.dumps({"message": "Not found"})
        self.assertEqual(c.submit_delivery(oid, TX), "TX_NOT_FOUND")
        del self.web.pages[self.ex + "/api/v2/transactions/" + TX]
        self.assertEqual(c.submit_delivery(oid, TX), "UNKNOWN")
        with self.assertRaises(Exception):
            c.submit_delivery(oid, "0x1234")
        self.assertEqual(self.paid(), 0)
        self.assertEqual(json.loads(self.c.get_offer(oid))["status"], "FILLED")

    def test_delivery_split_into_two_transfers_and_overflow(self):
        mid = self.market()
        oid = self.offer(mid)
        self.fill(oid)
        self.go_live(mid)
        part = {"from": {"hash": SELLER_CHAIN}, "to": {"hash": BUYER_CHAIN},
                "token": {"address_hash": TOKEN}, "total": {"value": "500"}}
        tx_url = self.ex + "/api/v2/transactions/" + TX
        self.web.pages[tx_url] = tx_json(ts=iso(self.clock[0] + 5), overflow=True, transfers=[])
        self.web.pages[tx_url + "/token-transfers"] = json.dumps({"items": [part, part], "next_page_params": None})
        self.assertEqual(self.as_(SELLER).submit_delivery(oid, TX), "DELIVERED")
        self.assert_balanced()

    def test_default_pays_buyer_price_and_bond(self):
        mid = self.market()
        oid = self.offer(mid)
        self.fill(oid)
        self.go_live(mid)
        with self.assertRaises(Exception):
            self.c.settle(oid)  # window still open
        self.clock[0] += int(json.loads(self.c.get_market(mid))["delivery_s"])
        self.set_tx(ts=iso(self.clock[0] - 5))
        with self.assertRaises(Exception):
            self.as_(SELLER).submit_delivery(oid, TX)  # too late to submit
        self.assertTrue(json.loads(self.c.get_offer(oid))["can_settle"])
        self.assertEqual(self.as_(STRANGER).settle(oid), "DEFAULTED")
        self.assertEqual(self.paid_to(BUYER), 2 * GEN)
        self.assert_balanced()

    def test_no_tge_refunds_everyone(self):
        mid = self.market()
        o1 = self.offer(mid)
        o2 = self.offer(mid)
        self.fill(o1)
        with self.assertRaises(Exception):
            self.c.settle(o1)
        self.clock[0] += self.mod.MIN_TGE_WINDOW_S * 10
        self.assertEqual(json.loads(self.c.get_market(mid))["current_status"], "NO_TGE")
        with self.assertRaises(Exception):
            self.as_(STRANGER).propose_tge(mid, TOKEN, PAGE_URL)
        self.assertEqual(self.as_(STRANGER).settle(o1), "REFUNDED")
        self.assertEqual(self.c.settle(o2), "CANCELLED")
        self.assert_balanced()

    def test_trades_are_isolated(self):
        # two markets, different outcomes: each trade pays only its own money
        m1 = self.market()
        m2 = self.market()
        a = self.offer(m1, price="1")
        b = self.offer(m2, price="3")
        self.fill(a, price="1")
        self.fill(b, price="3")
        self.go_live(m1)
        self.set_tx(ts=iso(self.clock[0] + 5))
        self.assertEqual(self.as_(SELLER).submit_delivery(a, TX), "DELIVERED")
        self.assertEqual(self.paid(), 2 * GEN)  # market 2 money untouched
        self.clock[0] += self.mod.MIN_TGE_WINDOW_S * 10
        self.assertEqual(self.c.settle(b), "REFUNDED")
        self.assert_balanced()

    def test_views(self):
        mid = self.market()
        oid = self.offer(mid)
        self.assertEqual(len(json.loads(self.c.get_markets())), 1)
        self.assertEqual(len(json.loads(self.c.get_offers(mid))), 1)
        self.assertEqual(json.loads(self.c.get_offers_of(SELLER))[0]["id"], oid)
        self.assertEqual(json.loads(self.c.get_counts()), {"markets": 1, "offers": 1})


class Demo(Base):
    PATH = os.path.join(ROOT, "contracts", "pretge_desk_demo.py")

    def test_demo_rules(self):
        r = json.loads(self.c.get_rules())
        self.assertEqual(r["build"], "demo")
        self.assertEqual(r["chain"], "base-sepolia")
        self.assertTrue(r["allow_past_tx"])

    def test_demo_full_flow_with_past_testnet_tx(self):
        mid = self.market(tw=600, dl=300)
        oid = self.offer(mid, amount="0.001", price="1")
        self.fill(oid)
        self.go_live(mid)
        self.set_tx(ts="2026-11-17T15:25:21.000000Z", conf=100)
        self.assertEqual(self.as_(SELLER).submit_delivery(oid, TX), "DELIVERED")
        self.assert_balanced()


class SourceMatch(unittest.TestCase):
    def test_demo_differs_only_in_build_block(self):
        with open(os.path.join(ROOT, "contracts", "pretge_desk.py")) as f:
            prod = f.read().splitlines()
        with open(os.path.join(ROOT, "contracts", "pretge_desk_demo.py")) as f:
            demo = f.read().splitlines()
        self.assertEqual(prod[:3], demo[:3])
        self.assertEqual(prod[0], "# v0.2.16")
        self.assertIn("1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6", prod[1])
        allowed = ("BUILD =", "CHAIN =", "EXPLORER =", "CHALLENGE_S =", "MIN_TGE_WINDOW_S =",
                   "MIN_DELIVERY_S =", "MIN_CONFIRMATIONS =", "ALLOW_PAST_TX =", "# PreTGE Desk DEMO BUILD",
                   "# Production source:")
        import difflib
        for line in difflib.unified_diff(prod, demo, lineterm="", n=0):
            if line.startswith(("---", "+++", "@@")):
                continue
            self.assertTrue(line[1:].startswith(allowed), line)


if __name__ == "__main__":
    unittest.main()
