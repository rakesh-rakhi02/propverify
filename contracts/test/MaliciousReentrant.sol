// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../ListingEscrow.sol";

contract MaliciousReentrant {
    ListingEscrow public immutable escrow;
    uint256 public targetListingId;
    bool public attackOnClaim;

    constructor(address _escrow) {
        escrow = ListingEscrow(_escrow);
    }

    function setTarget(uint256 listingId, bool isClaim) external {
        targetListingId = listingId;
        attackOnClaim = isClaim;
    }

    function deposit(uint256 listingId) external payable {
        escrow.openDeposit{value: msg.value}(listingId);
    }

    function attackRefund(uint256 listingId) external {
        escrow.refundDeposit(listingId);
    }

    function attackClaim(uint256 listingId) external {
        escrow.claimDeposit(listingId);
    }

    receive() external payable {
        if (targetListingId != 0) {
            uint256 id = targetListingId;
            targetListingId = 0; // prevent infinite loop if reentrancy guard fails
            if (attackOnClaim) {
                escrow.claimDeposit(id);
            } else {
                escrow.refundDeposit(id);
            }
        }
    }
}
