# PropVerify

**AI-powered property listing verifier with public on-chain proof.**
Built for Innoblock 2.0, PS 50 (Real Estate & Land Registry).

## The problem
Scammers post fake rental and sale listings with stolen photos and impossibly low prices, then collect advance fees from renters and buyers. Listing sites can't catch them fast enough, and nobody can independently check whether a listing was ever verified.

## The solution
1. **AI scores every listing** for fraud and explains why.
2. **Verified listings are recorded on Ethereum Sepolia** with the score and the lister's wallet, so the record is public and can't be edited.
3. **Buyers can protect their deposit** with an escrow contract instead of paying scammers directly.

## Features
- **Listing submission:** photos, price, address, description, and a map pin
- **AI fraud score (0-100):** price vs. area average, scam wording, consistency checks, lister history, with plain-language reasons
- **Duplicate photo detection:** perceptual hashing (pHash) catches resized or recompressed stolen photos
- **On-chain record:** oracle-signed score, listing hash and lister wallet stored in `PropertyVerifier.sol`
- **Reports:** each report lowers the trust score, and 3 reports mark a listing "Under review"
- **Lister reputation:** Bronze, Silver and Gold badges built from verified listings
- **Safe-deposit escrow:** `ListingEscrow.sol` holds the deposit until the buyer confirms a visit
- **Public verifier:** look up any listing by ID or transaction hash, with a QR code

## Roles
| Role | What they do |
|---|---|
| **Buyer** | Browse verified listings, view the map, report listings, pay a safe deposit |
| **Seller** | Submit listings, see the AI score, record verified listings on-chain, manage escrow |
| **Admin** | Approve sellers, review flagged listings, resolve escrow disputes |

## How it works
```
Browser (MetaMask + ethers.js)  <->  FastAPI backend (AI score, pHash, oracle signature)
              |
              +-->  Smart contracts on Sepolia  -->  Etherscan (public view)
```
Only hashes are stored on-chain. The backend signs each score, so sellers can't submit fake scores.

## Tech stack
Solidity + Hardhat, OpenZeppelin, Python FastAPI, SQLite, Pillow + imagehash, vanilla JS, ethers.js v6, Leaflet (OpenStreetMap)

## How to run (execution steps)

### 1. Prerequisites
- [Node.js](https://nodejs.org/) 18 or newer
- [Python](https://www.python.org/) 3.10 or newer
- [MetaMask](https://metamask.io/) browser extension
- A free [Alchemy](https://www.alchemy.com/) account (Sepolia RPC URL)
- A free [Etherscan](https://etherscan.io/) API key (only to verify the contract source)

### 2. Set up MetaMask (Sepolia testnet)
1. Turn on **Show test networks** in MetaMask and switch to **Sepolia**.
2. Create 3 accounts: **Admin/deployer**, **Seller**, **Buyer**.
3. Fund each with free test ETH from a Sepolia faucet (Alchemy or Google Cloud Web3).
4. Use new wallets made only for this project. Never use a wallet that holds real money.

### 3. Get the code and install dependencies
```bash
git clone <your-repo-url>
cd propverify
npm install
pip install -r backend/requirements.txt
```
Tip: create a Python virtual environment first (`python -m venv venv`, then `venv\Scripts\activate` on Windows or `source venv/bin/activate` on Mac/Linux).

### 4. Configure environment variables
```bash
cp .env.example .env
```
Open `.env` and fill in:
```env
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
PRIVATE_KEY=0xYOUR_ADMIN_WALLET_PRIVATE_KEY      # admin + AI oracle (throwaway wallet only)
ETHERSCAN_API_KEY=your_etherscan_key
DEMO_AUTO_KYC=true                               # optional: one-click seller approval for demos
```
Never commit `.env` to GitHub.

### 5. Run the tests
```bash
npx hardhat test                    # smart contract tests
python -m unittest backend/test_scoring.py   # AI scoring tests (if present)
```

### 6. Deploy the contracts to Sepolia
```bash
npm run deploy:sepolia
```
This deploys the contracts, prints their addresses and saves them to `deployment.json`.
Optional: publish the source on Etherscan so anyone can read it:
```bash
npx hardhat verify --network sepolia <contract-address> <constructor-args-printed-by-deploy>
```

### 7. Start the app
```bash
npm start
```
Open **http://localhost:8000** in the browser where MetaMask is installed.

### 8. Use the app
1. Click **Connect wallet** and choose the **Admin** account.
2. Register the **Seller** wallet as a lister (Admin approval, or the one-click demo shortcut if `DEMO_AUTO_KYC=true`).
3. Click **Switch account**, choose the **Seller** account, and open **Submit listing**.
4. Use **Fill genuine sample**, add 3 or more photos, click **Check listing**, then **Record on-chain** and confirm in MetaMask.
5. Open **Public verifier** and enter the listing ID to see the record, then open the Etherscan links.
6. Switch to the **Buyer** account to browse, report a listing, or pay a safe deposit.

### Troubleshooting
| Problem | Fix |
|---|---|
| Page does not load | Make sure `npm start` is running and nothing else uses port 8000 |
| "Contract not deployed" | Run `npm run deploy:sepolia`, then restart the backend |
| Deploy fails with insufficient funds | Get more Sepolia ETH for the admin wallet |
| MetaMask is on the wrong network | Switch to Sepolia |
| Account switch does nothing | Use the **Switch account** button and connect the account in MetaMask |
| Your own photos are flagged as duplicates | Click **reset demo data** under the form |
| Backend crashes on start | Check `.env` is filled in and `pip install` finished |

## Demo flow
1. **Genuine listing passes:** register as a seller, use "Fill genuine sample", check it, record on-chain.
2. **Public record:** open the Public Verifier and show the Etherscan links.
3. **Fake listing flagged:** use "Fill fake sample" and see the price and scam-wording reasons.
4. **Duplicate photo caught:** submit a resized copy of a photo from another wallet.
5. **Report flow:** report a listing from 3 wallets and watch it flip to "Under review".
6. **Escrow:** lock a deposit, confirm the visit, and let the seller claim it.

## Business model
- **Listing platforms** pay per verification (API)
- **Sellers and agents** pay for the verified badge
- **Buyers** use it free

## Limitations and future work
- Price averages are sample data (replace with live market data)
- Seller KYC is a demo (production: DigiLocker / eKYC)
- One oracle key signs scores (future: multiple oracles)
- pHash misses heavy edits (future: CLIP embeddings, reverse image search)

## License
MIT
