# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *

import json
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# PreTGE Desk - pre-market escrow for tokens that are not live yet
#
# A seller offers tokens of a project that has not launched (TGE) yet, for a
# GEN price. The seller locks a GEN bond equal to the price. A buyer fills
# the offer by locking the price. Nobody has to trust the other side:
#
#   1. TGE check. Anyone proposes the official token address. GenLayer
#      validators read a page on the project's official domain (committed
#      when the market was created) and the chain explorer, and must agree
#      that the address is on that page and is a token with that ticker.
#   2. Challenge window. For CHALLENGE_S anyone may show a DIFFERENT address
#      that passes the same check. Then the market is AMBIGUOUS and every
#      trade is refunded. Nobody gets paid on a disputed token.
#   3. Delivery check. After the TGE, the seller has delivery_s seconds to
#      send the tokens on-chain from the address they committed, to the
#      address the buyer committed. Validators read that transaction from
#      the explorer and must agree it is a successful transfer of the right
#      token and amount, made after the trade was filled.
#   4. Settlement. Delivered: seller gets price + bond. Not delivered in
#      time: buyer gets price + seller's bond. No TGE by the deadline, or an
#      ambiguous TGE: everyone gets their own money back.
#
# Every trade is its own escrow. There is no shared pool, so one trade can
# never pay out another trade's money. There is no owner and no admin.
# ---------------------------------------------------------------------------

# ---- build settings (the demo build differs ONLY in this block) -----------
BUILD = "production"
CHAIN = "base"
EXPLORER = "https://base.blockscout.com"
CHALLENGE_S = 3600            # 1 hour to challenge a TGE proposal
MIN_TGE_WINDOW_S = 3600       # TGE deadline at least 1 hour away
MIN_DELIVERY_S = 3600         # sellers get at least 1 hour to deliver
MIN_CONFIRMATIONS = 10        # delivery tx must have 10+ confirmations
ALLOW_PAST_TX = False         # delivery tx must be sent after the fill
# ---- end of build settings ------------------------------------------------

WEI = 10 ** 18
MIN_PRICE_WEI = 10 ** 16      # 0.01 GEN
MAX_TGE_WINDOW_S = 365 * 86400
MAX_DELIVERY_S = 7 * 86400
MAX_MARKETS = 500
MAX_OFFERS = 5000
MAX_OFFERS_PER_MARKET = 300
MAX_PAGE_CHARS = 200000
MIN_TIME = 1600000000
# Shared hosting roots: anyone can publish a page under these, so they can
# never be an official domain (a project's own subdomain of them is fine).
SHARED_HOSTS = (
    "github.io", "gitlab.io", "vercel.app", "netlify.app", "pages.dev", "web.app",
    "firebaseapp.com", "herokuapp.com", "gitbook.io", "notion.site", "medium.com",
    "substack.com", "mirror.xyz", "blogspot.com", "wordpress.com", "wixsite.com",
    "x.com", "twitter.com", "t.me", "discord.com", "discord.gg", "linktr.ee",
    "google.com", "docs.google.com", "sites.google.com", "youtube.com", "reddit.com",
    "github.com", "raw.githubusercontent.com", "ipfs.io", "co", "io", "xyz", "com",
)

# --- interface used to send GEN to a normal wallet (EOA) -------------------
_Wallet = None
try:
    @gl.evm.contract_interface
    class _WalletIface:
        class View:
            pass

        class Write:
            pass

    _Wallet = _WalletIface
except Exception:
    _Wallet = None


def _now() -> int:
    t = 0
    try:
        t = int(datetime.now(timezone.utc).timestamp())
    except Exception:
        t = 0
    if t < MIN_TIME:
        try:
            s = str(gl.message_raw["datetime"])
            t = int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            t = 0
    if t < MIN_TIME:
        raise Exception("Could not read the transaction time")
    return t


def _safe_now() -> int:
    # views: if the clock can't be read, show stored states (the website
    # also recomputes the status from the stored times)
    try:
        return _now()
    except Exception:
        return 0


def _pay(to_hex: str, amount: int) -> None:
    if amount <= 0:
        return
    to = Address(to_hex)
    v = u256(amount)
    if _Wallet is not None:
        try:
            _Wallet(to).emit_transfer(value=v)
            return
        except Exception:
            pass
    fn = getattr(gl, "get_contract_at", None)
    if fn is not None:
        try:
            fn(to).emit_transfer(value=v)
            return
        except Exception:
            pass
    ca = getattr(gl, "ContractAt", None)
    if ca is not None:
        ca(to).emit_transfer(value=v)
        return
    raise Exception("GEN transfer is not available on this network")


# ---------------- pure helpers (unit tested) --------------------------------

def parse_amount18(s: str) -> int:
    # "1000.5" -> 1000.5 * 10^18 (exact, no floats). -1 if invalid.
    t = str(s).strip()
    if len(t) == 0 or len(t) > 40:
        return -1
    parts = t.split(".")
    if len(parts) > 2:
        return -1
    a = parts[0]
    b = parts[1] if len(parts) == 2 else ""
    if a == "":
        a = "0"
    if not a.isdigit() or (b != "" and not b.isdigit()) or len(b) > 18:
        return -1
    return int(a) * WEI + int((b + "0" * 18)[:18])


def fmt18(v: int) -> str:
    w = int(v)
    neg = w < 0
    w = abs(w)
    whole = w // WEI
    frac = str(w % WEI).rjust(18, "0").rstrip("0")
    return ("-" if neg else "") + str(whole) + ("." + frac if frac else "")


def required_raw(amount18: int, decimals: int) -> int:
    # smallest on-chain amount (in token base units) that is >= amount
    d = int(decimals)
    num = int(amount18) * (10 ** d)
    return -(-num // WEI)


def is_evm_address(s: str) -> bool:
    return re.fullmatch(r"0x[0-9a-fA-F]{40}", str(s).strip()) is not None


def is_tx_hash(s: str) -> bool:
    return re.fullmatch(r"0x[0-9a-fA-F]{64}", str(s).strip()) is not None


def is_symbol(s: str) -> bool:
    return re.fullmatch(r"[A-Z0-9]{1,12}", str(s)) is not None


def is_domain(s: str) -> bool:
    d = str(s)
    if len(d) < 4 or len(d) > 100 or "." not in d:
        return False
    for label in d.split("."):
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", label):
            return False
    return True


def url_on_domain(url: str, domain: str) -> bool:
    # https only; host must be the domain or a subdomain of it.
    u = str(url).strip()
    if len(u) > 400 or not u.lower().startswith("https://"):
        return False
    if any(c in u for c in " \t\r\n\\"):
        return False
    rest = u[8:]
    cut = len(rest)
    for ch in "/?#":
        i = rest.find(ch)
        if i >= 0 and i < cut:
            cut = i
    host = rest[:cut].lower()
    if "@" in host or ":" in host or host == "":
        return False
    return host == domain or host.endswith("." + domain)


def json_from(text: str):
    t = str(text).strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except Exception:
        pass
    a = t.find("{")
    b = t.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except Exception:
            pass
    return None


def iso_to_ts(s) -> int:
    try:
        return int(datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def symbol_on_page(page: str, symbol: str) -> bool:
    pat = r"(?<![A-Za-z0-9])" + re.escape(symbol) + r"(?![A-Za-z0-9])"
    return re.search(pat, page, re.IGNORECASE) is not None


def check_tge(page: str, token_text: str, address: str, symbol: str) -> str:
    # The ONLY thing validators compare for a TGE proposal.
    p = str(page or "")[:MAX_PAGE_CHARS]
    if len(p.strip()) == 0:
        return "UNKNOWN"
    if address.lower() not in p.lower():
        return "ADDRESS_NOT_ON_PAGE"
    if not symbol_on_page(p, symbol):
        return "SYMBOL_NOT_ON_PAGE"
    d = json_from(token_text)
    if not isinstance(d, dict):
        return "UNKNOWN"
    if "symbol" not in d and "decimals" not in d:
        return "NOT_A_TOKEN"
    if str(d.get("type", "")).upper() != "ERC-20":
        return "NOT_A_TOKEN"
    a = str(d.get("address_hash", d.get("address", ""))).lower()
    if a and a != address.lower():
        return "NOT_A_TOKEN"
    sym = str(d.get("symbol") or "").strip().upper()
    if sym != symbol:
        return "SYMBOL_MISMATCH:" + sym[:16]
    try:
        dec = int(d.get("decimals"))
    except Exception:
        return "UNKNOWN"
    if dec < 0 or dec > 36:
        return "NOT_A_TOKEN"
    return "VERIFIED:" + str(dec)


def _tok_addr(t: dict) -> str:
    tok = t.get("token") or {}
    return str(tok.get("address_hash", tok.get("address", ""))).lower()


def _hash_of(x) -> str:
    if isinstance(x, dict):
        return str(x.get("hash", "")).lower()
    return str(x or "").lower()


def check_delivery(tx_text: str, transfers_text: str, tx_hash: str, token: str, sender: str,
                   receiver: str, need_raw: int, min_ts: int, max_ts: int, min_conf: int) -> str:
    # The ONLY thing validators compare for a delivery.
    d = json_from(tx_text)
    if not isinstance(d, dict):
        return "UNKNOWN"
    if "hash" not in d:
        return "TX_NOT_FOUND" if ("message" in d or "status" not in d) else "UNKNOWN"
    if str(d.get("hash", "")).lower() != tx_hash.lower():
        return "UNKNOWN"
    if d.get("status") != "ok" or d.get("result") != "success":
        return "TX_FAILED_OR_PENDING"
    try:
        conf = int(d.get("confirmations") or 0)
    except Exception:
        conf = 0
    if conf < min_conf:
        return "NOT_ENOUGH_CONFIRMATIONS"
    ts = iso_to_ts(d.get("timestamp"))
    if ts <= 0:
        return "UNKNOWN"
    if ts < min_ts:
        return "SENT_BEFORE_TRADE"
    if ts > max_ts:
        return "SENT_AFTER_DEADLINE"
    items = d.get("token_transfers") or []
    if d.get("token_transfers_overflow"):
        e = json_from(transfers_text)
        if not isinstance(e, dict) or not isinstance(e.get("items"), list) or e.get("next_page_params"):
            return "UNKNOWN"
        items = e["items"]
    total = 0
    for t in items:
        if not isinstance(t, dict):
            continue
        if _tok_addr(t) != token.lower():
            continue
        if _hash_of(t.get("from")) != sender.lower() or _hash_of(t.get("to")) != receiver.lower():
            continue
        try:
            total += int((t.get("total") or {}).get("value"))
        except Exception:
            return "UNKNOWN"
    if total <= 0:
        return "NO_MATCHING_TRANSFER"
    if total < need_raw:
        return "AMOUNT_TOO_LOW:" + str(total)
    return "DELIVERED"


def _read_url(url: str) -> str:
    # only called inside a non-deterministic block
    try:
        res = gl.nondet.web.get(url)
        t = res.body.decode("utf-8")
        if t:
            return t
    except Exception:
        pass
    try:
        return str(gl.nondet.web.render(url, mode="text"))
    except Exception:
        return ""


def _read_json(url: str) -> str:
    # explorer API; falls back to a rendered fetch if a plain GET is blocked
    try:
        res = gl.nondet.web.get(url)
        t = res.body.decode("utf-8")
        if json_from(t) is not None:
            return t
    except Exception:
        pass
    try:
        return str(gl.nondet.web.render(url, mode="text"))
    except Exception:
        return ""


class PreTGEDesk(gl.Contract):
    market_count: u256
    offer_count: u256
    markets: TreeMap[str, str]
    offers: TreeMap[str, str]
    market_offers: TreeMap[str, str]
    user_offers: TreeMap[str, str]
    used_tx: TreeMap[str, str]

    def __init__(self):
        self.market_count = 0
        self.offer_count = 0

    # ---------------- internal ----------------

    def _market(self, market_id: str) -> dict:
        k = str(market_id).strip()
        if k not in self.markets:
            raise Exception("Market not found")
        return json.loads(self.markets[k])

    def _save_market(self, m: dict) -> None:
        self.markets[m["id"]] = json.dumps(m)

    def _offer(self, offer_id: str) -> dict:
        k = str(offer_id).strip()
        if k not in self.offers:
            raise Exception("Offer not found")
        return json.loads(self.offers[k])

    def _save_offer(self, o: dict) -> None:
        self.offers[o["id"]] = json.dumps(o)

    def _status(self, m: dict, now: int) -> str:
        s = m["status"]
        if now <= 0:
            return s
        if s == "PRE":
            return "NO_TGE" if now >= int(m["tge_deadline"]) else "PRE"
        if s == "PENDING_LIVE":
            return "LIVE" if now >= int(m["proposed_at"]) + CHALLENGE_S else "PENDING_LIVE"
        return s  # AMBIGUOUS

    def _live_at(self, m: dict) -> int:
        return int(m["proposed_at"]) + CHALLENGE_S

    def _index_user(self, addr: str, oid: str) -> None:
        k = addr.lower()
        lst = json.loads(self.user_offers[k]) if k in self.user_offers else []
        if oid not in lst:
            lst.append(oid)
        self.user_offers[k] = json.dumps(lst)

    def _sender(self) -> str:
        return gl.message.sender_address.as_hex

    def _verify_tge(self, m: dict, address: str, evidence_url: str) -> str:
        url = evidence_url
        token_url = EXPLORER + "/api/v2/tokens/" + address
        symbol = m["symbol"]

        def run() -> str:
            page = _read_url(url)
            token_text = _read_json(token_url)
            return check_tge(page, token_text, address, symbol)

        return str(gl.eq_principle.strict_eq(run))

    def _tge_input_checks(self, m: dict, address: str, evidence_url: str) -> str:
        a = str(address).strip()
        if not is_evm_address(a):
            raise Exception("Token address must be 0x followed by 40 hex characters")
        u = str(evidence_url).strip()
        if not url_on_domain(u, m["official_domain"]):
            raise Exception("evidence_url must be an https:// page on the committed official domain " + m["official_domain"])
        return a

    # ---------------- markets ----------------

    @gl.public.write
    def create_market(self, symbol: str, name: str, official_domain: str,
                      tge_window_seconds: int, delivery_seconds: int) -> str:
        now = _now()
        n = int(self.market_count)
        if n >= MAX_MARKETS:
            raise Exception("Market limit reached")
        sym = str(symbol).strip().upper()
        if not is_symbol(sym):
            raise Exception("Ticker must be 1-12 characters A-Z or 0-9")
        nm = str(name).strip()
        if len(nm) < 1 or len(nm) > 40:
            raise Exception("Name must be 1-40 characters")
        dom = str(official_domain).strip().lower()
        if dom.startswith("www."):
            dom = dom[4:]
        if not is_domain(dom):
            raise Exception("official_domain must be a plain domain like project.xyz (no https://, no path)")
        if dom in SHARED_HOSTS:
            raise Exception(dom + " is shared hosting where anyone can publish. Use the project's own domain or its own subdomain")
        tw = int(tge_window_seconds)
        if tw < MIN_TGE_WINDOW_S or tw > MAX_TGE_WINDOW_S:
            raise Exception("TGE window must be " + str(MIN_TGE_WINDOW_S) + "-" + str(MAX_TGE_WINDOW_S) + " seconds")
        dl = int(delivery_seconds)
        if dl < MIN_DELIVERY_S or dl > MAX_DELIVERY_S:
            raise Exception("Delivery window must be " + str(MIN_DELIVERY_S) + "-" + str(MAX_DELIVERY_S) + " seconds")
        mid = str(n)
        m = {
            "id": mid,
            "symbol": sym,
            "name": nm,
            "chain": CHAIN,
            "official_domain": dom,
            "creator": self._sender(),
            "created_at": now,
            "tge_deadline": now + tw,
            "delivery_s": dl,
            "status": "PRE",
            "token_address": "",
            "decimals": -1,
            "evidence_url": "",
            "proposed_at": 0,
            "proposer": "",
            "challenge": {},
            "last_check": {},
            "offer_count": 0,
        }
        self._save_market(m)
        self.market_offers[mid] = "[]"
        self.market_count = n + 1
        return mid

    @gl.public.write
    def propose_tge(self, market_id: str, token_address: str, evidence_url: str) -> str:
        now = _now()
        m = self._market(market_id)
        st = self._status(m, now)
        if st != "PRE":
            raise Exception("Market is not waiting for a TGE (status " + st + ")")
        addr = self._tge_input_checks(m, token_address, evidence_url)
        u = str(evidence_url).strip()
        verdict = self._verify_tge(m, addr, u)
        m["last_check"] = {"at": now, "kind": "propose", "address": addr, "url": u, "verdict": verdict}
        if verdict.startswith("VERIFIED:"):
            m["status"] = "PENDING_LIVE"
            m["token_address"] = addr
            m["decimals"] = int(verdict.split(":")[1])
            m["evidence_url"] = u
            m["proposed_at"] = now
            m["proposer"] = self._sender()
        self._save_market(m)
        return verdict

    @gl.public.write
    def challenge_tge(self, market_id: str, other_address: str, evidence_url: str) -> str:
        now = _now()
        m = self._market(market_id)
        st = self._status(m, now)
        if st != "PENDING_LIVE":
            raise Exception("Only a TGE proposal inside its challenge window can be challenged (status " + st + ")")
        addr = self._tge_input_checks(m, other_address, evidence_url)
        if addr.lower() == str(m["token_address"]).lower():
            raise Exception("This is the proposed address. A challenge needs a DIFFERENT address")
        u = str(evidence_url).strip()
        verdict = self._verify_tge(m, addr, u)
        m["last_check"] = {"at": now, "kind": "challenge", "address": addr, "url": u, "verdict": verdict}
        if verdict.startswith("VERIFIED:"):
            # two different addresses both pass: nobody can say which token
            # is the real one, so every trade is refunded.
            m["status"] = "AMBIGUOUS"
            m["challenge"] = {"address": addr, "url": u, "by": self._sender(), "at": now}
        self._save_market(m)
        return "AMBIGUOUS" if verdict.startswith("VERIFIED:") else verdict

    # ---------------- offers / trades ----------------

    @gl.public.write.payable
    def create_offer(self, market_id: str, token_amount: str, price_gen: str, seller_chain_address: str) -> str:
        now = _now()
        m = self._market(market_id)
        st = self._status(m, now)
        if st != "PRE":
            raise Exception("New offers are only allowed before the TGE (status " + st + ")")
        if int(self.offer_count) >= MAX_OFFERS or int(m["offer_count"]) >= MAX_OFFERS_PER_MARKET:
            raise Exception("Offer limit reached")
        amt = parse_amount18(token_amount)
        if amt <= 0:
            raise Exception("Token amount must be a positive number like 1000 or 0.5")
        price = parse_amount18(price_gen)
        if price < MIN_PRICE_WEI:
            raise Exception("Price must be at least 0.01 GEN")
        sca = str(seller_chain_address).strip()
        if not is_evm_address(sca):
            raise Exception("Seller chain address must be 0x followed by 40 hex characters")
        paid = int(gl.message.value)
        if paid < price:
            raise Exception("Send the bond with this transaction: " + fmt18(price) + " GEN (equal to the price)")
        oid = str(int(self.offer_count))
        seller = self._sender()
        o = {
            "id": oid,
            "market_id": m["id"],
            "seller": seller,
            "seller_chain": sca,
            "buyer": "",
            "buyer_chain": "",
            "token_amount": fmt18(amt),
            "amount18": str(amt),
            "price_wei": str(price),
            "bond_wei": str(price),
            "status": "OPEN",
            "created_at": now,
            "filled_at": 0,
            "delivery_tx": "",
            "last_check": {},
            "settled_at": 0,
            "payouts": [],
        }
        self._save_offer(o)
        self.offer_count = int(oid) + 1
        lst = json.loads(self.market_offers[m["id"]])
        lst.append(oid)
        self.market_offers[m["id"]] = json.dumps(lst)
        m["offer_count"] = int(m["offer_count"]) + 1
        self._save_market(m)
        self._index_user(seller, oid)
        if paid > price:
            _pay(seller, paid - price)
        return oid

    @gl.public.write.payable
    def fill_offer(self, offer_id: str, buyer_chain_address: str) -> str:
        now = _now()
        o = self._offer(offer_id)
        if o["status"] != "OPEN":
            raise Exception("Offer is not open (status " + o["status"] + ")")
        m = self._market(o["market_id"])
        st = self._status(m, now)
        if st != "PRE":
            raise Exception("Offers can only be filled before the TGE (status " + st + ")")
        buyer = self._sender()
        if buyer.lower() == str(o["seller"]).lower():
            raise Exception("The seller cannot fill their own offer")
        bca = str(buyer_chain_address).strip()
        if not is_evm_address(bca):
            raise Exception("Buyer chain address must be 0x followed by 40 hex characters")
        if bca.lower() == str(o["seller_chain"]).lower():
            raise Exception("Buyer and seller chain addresses must be different")
        price = int(o["price_wei"])
        paid = int(gl.message.value)
        if paid < price:
            raise Exception("Send the price with this transaction: " + fmt18(price) + " GEN")
        o["buyer"] = buyer
        o["buyer_chain"] = bca
        o["status"] = "FILLED"
        o["filled_at"] = now
        self._save_offer(o)
        self._index_user(buyer, o["id"])
        if paid > price:
            _pay(buyer, paid - price)
        return "FILLED"

    @gl.public.write
    def cancel_offer(self, offer_id: str) -> str:
        o = self._offer(offer_id)
        if o["status"] != "OPEN":
            raise Exception("Only an open (unfilled) offer can be cancelled")
        if self._sender().lower() != str(o["seller"]).lower():
            raise Exception("Only the seller can cancel. After the TGE deadline anyone can use settle()")
        return self._close_open(o, _now(), "cancelled by seller")

    def _close_open(self, o: dict, now: int, why: str) -> str:
        bond = int(o["bond_wei"])
        o["status"] = "CANCELLED"
        o["settled_at"] = now
        o["payouts"] = [{"to": o["seller"], "amount_wei": str(bond), "why": why}]
        self._save_offer(o)
        _pay(o["seller"], bond)
        return "CANCELLED"

    @gl.public.write
    def submit_delivery(self, offer_id: str, tx_hash: str) -> str:
        now = _now()
        o = self._offer(offer_id)
        if o["status"] != "FILLED":
            raise Exception("Offer is not waiting for delivery (status " + o["status"] + ")")
        m = self._market(o["market_id"])
        st = self._status(m, now)
        if st != "LIVE":
            raise Exception("Delivery opens when the TGE is final (status " + st + ")")
        deadline = self._live_at(m) + int(m["delivery_s"])
        if now >= deadline:
            raise Exception("The delivery window has closed. Use settle()")
        h = str(tx_hash).strip().lower()
        if not is_tx_hash(h):
            raise Exception("tx_hash must be 0x followed by 64 hex characters")
        if h in self.used_tx:
            raise Exception("This transaction was already used for offer " + self.used_tx[h])

        token = str(m["token_address"])
        need = required_raw(int(o["amount18"]), int(m["decimals"]))
        sender = str(o["seller_chain"])
        receiver = str(o["buyer_chain"])
        min_ts = 0 if ALLOW_PAST_TX else int(o["filled_at"])
        max_ts = deadline
        tx_url = EXPLORER + "/api/v2/transactions/" + h
        tr_url = tx_url + "/token-transfers"

        def run() -> str:
            tx_text = _read_json(tx_url)
            d = json_from(tx_text)
            tr_text = ""
            if isinstance(d, dict) and d.get("token_transfers_overflow"):
                tr_text = _read_json(tr_url)
            return check_delivery(tx_text, tr_text, h, token, sender, receiver, need, min_ts, max_ts, MIN_CONFIRMATIONS)

        verdict = str(gl.eq_principle.strict_eq(run))
        o["last_check"] = {"at": now, "tx": h, "verdict": verdict, "need_raw": str(need)}
        if verdict != "DELIVERED":
            self._save_offer(o)
            return verdict

        price = int(o["price_wei"])
        bond = int(o["bond_wei"])
        o["status"] = "DELIVERED"
        o["delivery_tx"] = h
        o["settled_at"] = now
        o["payouts"] = [{"to": o["seller"], "amount_wei": str(price + bond), "why": "tokens delivered: price + bond back"}]
        self.used_tx[h] = o["id"]
        self._save_offer(o)
        _pay(o["seller"], price + bond)
        return "DELIVERED"

    @gl.public.write
    def settle(self, offer_id: str) -> str:
        # Anyone may call. Moves money only when the rules say it is final.
        now = _now()
        o = self._offer(offer_id)
        m = self._market(o["market_id"])
        st = self._status(m, now)
        s = o["status"]
        if s == "OPEN":
            if st == "PRE":
                raise Exception("Offer is still open. The seller can cancel it")
            return self._close_open(o, now, "not filled before the TGE: bond back")
        if s != "FILLED":
            raise Exception("Offer is already settled (" + s + ")")
        price = int(o["price_wei"])
        bond = int(o["bond_wei"])
        if st in ("NO_TGE", "AMBIGUOUS"):
            why = "no TGE before the deadline" if st == "NO_TGE" else "TGE address was disputed"
            o["status"] = "REFUNDED"
            o["settled_at"] = now
            o["payouts"] = [
                {"to": o["buyer"], "amount_wei": str(price), "why": why + ": price back"},
                {"to": o["seller"], "amount_wei": str(bond), "why": why + ": bond back"},
            ]
            self._save_offer(o)
            _pay(o["buyer"], price)
            _pay(o["seller"], bond)
            return "REFUNDED"
        if st == "LIVE" and now >= self._live_at(m) + int(m["delivery_s"]):
            o["status"] = "DEFAULTED"
            o["settled_at"] = now
            o["payouts"] = [{"to": o["buyer"], "amount_wei": str(price + bond), "why": "not delivered in time: price + seller bond"}]
            self._save_offer(o)
            _pay(o["buyer"], price + bond)
            return "DEFAULTED"
        raise Exception("Nothing to settle yet (market " + st + ")")

    # ---------------- views ----------------

    def _market_view(self, m: dict, now: int) -> dict:
        st = self._status(m, now)
        out = dict(m)
        out["current_status"] = st
        if m["status"] in ("PENDING_LIVE",) or st == "LIVE":
            out["live_at"] = self._live_at(m)
            out["delivery_deadline"] = self._live_at(m) + int(m["delivery_s"])
        return out

    def _offer_view(self, o: dict, m: dict, now: int) -> dict:
        st = self._status(m, now)
        out = dict(o)
        out["price_gen"] = fmt18(int(o["price_wei"]))
        out["bond_gen"] = fmt18(int(o["bond_wei"]))
        out["market_status"] = st
        out["symbol"] = m["symbol"]
        if m["decimals"] is not None and int(m["decimals"]) >= 0:
            out["need_raw"] = str(required_raw(int(o["amount18"]), int(m["decimals"])))
        s = o["status"]
        out["can_fill"] = s == "OPEN" and st == "PRE"
        out["can_deliver"] = s == "FILLED" and st == "LIVE" and now < self._live_at(m) + int(m["delivery_s"])
        out["can_settle"] = (s == "OPEN" and st != "PRE") or (s == "FILLED" and (
            st in ("NO_TGE", "AMBIGUOUS") or (st == "LIVE" and now >= self._live_at(m) + int(m["delivery_s"]))))
        return out

    @gl.public.view
    def get_rules(self) -> str:
        return json.dumps({
            "build": BUILD,
            "chain": CHAIN,
            "explorer": EXPLORER,
            "challenge_s": CHALLENGE_S,
            "min_tge_window_s": MIN_TGE_WINDOW_S,
            "max_tge_window_s": MAX_TGE_WINDOW_S,
            "min_delivery_s": MIN_DELIVERY_S,
            "max_delivery_s": MAX_DELIVERY_S,
            "min_confirmations": MIN_CONFIRMATIONS,
            "allow_past_tx": ALLOW_PAST_TX,
            "bond": "equal to the price",
            "min_price_gen": fmt18(MIN_PRICE_WEI),
            "shared_pool": False,
            "owner": None,
        })

    @gl.public.view
    def get_counts(self) -> str:
        return json.dumps({"markets": int(self.market_count), "offers": int(self.offer_count)})

    @gl.public.view
    def get_markets(self) -> str:
        now = _safe_now()
        out = []
        for i in range(int(self.market_count)):
            out.append(self._market_view(json.loads(self.markets[str(i)]), now))
        return json.dumps(out)

    @gl.public.view
    def get_market(self, market_id: str) -> str:
        return json.dumps(self._market_view(self._market(market_id), _safe_now()))

    @gl.public.view
    def get_offers(self, market_id: str) -> str:
        now = _safe_now()
        m = self._market(market_id)
        ids = json.loads(self.market_offers[m["id"]])
        return json.dumps([self._offer_view(json.loads(self.offers[i]), m, now) for i in ids])

    @gl.public.view
    def get_offer(self, offer_id: str) -> str:
        o = self._offer(offer_id)
        return json.dumps(self._offer_view(o, self._market(o["market_id"]), _safe_now()))

    @gl.public.view
    def get_offers_of(self, wallet: str) -> str:
        now = _safe_now()
        k = str(wallet).strip().lower()
        ids = json.loads(self.user_offers[k]) if k in self.user_offers else []
        out = []
        for i in ids:
            o = json.loads(self.offers[i])
            out.append(self._offer_view(o, self._market(o["market_id"]), now))
        return json.dumps(out)

    @gl.public.view
    def is_live(self, market_id: str) -> bool:
        # trust primitive for other contracts
        return self._status(self._market(market_id), _safe_now()) == "LIVE"
