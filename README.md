# PreTGE Desk: pre-market escrow on GenLayer

**Trade tokens before their TGE without trusting the other side.** Both sides lock GEN. GenLayer validators confirm the official token address and read the delivery on-chain. Then the contract pays the right side, or gives everyone their money back.

Live app: https://gurusankar55.github.io/pretgedesk/

## The problem

Pre-market trading of points and pre-TGE allocations is big in crypto. Today it runs on trust:

- **OTC deals in Telegram or X DMs.** One side sends first and hopes the other side pays or delivers.
- **Centralised pre-market desks.** An operator decides which token is "the real one" and whether a delivery counts.

A plain smart contract can't take over this job. It can't answer the two questions that matter:

1. Which contract address is the project's **official** token?
2. Did the seller really **deliver** those tokens to the buyer on another chain?

GenLayer validators can read the web and an explorer API, and they must agree on the answer.

## How it works

```
create_market(ticker, name, official_domain, tge_window, delivery_window)
        │
create_offer  ── seller locks a bond = price ──►  OPEN
fill_offer    ── buyer locks the price      ──►  FILLED
        │
propose_tge(address, page on official domain) ── validators: VERIFIED ──► PENDING_LIVE
        │        (challenge window: anyone may show a DIFFERENT address that also passes)
        ├── challenge passes ─────────────► AMBIGUOUS ── settle ──► REFUNDED (both sides)
        └── window ends ──────────────────► LIVE
                                              │
submit_delivery(tx_hash) ── validators read the tx ── DELIVERED ──► seller gets price + bond
settle() after the delivery window ─────────────────── DEFAULTED ──► buyer gets price + bond
settle() if no TGE before the deadline ─────────────── REFUNDED ───► both sides get their own money back
```

### 1. TGE check (`propose_tge`, `challenge_tge`)

Deterministic checks run first, with no validator work:

- The page must be `https://` on the official domain committed when the market was created, or on one of its subdomains. `user@host`, ports, look-alike hosts and `http://` are refused.
- Shared hosting roots (`github.io`, `vercel.app`, `x.com`, `gitbook.io` …) can't be an official domain, because anyone can publish there.

Then every validator does the same work on its own (`gl.eq_principle.strict_eq`):

- It fetches the page and checks, in code, that the token address is on it and the ticker appears as a whole word.
- It reads the token from the Blockscout explorer API. The token must be ERC-20 with the same ticker.
- It returns one verdict: `VERIFIED:<decimals>`, `ADDRESS_NOT_ON_PAGE`, `SYMBOL_NOT_ON_PAGE`, `SYMBOL_MISMATCH:<x>`, `NOT_A_TOKEN` or `UNKNOWN`.

There is no LLM in this contract. Verdicts come from exact checks, so honest validators always return the same string.

**Challenge window (1 hour).** A page can list more than one address. While the window is open, anyone can show a different address that passes the same check. If one does, nobody can say which token is real, so the market becomes `AMBIGUOUS` and every trade is refunded.

### 2. Delivery check (`submit_delivery`)

Each validator reads `/api/v2/transactions/<hash>` from the explorer and checks, in code:

- the transaction succeeded and has at least 10 confirmations;
- it was sent after the trade was filled and before the delivery deadline;
- the sum of transfers **of the official token**, **from the seller's committed wallet** to **the buyer's committed wallet**, is at least the amount, rounded up to the token's decimals.

A transaction hash can be used only once across the whole contract.

### 3. Settlement (`settle`, anyone can call)

| outcome | seller | buyer |
|---|---|---|
| delivered in time | price + bond | the tokens (on-chain) |
| not delivered in time | – | price + seller's bond |
| no TGE by the deadline / disputed TGE | bond back | price back |
| offer never filled | bond back | – |

## Funds safety

- **Per-trade escrow.** There is no shared pool. A payout only uses the price and bond of that one trade, so one trade can never pay out another trade's money (tested).
- **No owner, no admin, no pause, no fees.** Nobody can change a market after it is created.
- **Fail-safe default.** Unreadable sources return `UNKNOWN`, and nothing moves. No TGE means refunds.
- **One final state per trade.** `DELIVERED`, `DEFAULTED`, `REFUNDED` and `CANCELLED` exclude each other, and a settled trade can't be settled again.
- The seller can't fill their own offer, and the buyer and seller wallets on the chain must be different.

## Production and demo are separate contracts

| | `contracts/pretge_desk.py` (production) | `contracts/pretge_desk_demo.py` (test only) |
|---|---|---|
| chain | Base mainnet | Base Sepolia testnet |
| challenge window | 1 hour | 2 minutes |
| min TGE / delivery window | 1 hour | 1 minute |
| confirmations | 10 | 1 |
| delivery tx must be after the fill | **yes** | no, so a public testnet transfer can be reused in the Studio test |

The two files differ **only** in that settings block. A unit test (`SourceMatch`) enforces this. They share no storage and no balance.

## Methods

**Write:** `create_market`, `propose_tge`, `challenge_tge`, `create_offer` (payable, bond), `fill_offer` (payable, price), `cancel_offer`, `submit_delivery`, `settle`

**View:** `get_rules`, `get_counts`, `get_markets`, `get_market`, `get_offers`, `get_offer`, `get_offers_of`, `is_live`

Other contracts can use `is_live(market_id)` as a "this token's TGE is final" signal.

## Tests

```
python -m unittest tests/test_pretge_desk.py -v
```

There are 23 offline tests. They use a small stub of the `genlayer` module, import the real contract files unchanged, mock the web pages and explorer responses, and control the clock. The tests cover:

- domain tricks;
- every failed TGE and delivery verdict, each of which moves no money;
- the challenge path;
- default, no-TGE and cancel refunds;
- split transfers and explorer overflow;
- tx reuse;
- isolation between trades;
- a check that every GEN that comes in also goes out;
- the demo/production source match.

The manual GenLayer Studio test is in `tests/STUDIO_TEST_PLAN.md`. Evidence pages used there are in `docs/` (`tge-demo.html`, `tge-two.html`, `tge-base.html`).

## Limits

- Delivery is read from one explorer (Blockscout). If it is down, verdicts are `UNKNOWN`, nothing moves and you can retry. A wrong explorer is the main trust assumption.
- The seller must call `submit_delivery` before the delivery deadline. A transfer sent in time but submitted late doesn't count.
- The official domain is chosen by whoever creates the market. Traders should check it before trading. A project team that controls its own domain could make its token "ambiguous". That only leads to refunds, never to a wrong payout.
- v1 supports one EVM chain per build (Base). Prices are in GEN.

## Files

```
contracts/pretge_desk.py        production Intelligent Contract
contracts/pretge_desk_demo.py   demo build (Base Sepolia, short windows)
tests/test_pretge_desk.py       23 offline unit tests
tests/genlayer_stub.py          stub used by the tests
tests/STUDIO_TEST_PLAN.md       manual Studio scenarios
docs/index.html                 the web app (GitHub Pages)
docs/config.js                  deployed contract addresses
docs/tge-*.html                 evidence pages for the Studio test
```

License: MIT
