const { expect } = require("chai");
const { ethers } = require("hardhat");

async function sign(oracle, c, lh, ih, score, lister) {
  const { chainId } = await ethers.provider.getNetwork();
  const d = ethers.solidityPackedKeccak256(
    ["bytes32", "bytes32", "uint8", "address", "uint256", "address"],
    [lh, ih, score, lister.address, chainId, await c.getAddress()]
  );
  return oracle.signMessage(ethers.getBytes(d));
}

describe("ListingEscrow", () => {
  let verifier, escrow, owner, lister, buyer, reporter1, reporter2, reporter3, other;
  const h = (s) => ethers.id(s);

  async function recordListing(lh = "L1", ih = "I1", score = 90) {
    const sig = await sign(owner, verifier, h(lh), h(ih), score, lister);
    return verifier.connect(lister).recordVerification(h(lh), h(ih), score, sig);
  }

  beforeEach(async () => {
    [owner, lister, buyer, reporter1, reporter2, reporter3, other] = await ethers.getSigners();

    verifier = await ethers.deployContract("PropertyVerifier", [owner.address]);
    await verifier.registerLister(lister.address);

    escrow = await ethers.deployContract("ListingEscrow", [await verifier.getAddress(), owner.address]);

    // Record verified listing #1
    await recordListing("Listing1", "Image1", 95);
  });

  it("1. Happy path: deposit -> visit confirmed -> seller claims", async () => {
    const depositAmt = ethers.parseEther("0.1");

    // Seller sets deposit amount
    await expect(escrow.connect(lister).setDepositAmount(1, depositAmt))
      .to.emit(escrow, "DepositAmountSet")
      .withArgs(1, depositAmt);

    // Buyer opens deposit
    await expect(escrow.connect(buyer).openDeposit(1, { value: depositAmt }))
      .to.emit(escrow, "DepositOpened")
      .withArgs(1, buyer.address, lister.address, depositAmt);

    // Seller tries to claim before buyer confirms visit -> reverts
    await expect(escrow.connect(lister).claimDeposit(1)).to.be.revertedWith("visit not confirmed");

    // Buyer confirms visit
    await expect(escrow.connect(buyer).confirmVisit(1))
      .to.emit(escrow, "VisitConfirmed")
      .withArgs(1, buyer.address);

    // Seller claims deposit
    const balanceBefore = await ethers.provider.getBalance(lister.address);
    const tx = await escrow.connect(lister).claimDeposit(1);
    const receipt = await tx.wait();
    const gasUsed = receipt.gasUsed * receipt.gasPrice;
    const balanceAfter = await ethers.provider.getBalance(lister.address);

    expect(balanceAfter).to.equal(balanceBefore + depositAmt - gasUsed);

    const dep = await escrow.getDeposit(1);
    expect(dep.status).to.equal(3); // Status.Claimed
    expect(dep.amount).to.equal(0);
  });

  it("2. Refund after timeout: buyer refunds after 7 days", async () => {
    const depositAmt = ethers.parseEther("0.05");
    await escrow.connect(buyer).openDeposit(1, { value: depositAmt });

    // Buyer tries to refund immediately -> reverts
    await expect(escrow.connect(buyer).refundDeposit(1)).to.be.revertedWith("refund timeout not elapsed");

    // Advance time by 7 days + 10 seconds
    await ethers.provider.send("evm_increaseTime", [7 * 24 * 3600 + 10]);
    await ethers.provider.send("evm_mine");

    // Buyer refunds
    const balanceBefore = await ethers.provider.getBalance(buyer.address);
    const tx = await escrow.connect(buyer).refundDeposit(1);
    const receipt = await tx.wait();
    const gasUsed = receipt.gasUsed * receipt.gasPrice;
    const balanceAfter = await ethers.provider.getBalance(buyer.address);

    expect(balanceAfter).to.equal(balanceBefore + depositAmt - gasUsed);

    const dep = await escrow.getDeposit(1);
    expect(dep.status).to.equal(4); // Status.Refunded
  });

  it("3. Unverified listing is rejected", async () => {
    const depositAmt = ethers.parseEther("0.05");

    // Non-existent listing ID 999
    await expect(escrow.connect(buyer).openDeposit(999, { value: depositAmt })).to.be.revertedWith(
      "no such listing"
    );

    // Listing that receives 3 reports flips to UnderReview
    await verifier.connect(reporter1).reportListing(1);
    await verifier.connect(reporter2).reportListing(1);
    await verifier.connect(reporter3).reportListing(1);

    const l = await verifier.getListing(1);
    expect(l.status).to.equal(1); // UnderReview

    // Opening deposit on listing under review is rejected
    await expect(escrow.connect(buyer).openDeposit(1, { value: depositAmt })).to.be.revertedWith(
      "listing under review"
    );
  });

  it("4. Reentrancy attempt is blocked", async () => {
    // Record listing #2 for this test
    await recordListing("Listing2", "Image2", 90);

    const attacker = await ethers.deployContract("MaliciousReentrant", [await escrow.getAddress()]);
    const depositAmt = ethers.parseEther("0.1");

    // Attacker deposits
    await attacker.deposit(2, { value: depositAmt });

    // Advance time past 7 days timeout
    await ethers.provider.send("evm_increaseTime", [7 * 24 * 3600 + 10]);
    await ethers.provider.send("evm_mine");

    // Configure attacker to reenter refundDeposit on receive()
    await attacker.setTarget(2, false);

    // Attacking should revert due to ReentrancyGuard or fail safely
    await expect(attacker.attackRefund(2)).to.be.reverted;
  });

  it("5. Dispute: funds are frozen until admin resolves", async () => {
    const depositAmt = ethers.parseEther("0.08");
    await escrow.connect(buyer).openDeposit(1, { value: depositAmt });

    // Buyer raises dispute
    await expect(escrow.connect(buyer).raiseDispute(1))
      .to.emit(escrow, "DisputeRaised")
      .withArgs(1, buyer.address);

    // Seller cannot claim, buyer cannot refund
    await expect(escrow.connect(lister).claimDeposit(1)).to.be.revertedWith("visit not confirmed");
    await ethers.provider.send("evm_increaseTime", [7 * 24 * 3600 + 10]);
    await ethers.provider.send("evm_mine");
    await expect(escrow.connect(buyer).refundDeposit(1)).to.be.revertedWith("deposit not active or confirmed");

    // Non-admin cannot resolve
    await expect(escrow.connect(other).resolveDispute(1, true)).to.be.revertedWith(
      "only admin can resolve dispute"
    );

    // Admin resolves dispute in favor of buyer (refund)
    const buyerBalBefore = await ethers.provider.getBalance(buyer.address);
    await expect(escrow.connect(owner).resolveDispute(1, false))
      .to.emit(escrow, "DisputeResolved")
      .withArgs(1, buyer.address, depositAmt);

    const buyerBalAfter = await ethers.provider.getBalance(buyer.address);
    expect(buyerBalAfter).to.equal(buyerBalBefore + depositAmt);

    const dep = await escrow.getDeposit(1);
    expect(dep.status).to.equal(6); // Status.Resolved
  });
});
