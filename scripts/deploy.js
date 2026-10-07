const hre = require("hardhat");
const fs = require("fs");

async function main() {
  const signers = await hre.ethers.getSigners();
  if (!signers || signers.length === 0) {
    console.error("\n❌ ERROR: No deployer account found!");
    console.error("Please add your Account 1 private key to the .env file:");
    console.error("PRIVATE_KEY=0x<your_64_character_hex_private_key>\n");
    process.exit(1);
  }
  const [deployer] = signers;
  console.log("Deploying contracts with account:", deployer.address);
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Account balance:", hre.ethers.formatEther(balance), "Sepolia ETH");
  if (balance === 0n) {
    console.warn("\n⚠️ WARNING: Account balance is 0 ETH. Contract deployment requires Sepolia testnet ETH for gas fees.");
    console.warn("Please fund this address using a Sepolia faucet before deploying.\n");
  }

  // 1. Deploy PropertyVerifier (deployer = admin + oracle)
  const c = await hre.ethers.deployContract("PropertyVerifier", [deployer.address]);
  await c.waitForDeployment();
  const address = await c.getAddress();

  // 2. Deploy ListingEscrow (linked to PropertyVerifier address and admin)
  const escrow = await hre.ethers.deployContract("ListingEscrow", [address, deployer.address]);
  await escrow.waitForDeployment();
  const escrowAddress = await escrow.getAddress();

  const { chainId } = await hre.ethers.provider.getNetwork();
  const deploymentData = {
    address,
    escrow: escrowAddress,
    chainId: Number(chainId),
    oracle: deployer.address,
    admin: deployer.address
  };

  fs.writeFileSync("deployment.json", JSON.stringify(deploymentData, null, 2));

  console.log("PropertyVerifier deployed to:", address);
  console.log("ListingEscrow deployed to:   ", escrowAddress);
  console.log("\nVerify commands for Etherscan:");
  console.log(`npx hardhat verify --network sepolia ${address} ${deployer.address}`);
  console.log(`npx hardhat verify --network sepolia ${escrowAddress} ${address} ${deployer.address}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
