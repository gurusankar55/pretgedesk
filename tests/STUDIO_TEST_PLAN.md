# PreTGE Desk — Studio test plan

Network: GenLayer Studio (studio.genlayer.com). Use two Studio accounts:

- **Account 1 = seller**
- **Account 2 = buyer**

Run these steps after GitHub Pages is live, so these pages open:
`https://gurusankar55.github.io/pretgedesk/tge-demo.html`,
`https://gurusankar55.github.io/pretgedesk/tge-two.html`,
`https://gurusankar55.github.io/pretgedesk/tge-base.html`

## Deploy

1. Deploy `contracts/pretge_desk_demo.py` with no constructor arguments, and save the address as DEMO.
2. Deploy `contracts/pretge_desk.py` with no constructor arguments, and save the address as PRODUCTION.
3. On both contracts, call `get_rules()`. The demo shows `build: demo, chain: base-sepolia`. The production contract shows `build: production, chain: base, allow_past_tx: false`.

Fixed values used below (a real public Base Sepolia USDC transfer of 0.001 USDC):

| name | value |
|---|---|
| USDC (Base Sepolia) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |
| second "USDC" (Base Sepolia) | `0x9C868614ffca7da36B36330b1f317B117c7834dE` |
| seller wallet on chain | `0x4B063d567910269f7714603A0501A560691DA31f` |
| buyer wallet on chain | `0xA849bbaD82F9edafDf9A5550CC874276138779d9` |
| delivery tx | `0xd385c5f5dbd68b7bc8f68b5c8eca7797a87cf2e841fed5b91384aec31cec493e` |

## Demo contract

### A. Delivered: seller paid (market 0)

| step | account | call | expected |
|---|---|---|---|
| A1 | 1 | `create_market("USDC","Demo USDC","gurusankar55.github.io",900,600)` | `"0"` |
| A2 | 1 | `create_offer("0","0.001","1","0x4B063d567910269f7714603A0501A560691DA31f")` + value **1 GEN** | `"0"` |
| A3 | 1 | `fill_offer("0","0xA849bbaD82F9edafDf9A5550CC874276138779d9")` + 1 GEN | error: the seller cannot fill their own offer |
| A4 | 2 | same `fill_offer` + value **1 GEN** | `"FILLED"` |
| A5 | 2 | `propose_tge("0","0x036CbD53842c5426634e7929541eC2318f3dCF7e","https://evil.io/x")` | error: not on the committed official domain |
| A6 | 2 | `propose_tge("0","0x036CbD53842c5426634e7929541eC2318f3dCF7e","https://gurusankar55.github.io/pretgedesk/tge-demo.html")` | `"VERIFIED:6"` |
| A7 | 1 | `submit_delivery("0","0xd385…493e")` straight away | error: delivery opens when the TGE is final (PENDING_LIVE) |
| A8 | 1 | wait 2 minutes, then `submit_delivery("0","0xd385c5f5dbd68b7bc8f68b5c8eca7797a87cf2e841fed5b91384aec31cec493e")` | `"DELIVERED"`, account 1 receives **2 GEN** |
| A9 | – | `get_offer("0")` | status `DELIVERED`, one payout of 2 GEN to account 1 |

### B. Not delivered: buyer gets price + bond (market 1)

| step | account | call | expected |
|---|---|---|---|
| B1 | 1 | `create_market("USDC","Default test","gurusankar55.github.io",900,180)` | `"1"` |
| B2 | 1 | `create_offer("1","0.001","1","0x4B063d567910269f7714603A0501A560691DA31f")` + 1 GEN | `"1"` |
| B3 | 2 | `fill_offer("1","0xA849bbaD82F9edafDf9A5550CC874276138779d9")` + 1 GEN | `"FILLED"` |
| B4 | 2 | `propose_tge("1", USDC, tge-demo.html)` | `"VERIFIED:6"` |
| B5 | 1 | after 2 min: `submit_delivery("1","0xd385…493e")` | error: transaction already used for offer 0 |
| B6 | 2 | after 3 more minutes: `settle("1")` | `"DEFAULTED"`, account 2 receives **2 GEN** |

### C. Disputed TGE: everyone refunded (market 2)

| step | account | call | expected |
|---|---|---|---|
| C1 | 1 | `create_market("USDC","Dispute test","gurusankar55.github.io",900,600)` | `"2"` |
| C2 | 1/2 | `create_offer("2",…)` + 1 GEN, then `fill_offer("2",…)` + 1 GEN | `"2"`, `"FILLED"` |
| C3 | 2 | `propose_tge("2","0x036CbD53842c5426634e7929541eC2318f3dCF7e","https://gurusankar55.github.io/pretgedesk/tge-two.html")` | `"VERIFIED:6"` |
| C4 | 1 | `challenge_tge("2","0x9C868614ffca7da36B36330b1f317B117c7834dE","https://gurusankar55.github.io/pretgedesk/tge-two.html")` | `"AMBIGUOUS"` |
| C5 | any | `settle("2")` | `"REFUNDED"`: 1 GEN back to each side |

### D. No TGE before the deadline (market 3)

| step | account | call | expected |
|---|---|---|---|
| D1 | 1 | `create_market("ZZZ","Never launches","gurusankar55.github.io",120,600)` | `"3"` |
| D2 | 1 | two offers: `create_offer("3","5","1",seller wallet)` + 1 GEN, twice | `"3"`, `"4"` |
| D3 | 2 | `fill_offer("3", buyer wallet)` + 1 GEN | `"FILLED"` |
| D4 | any | `settle("3")` before 2 min | error: nothing to settle yet |
| D5 | any | after 2 min: `settle("3")` | `"REFUNDED"` |
| D6 | any | `settle("4")` | `"CANCELLED"`: the seller's bond comes back |

### E. Accounting

| check | expected |
|---|---|
| `get_counts()` | `{"markets":4,"offers":5}` |
| contract balance in Studio | 0 GEN: every GEN that came in went out |

## Production contract (real rules, Base mainnet)

| step | account | call | expected |
|---|---|---|---|
| P1 | 1 | `create_market("USDC","Prod test","github.io",3600,3600)` | error: shared hosting |
| P2 | 1 | `create_market("USDC","Prod test","gurusankar55.github.io",60,3600)` | error: TGE window must be 3600–… |
| P3 | 1 | `create_market("USDC","Prod test","gurusankar55.github.io",3600,3600)` | `"0"` |
| P4 | 1 | `create_offer("0","0.02","1","0xd2f749ca9943C0641aFbE46A54704eb6B9E9faa7")` + 1 GEN | `"0"` |
| P5 | 2 | `fill_offer("0","0x7284D41b5b852F2bd4c99bDf95043D84452d299C")` + 1 GEN | `"FILLED"` |
| P6 | 2 | `propose_tge("0","0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","https://gurusankar55.github.io/pretgedesk/tge-base.html")` | `"VERIFIED:6"` |
| P7 | 1 | after 1 hour: `submit_delivery("0","0xa4d1f1b89fe8c80dfc36666a47b0c6d463ac500abcacd22170fb8cca02e0ba24")` | `"SENT_BEFORE_TRADE"`: production rejects an old transfer and moves no money |
