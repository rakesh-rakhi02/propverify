require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const hasValidPrivateKey =
  process.env.PRIVATE_KEY &&
  /^0x[0-9a-fA-F]{64}$/.test(process.env.PRIVATE_KEY.trim());

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      evmVersion: "cancun",
    },
  },
  networks: {
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL || "",
      accounts: hasValidPrivateKey ? [process.env.PRIVATE_KEY.trim()] : [],
    },
  },
  etherscan: { apiKey: process.env.ETHERSCAN_API_KEY || "" },
};
