const { ethers } = require("ethers");
require("dotenv").config();

async function check() {
  const rpc = process.env.SEPOLIA_RPC_URL;
  const key = process.env.PRIVATE_KEY;
  if (!rpc || !key) {
    console.log("Missing SEPOLIA_RPC_URL or PRIVATE_KEY in .env");
    return;
  }
  const provider = new ethers.JsonRpcProvider(rpc);
  const wallet = new ethers.Wallet(key, provider);
  const balance = await provider.getBalance(wallet.address);
  const eth = ethers.formatEther(balance);
  console.log("==========================================");
  console.log("Deployer Address:", wallet.address);
  console.log("Sepolia Balance :", eth, "ETH");
  console.log("==========================================");
  if (balance > ethers.parseEther("0.015")) {
    console.log("✅ Balance sufficient! You can run 'npm run deploy:sepolia' now.");
  } else {
    console.log("⏳ Insufficient funds for contract deployment (needs ~0.02 Sepolia ETH).");
    console.log("Please send Sepolia test ETH to:", wallet.address);
  }
}

check().catch(console.error);
