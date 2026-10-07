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

describe("PropertyVerifier", () => {
  let c, owner, lister, r1, r2, r3, other;
  const h = (s) => ethers.id(s);

  async function record(lh, ih, score = 90, who = lister) {
    return c.connect(who).recordVerification(h(lh), h(ih), score, await sign(owner, c, h(lh), h(ih), score, who));
  }

  beforeEach(async () => {
    [owner, lister, r1, r2, r3, other] = await ethers.getSigners();
    c = await ethers.deployContract("PropertyVerifier", [owner.address]);
    await c.registerLister(lister.address);
  });

  it("records a verified listing with score and lister wallet", async () => {
    await expect(record("L1", "I1")).to.emit(c, "ListingVerified");
    const l = await c.getListing(1);
    expect(l.lister).to.equal(lister.address);
    expect(l.score).to.equal(90);
    expect(await c.reputation(lister.address)).to.equal(10);
  });

  it("rejects unregistered listers, low scores, bad signatures", async () => {
    const sig = await sign(owner, c, h("L"), h("I"), 90, other);
    await expect(c.connect(other).recordVerification(h("L"), h("I"), 90, sig)).to.be.revertedWith("not registered");
    await expect(record("L", "I", 50)).to.be.revertedWith("score too low");
    const forged = await sign(other, c, h("L"), h("I"), 90, lister);
    await expect(c.connect(lister).recordVerification(h("L"), h("I"), 90, forged)).to.be.revertedWith("bad signature");
  });

  it("blocks a lister from inflating the score after signing", async () => {
    const sig = await sign(owner, c, h("L"), h("I"), 75, lister);
    await expect(c.connect(lister).recordVerification(h("L"), h("I"), 99, sig)).to.be.revertedWith("bad signature");
  });

  it("blocks duplicate image hashes", async () => {
    await record("L1", "I1");
    await expect(record("L2", "I1")).to.be.revertedWith("image already used");
  });

  it("allows one report per wallet and lowers trust", async () => {
    await record("L1", "I1");
    await c.connect(r1).reportListing(1);
    await expect(c.connect(r1).reportListing(1)).to.be.revertedWith("already reported");
    expect(await c.trustScore(1)).to.equal(80);
    await expect(c.connect(lister).reportListing(1)).to.be.revertedWith("own listing");
  });

  it("flips to UnderReview after 3 reports and hurts reputation", async () => {
    await record("L1", "I1");
    for (const r of [r1, r2, r3]) await c.connect(r).reportListing(1);
    expect((await c.getListing(1)).status).to.equal(1);
    expect(await c.reputation(lister.address)).to.equal(10 - 15);
  });
});
