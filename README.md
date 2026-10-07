# PropVerify · AI Property Listing Verifier Detecting Fake Listings
> **INNOBLOCK 2.0 · PROBLEM STATEMENT PS 50 (DOMAIN 5: REAL ESTATE & LAND REGISTRY)**  
> *AI-powered multi-vector fraud scoring for real estate listings with cryptographically signed, immutable on-chain records, community reporting, lister reputation, and earnest money escrow on Ethereum Sepolia.*

---

## 🏆 Innoblock 2.0 (PS 50) Alignment Matrix

| Category | Requirement (from PS 50 Specification) | Implementation in PropVerify | Status |
| :--- | :--- | :--- | :---: |
| **Must-Have 01** | *Lister submits a listing with photos, price, address and description* | Responsive submission form with multi-photo upload, price, address, description, locality, BHK, sqft, and interactive Leaflet map GPS pin picker. | **100% Complete** |
| **Must-Have 02** | *AI model flags signals like price far below area average* | Multi-vector scoring engine (`scoring.py`) flags price anomalies against locality baselines (e.g. -76% below average), advance-fee keywords, and spec inconsistencies. | **100% Complete** |
| **Must-Have 03** | *Duplicate image check against previously submitted listings* | 64-bit DCT perceptual hashing (`imagehash` pHash) detects stolen photos across past listings (Hamming distance $\le 10$) with visual side-by-side comparison. | **100% Complete** |
| **Must-Have 04** | *Verified listings recorded on-chain with score and lister wallet* | Cryptographic ECDSA oracle signature authorizes `PropertyVerifier.sol` on Sepolia to record listing hash, image pHash, trust score, and verified lister wallet. | **100% Complete** |
| **Good-To-Have 01** | *Users can report a listing, lowering its trust score* | `reportListing(id)` smart contract & backend endpoint: each report deducts 10 trust points, penalizes seller reputation, and flips listing to "UNDER REVIEW" at 3 reports. | **100% Complete** |
| **Good-To-Have 02** | *Lister reputation built from past verified listings* | On-chain formula `(verifiedCount * 10) - (reportsAgainst * 5)` unlocks tiered reputation badges (**Bronze** `<10`, **Silver** `10–29`, **Gold** `≥30`). | **100% Complete** |
| **Demo Must Show 01** | *A genuine sample listing passing verification* | **1-Click Demo 01**: Pre-fills genuine 2 BHK Madhapur (Rs 36k, real photos) $\rightarrow$ Score 95+ (Verified) $\rightarrow$ Records on Sepolia. | **100% Complete** |
| **Demo Must Show 02** | *A fake listing flagged with reasons shown* | **1-Click Demo 02**: Pre-fills fake Gachibowli 2 BHK (Rs 9k) $\rightarrow$ Flags 76% price anomaly, "advance payment", "owner abroad" $\rightarrow$ Score <40 (Flagged). | **100% Complete** |
| **Demo Must Show 03** | *On-chain record of a verified listing viewed publicly* | **1-Click Demo 03**: Public Verifier queries Sepolia directly $\rightarrow$ displays trust score, lister reputation, Etherscan link, and mobile verification QR code. | **100% Complete** |

---

## 1. System Architecture

```
                                  +-------------------------------------------------------------+
                                  |                     CLIENT BROWSER                          |
                                  |   (Vanilla JS + Ethers.js v6 + Leaflet OSM + QRCode.js)     |
                                  +------------------------------+------------------------------+
                                                                 |
                                       HTTP / JSON-RPC           |             Web3 Provider
                                       (Port 8000)               |             (MetaMask)
                                                                 v                   v
                     +-------------------------------------------+---+               |
                     |                 BACKEND ENGINE                |               |
                     |              (FastAPI + SQLite)               |               |
                     +-----------------------------------------------+               |
                     |  - Multi-Vector AI Fraud Scoring (scoring.py) |               |
                     |    * Price per sq ft vs. locality benchmarks  |               |
                     |    * Scam text NLP keyword detector           |               |
                     |    * Spec & coordinate consistency check      |               |
                     |    * Lister history & reputation weighting    |               |
                     |  - Perceptual Image Hashing (pHash)           |               |
                     |    * 64-bit DCT perceptual hash               |               |
                     |    * Hamming distance duplicate detection     |               |
                     |  - ECDSA Oracle Key Signing                   |               |
                     |    * Signs (listingHash, imageHash, score)    |               |
                     +-----------------------------------------------+               |
                                                                                     |
                                                                                     v
                     +---------------------------------------------------------------+----------+
                     |                 ETHEREUM SEPOLIA TESTNET (EVM)                           |
                     +--------------------------------------------------------------------------+
                     |  PropertyVerifier.sol                                                    |
                     |    * Admin registerLister() KYC whitelist                                |
                     |    * ECDSA signature verification (ecrecover oracle validation)          |
                     |    * Duplicate perceptual image hash rejection guard                     |
                     |    * Lister reputation accumulator (+10 per verify, -5 per report)       |
                     |    * Community reporting -> Flips to "UNDER REVIEW" at 3+ reports       |
                     |                                                                          |
                     |  ListingEscrow.sol                                                       |
                     |    * openDeposit() earnest money lock (capped at 1 ETH)                  |
                     |    * Rejects deposits for unverified or under-review listings            |
                     |    * confirmVisit() physical inspection release unlock                   |
                     |    * 7-day automated timeout refund for buyers                           |
                     |    * Mutual dispute freeze & admin arbitration                           |
                     |    * OpenZeppelin ReentrancyGuard & Checks-Effects-Interactions          |
                     +--------------------------------------------------------------------------+
```

---

## 2. Role Explanations

| Role | Access & Wallet | Primary Responsibilities & Capabilities |
| :--- | :--- | :--- |
| **Buyer** | **No wallet required** to browse; **MetaMask** optional for escrow & reporting | <ul><li>Browse all verified properties on a responsive card grid filtered by locality, rent/sale, BHK, and price ceiling.</li><li>Inspect listing detail view: full photo gallery, AI explanation breakdown, and seller reputation badge.</li><li>**Interactive Leaflet Map**: View exact verified pin coordinates for on-chain listings (or ~1 km neighborhood privacy circles for unverified submissions).</li><li>**Safe Deposit Escrow**: Lock earnest deposits into `ListingEscrow.sol`, confirm in-person property visits to unlock payment, claim 100% refund after 7 days if visit is unconfirmed, or raise disputes.</li><li>**Public Proof & QR Code**: Scan or download client-side generated QR codes (`/#verify=<id>`) to audit contract state on Etherscan.</li><li>Submit on-chain fraud reports directly via MetaMask.</li></ul> |
| **Seller** | **KYC Registered Wallet** (`listers(address).registered == true`) | <ul><li>Access dedicated **Seller Dashboard** displaying on-chain reputation score, verification count, and badge tier (**Bronze** `<10`, **Silver** `10–29`, **Gold** `≥30`).</li><li>**Add Listing Form**: Pick precise property coordinates with Leaflet + OpenStreetMap pin picker (incorporated directly into the cryptographic listing hash).</li><li>**AI Fraud Verification**: Submit property data and multi-photo uploads to receive real-time trust scoring and duplicate image audits.</li><li>**Record On-Chain**: Broadcast oracle-signed verification transactions to `PropertyVerifier.sol` on Sepolia.</li><li>**Escrow Panel**: Set custom deposit requirements (`setDepositAmount`, capped at 1.0 ETH), monitor active buyer deposits, and claim unlocked funds after visits are confirmed.</li></ul> |
| **Admin** | **Contract Owner Wallet** (`admin() == msg.sender`) | <ul><li>**Seller KYC Applications**: Review pending broker/owner requests (`seller_requests`) and approve them directly on-chain by calling `registerLister(wallet)` via MetaMask.</li><li>**Needs Review Queue**: Audit borderline submissions (scores 40–69) flagged with specific risk severity tags.</li><li>**Reported Listings Audit**: Read `ListingReported` events and monitor listings that reached the 3-report threshold to enter "UNDER REVIEW".</li><li>**Escrow Arbitration**: Inspect frozen deposits under dispute and arbitrate funds by executing `resolveDispute(listingId, toSeller)` to award the seller or refund the buyer.</li><li>Optional demo shortcut: `DEMO_AUTO_KYC=true` for instant 1-click KYC approvals during presentations.</li></ul> |

---

## 3. Setup & Installation

### Prerequisites
- [Node.js](https://nodejs.org/) (v18 or higher)
- [Python](https://www.python.org/) (v3.10 or higher)
- [MetaMask](https://metamask.io/) browser extension connected to **Ethereum Sepolia Testnet**

### Step-by-Step Installation

1. **Clone & Install Node Dependencies**:
   ```bash
   npm install
   ```

2. **Configure Environment Variables**:
   Create a `.env` file from the provided template:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your Sepolia credentials:
   ```env
   SEPOLIA_RPC_URL="https://eth-sepolia.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"
   PRIVATE_KEY="YOUR_SEPOLIA_DEPLOYER_PRIVATE_KEY"
   DEMO_AUTO_KYC=true
   ```

3. **Compile Contracts & Run Hardhat Tests**:
   ```bash
   npx hardhat test
   ```
   *Expected output: All 11 unit tests passing across `PropertyVerifier` and `ListingEscrow`.*

4. **Run Backend Unit Tests**:
   ```bash
   python -m unittest backend/test_scoring.py
   ```
   *Expected output: All 6 scoring, anomaly, and location consistency tests passing.*

5. **Deploy Contracts to Sepolia** *(optional if using pre-deployed configuration)*:
   ```bash
   npm run deploy:sepolia
   ```
   The deployment script automatically compiles, deploys `PropertyVerifier` and `ListingEscrow`, and saves contract addresses to `backend/deployment.json`.
   
   To verify source code on Etherscan:
   ```bash
   npx hardhat verify --network sepolia <PropertyVerifier_address> <deployer_address>
   npx hardhat verify --network sepolia <ListingEscrow_address> <PropertyVerifier_address> <admin_address>
   ```

6. **Install Python Backend Dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

7. **Launch Web Server**:
   ```bash
   npm start
   ```
   Open your browser to `http://localhost:8000`.

---

## 4. End-to-End Demo Scripts

### Scenario 1: Genuine Listing Verification Flow
1. Open `http://localhost:8000` and click **Enter as Seller** (or use the Demo Seller Wallet).
2. Click **Add Listing** in the navigation.
3. Click the **"Fill genuine sample"** button:
   - Form auto-fills: 2 BHK in *Madhapur*, Rs 36,000/mo, 1,200 sq ft, legitimate description, and sample interior photos.
   - The Leaflet map sets coordinates inside Madhapur.
4. Click **Check listing**:
   - The AI engine inspects price per sq ft (Rs 30/sq ft, within the Rs 25–40 benchmark).
   - Scam text check passes (0 advance-fee triggers).
   - Location consistency check passes (pin is 0.00 km from Madhapur center).
   - Generates Trust Score **92/100 (VERIFIED)** with a cryptographic ECDSA signature from the AI oracle.
5. Click **Record on-chain**:
   - MetaMask prompts to confirm `recordVerification(...)` on `PropertyVerifier.sol`.
   - Once mined, the listing receives on-chain listing ID (e.g., `#1`).
6. Click **Open public record**:
   - Public Verifier confirms status **VERIFIED**, shows the lister badge, Etherscan link, and a live client-side QR code.

### Scenario 2: Fake Listing & Price Anomaly Detection Flow
1. Go to **Add Listing** and click **"Fill fake sample"**:
   - Form fills: 2 BHK in *Gachibowli*, Rs 9,000/mo (market norm: Rs 30,000–50,000/mo), with scam wording: *"Owner abroad. Pay advance Rs 5000 to book. WhatsApp only."*
2. Click **Check listing**:
   - AI engine triggers high-severity penalties:
     - Severe price undercutting detected (Rs 7.5/sq ft vs expected Rs 28–45/sq ft).
     - Scam triggers matched: `"owner abroad"`, `"pay advance"`, `"whatsapp only"`.
   - Score drops below 40 $\rightarrow$ **Verdict: FRAUD (Score ~20/100)**.
3. The **"Record on-chain"** button is completely disabled; fraudulent listings cannot receive an oracle signature or be anchored to the blockchain.

### Scenario 3: Duplicate Photo Detection Flow (pHash)
1. In **Add Listing**, upload the same property photos used in Scenario 1, but enter different property details or a lower price in *Kondapur*.
2. Click **Check listing**:
   - Perceptual Hash (pHash) engine computes the 64-bit DCT hash of each photo and computes Hamming distances against existing database hashes.
   - Hamming distance $\le 10$ is detected.
   - Screen displays the visual side-by-side duplicate comparison banner: *"Photo matches listing #1 (Hamming distance 0)"*.
   - A 30-point duplicate penalty is deducted. Even if signed, `PropertyVerifier.sol` checks `registeredImages[imageHash]` on-chain and reverts duplicate minting attempts.

### Scenario 4: Community Fraud Report Flow
1. In the **Browse Verified Listings** or **Public Verifier** view, open an on-chain verified listing.
2. Click **Report this listing** (with a connected MetaMask buyer/renter wallet).
3. MetaMask broadcasts `reportListing(listingId)`.
4. Upon transaction confirmation:
   - The smart contract increments `reportCount`.
   - Dynamic trust score decreases: `trustScore = max(0, originalScore - (reports * 15))`.
   - Lister's on-chain reputation score is penalized (`-5` points per report).
5. When `reportCount >= 3`, the contract flips status to **1 (UNDER REVIEW)**:
   - The Public Verifier stamp changes from green **VERIFIED** to yellow **UNDER REVIEW**.
   - Any attempt to open safe deposits in `ListingEscrow.sol` is automatically blocked.

### Scenario 5: Safe Deposit Escrow & Dispute Resolution Flow
1. **Open Deposit**:
   - As a Buyer, open a verified property detail page and locate the **"Safe Deposit Escrow"** card.
   - Enter `0.02` ETH and click **🔒 Pay Safe Deposit**.
   - MetaMask calls `ListingEscrow.openDeposit(listingId)` with the deposit value.
   - The escrow status updates to **Deposit Locked**.
2. **Happy Path (Confirm Visit & Claim)**:
   - After inspecting the home in person, the buyer clicks **✓ Confirm Visit**.
   - MetaMask calls `confirmVisit(listingId)`. Status flips to **Visit Confirmed**.
   - The seller visits their **Escrow Panel** and clicks **💰 Claim Deposit**.
   - `claimDeposit(listingId)` transfers the testnet ETH to the seller's wallet.
3. **Timeout Refund Branch**:
   - If 7 days elapse without visit confirmation, the buyer's **Claim Refund** button activates.
   - Calling `refundDeposit(listingId)` returns 100% of earnest funds back to the buyer's wallet.
4. **Dispute & Admin Arbitration Branch**:
   - If either buyer or seller suspects fraud or misrepresentation, they click **Raise Dispute**.
   - Escrow status freezes on-chain as **⚠️ Disputed & Frozen**.
   - The contract administrator switches to their Admin wallet, visits the **Escrow Disputes** tab, and arbitrates the case:
     - Click **Award Seller** $\rightarrow$ releases funds to seller.
     - Click **Refund Buyer** $\rightarrow$ returns funds to buyer.

---

## 5. Business Model

PropVerify operates a sustainable, three-sided economic model aligned with real-world real estate market dynamics:

```
+---------------------------------------------------------------------------------------+
|                                    BUSINESS MODEL                                     |
+------------------------------+---------------------------+----------------------------+
| 1. Platforms (B2B SaaS)      | 2. Sellers & Agents       | 3. Buyers & Renters        |
| Pay per Verification         | Pay for Trust Badges      | 100% Free Access           |
+------------------------------+---------------------------+----------------------------+
| • Major portals (99acres,    | • Independent brokers and | • End-users browse,        |
|   MagicBricks, Housing.com,    agencies pay a monthly or   filter, and inspect proof  |
|   Zillow) pay micro-fees       annual fee for priority     certificates without fees  |
|   per verified submission      KYC verification and        or platform barriers.      |
|   ($0.20 - $1.00 / listing).   on-chain badge minting.                                |
| • Eliminates duplicate spam, | • Verified badge tier     • Safe deposit escrow locks  |
|   reduces moderation costs,    boosts algorithmic          earnest money trustlessly   |
|   and prevents scam churn.     ranking & user inquiries.   without middleman cuts.    |
+------------------------------+---------------------------+----------------------------+
```

1. **Platforms Pay Per Verification (B2B SaaS)**:
   - Real estate classified platforms spend millions annually on manual call-center verification teams.
   - PropVerify offers an automated API and oracle gateway charging **$0.20 to $1.00 per listing verification**.
   - Platforms save >80% on manual moderation while gaining cryptographic guarantees they can market to users.

2. **Sellers Pay for the Verified Badge (Subscription / Tiered Minting)**:
   - Serious brokers, landlords, and agencies pay a subscription or micro-minting fee to maintain registered lister status.
   - Achieving **Silver** and **Gold** badges provides prominent placement, verified trust tags, and higher lead conversion rates.

3. **Buyers & Renters Access for Free**:
   - Complete access to browse verified properties, inspect Leaflet maps, audit on-chain Etherscan proofs, and scan QR codes is entirely free.
   - Builds organic network effects, drawing high-intent tenants and buyers to verified-only marketplaces.

---

## 6. Limitations and Future Work

While PropVerify delivers a complete end-to-end prototype, real-world commercialization will expand upon the following architectural foundations:

1. **Sample Price Benchmark Data**:
   - *Current limitation*: Locality median price baselines are stored in `backend/prices.json` covering 6 major Hyderabad technology corridors.
   - *Future work*: Integrate live automated feeds from municipal stamp duty registration registries, government property valuation databases, and decentralized real estate price oracles (e.g., Chainlink external adapters querying MLS/PropTech APIs).

2. **Demo KYC & Lister Onboarding**:
   - *Current limitation*: Seller verification relies on admin MetaMask approvals (`registerLister`) and an optional demo shortcut (`DEMO_AUTO_KYC=true`).
   - *Future work*: Implement Zero-Knowledge Identity Proofs (ZK-KYC via Polygon ID, WorldID, or Aadhaar zk-SNARKs) allowing brokers and property owners to verify national identity and land title deeds without exposing private identifiable credentials on-chain.

3. **Single AI Oracle Key**:
   - *Current limitation*: A single backend private key acts as the trusted ECDSA signer for AI scores (`PropertyVerifier.sol` validates `ecrecover`).
   - *Future work*: Transition to a Multi-Party Computation (MPC) threshold signature scheme or a decentralized oracle network (DON) using Chainlink Functions where multiple independent validator nodes must reach consensus on fraud metrics before an on-chain score signature is issued.

4. **Perceptual Hashing (pHash) Edge Cases**:
   - *Current limitation*: Perceptual hashing (64-bit DCT with Hamming distance threshold $\le 10$) reliably detects exact duplicates, color shifts, downscaling, and compression artifacts, but can miss heavy rotational crops, extreme perspective skews, or deliberate occlusion borders.
   - *Future work*: Augment pHash with multi-modal neural image embeddings (such as CLIP or Vision Transformers) paired with a vector similarity database (Milvus / Pinecone / Qdrant) to identify semantic visual duplication and reverse-image matches across millions of web listings.

---

## 7. Test Suite Summary

To execute all automated test suites:

```bash
# 1. Smart Contract Tests (11 tests)
npx hardhat test

# 2. Python Backend Scoring Tests (6 tests)
python -m unittest backend/test_scoring.py
```

### Coverage Details:
- `test/PropertyVerifier.test.js`:
  - `[PASS]` Deploys and registers lister.
  - `[PASS]` Verifies listing with valid oracle signature and records hashes.
  - `[PASS]` Rejects verification with invalid oracle signature.
  - `[PASS]` Rejects verification for unregistered lister.
  - `[PASS]` Prevents duplicate image registration via perceptual hash guard.
  - `[PASS]` Increments report count and flips status to Under Review at 3 reports.
  - `[PASS]` Correctly computes reputation and badges (Bronze, Silver, Gold).
- `test/ListingEscrow.test.js`:
  - `[PASS]` Happy path: Deposit opened -> Visit confirmed -> Seller claims funds.
  - `[PASS]` Timeout refund: Buyer blocked before 7 days, successfully refunds after timeout.
  - `[PASS]` Unverified or under-review listings rejected from opening deposits.
  - `[PASS]` Reentrancy attack attempt stopped by OpenZeppelin ReentrancyGuard.
  - `[PASS]` Dispute raised freezes funds; Admin resolves and releases to seller or buyer.
- `backend/test_scoring.py`:
  - `[PASS]` `test_genuine_listing_scores_high` (score $\ge 70$, verdict Verified).
  - `[PASS]` `test_fake_listing_price_too_low` (severe penalty for underpricing).
  - `[PASS]` `test_fake_listing_scam_words` (penalties for advance fee triggers).
  - `[PASS]` `test_duplicate_image_penalty` (pHash duplicate detection).
  - `[PASS]` `test_location_consistency_within_range` (pin near locality center passes).
  - `[PASS]` `test_location_consistency_out_of_range` (pin $>5$ km from locality center penalized).

---

## License
MIT License. Built for Innoblock 2.0 Hackathon.
#   p r o p v e r i f y  
 