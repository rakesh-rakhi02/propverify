// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "./PropertyVerifier.sol";

/// @title ListingEscrow
/// @notice Safe deposit escrow for verified properties on PropertyVerifier.
/// Allows buyers to commit earnest money / security deposits with 7-day refund guarantee,
/// visit confirmation unlocks, and mutual dispute freezing resolved by the admin.
contract ListingEscrow is ReentrancyGuard {
    enum Status { None, Active, VisitConfirmed, Claimed, Refunded, Disputed, Resolved }

    struct Deposit {
        uint256 listingId;
        address buyer;
        address seller;
        uint256 amount;
        uint64 createdAt;
        Status status;
    }

    uint256 public constant MAX_DEPOSIT = 1 ether;
    uint256 public constant TIMEOUT = 7 days;

    PropertyVerifier public immutable verifier;
    address public immutable admin;

    mapping(uint256 => uint256) public sellerDepositAmount;
    mapping(uint256 => Deposit) public deposits;

    event DepositAmountSet(uint256 indexed listingId, uint256 amount);
    event DepositOpened(uint256 indexed listingId, address indexed buyer, address indexed seller, uint256 amount);
    event VisitConfirmed(uint256 indexed listingId, address indexed buyer);
    event DepositClaimed(uint256 indexed listingId, address indexed seller, uint256 amount);
    event DepositRefunded(uint256 indexed listingId, address indexed buyer, uint256 amount);
    event DisputeRaised(uint256 indexed listingId, address indexed raisedBy);
    event DisputeResolved(uint256 indexed listingId, address indexed recipient, uint256 amount);

    constructor(address _verifier, address _admin) {
        require(_verifier != address(0), "invalid verifier address");
        require(_admin != address(0), "invalid admin address");
        verifier = PropertyVerifier(_verifier);
        admin = _admin;
    }

    /// @notice Allows the seller to configure the required deposit amount (capped at MAX_DEPOSIT).
    function setDepositAmount(uint256 listingId, uint256 amount) external {
        PropertyVerifier.Listing memory l = verifier.getListing(listingId);
        require(msg.sender == l.lister, "only seller can set deposit");
        require(amount > 0, "amount must be > 0");
        require(amount <= MAX_DEPOSIT, "amount exceeds max deposit");

        sellerDepositAmount[listingId] = amount;
        emit DepositAmountSet(listingId, amount);
    }

    /// @notice A buyer opens an escrow deposit for a listing verified on PropertyVerifier and not under review.
    function openDeposit(uint256 listingId) external payable nonReentrant {
        PropertyVerifier.Listing memory l = verifier.getListing(listingId);
        require(l.id != 0, "listing not found");
        require(l.status == PropertyVerifier.Status.Verified, "listing under review");
        require(verifier.trustScore(listingId) >= verifier.THRESHOLD(), "score too low");
        require(msg.sender != l.lister, "seller cannot deposit on own listing");

        uint256 reqAmt = sellerDepositAmount[listingId];
        if (reqAmt > 0) {
            require(msg.value == reqAmt, "incorrect deposit amount");
        } else {
            require(msg.value > 0 && msg.value <= MAX_DEPOSIT, "deposit exceeds max or zero");
        }

        Deposit storage d = deposits[listingId];
        require(
            d.status == Status.None ||
            d.status == Status.Claimed ||
            d.status == Status.Refunded ||
            d.status == Status.Resolved,
            "deposit currently active"
        );

        deposits[listingId] = Deposit({
            listingId: listingId,
            buyer: msg.sender,
            seller: l.lister,
            amount: msg.value,
            createdAt: uint64(block.timestamp),
            status: Status.Active
        });

        emit DepositOpened(listingId, msg.sender, l.lister, msg.value);
    }

    /// @notice Buyer confirms they have inspected the property in person. Unlocks funds for seller to claim.
    function confirmVisit(uint256 listingId) external {
        Deposit storage d = deposits[listingId];
        require(d.status == Status.Active, "deposit not active");
        require(msg.sender == d.buyer, "only buyer can confirm visit");

        d.status = Status.VisitConfirmed;
        emit VisitConfirmed(listingId, msg.sender);
    }

    /// @notice Seller claims the deposit once visit is confirmed by the buyer.
    function claimDeposit(uint256 listingId) external nonReentrant {
        Deposit storage d = deposits[listingId];
        require(d.status == Status.VisitConfirmed, "visit not confirmed");
        require(msg.sender == d.seller, "only seller can claim");

        uint256 amt = d.amount;
        d.status = Status.Claimed;
        d.amount = 0;

        (bool sent, ) = d.seller.call{value: amt}("");
        require(sent, "transfer failed");

        emit DepositClaimed(listingId, d.seller, amt);
    }

    /// @notice If 7 days pass without visit confirmation, buyer can refund themselves.
    function refundDeposit(uint256 listingId) external nonReentrant {
        Deposit storage d = deposits[listingId];
        require(d.status == Status.Active, "deposit not active or confirmed");
        require(msg.sender == d.buyer, "only buyer can refund");
        require(block.timestamp >= d.createdAt + TIMEOUT, "refund timeout not elapsed");

        uint256 amt = d.amount;
        d.status = Status.Refunded;
        d.amount = 0;

        (bool sent, ) = d.buyer.call{value: amt}("");
        require(sent, "transfer failed");

        emit DepositRefunded(listingId, d.buyer, amt);
    }

    /// @notice Either buyer or seller can freeze funds by raising a dispute.
    function raiseDispute(uint256 listingId) external {
        Deposit storage d = deposits[listingId];
        require(d.status == Status.Active || d.status == Status.VisitConfirmed, "cannot dispute");
        require(msg.sender == d.buyer || msg.sender == d.seller, "not party to deposit");

        d.status = Status.Disputed;
        emit DisputeRaised(listingId, msg.sender);
    }

    /// @notice Admin arbitrates frozen funds, releasing to seller or refunding buyer.
    function resolveDispute(uint256 listingId, bool toSeller) external nonReentrant {
        require(msg.sender == admin, "only admin can resolve dispute");
        Deposit storage d = deposits[listingId];
        require(d.status == Status.Disputed, "deposit not disputed");

        uint256 amt = d.amount;
        d.status = Status.Resolved;
        d.amount = 0;

        address recipient = toSeller ? d.seller : d.buyer;
        (bool sent, ) = recipient.call{value: amt}("");
        require(sent, "transfer failed");

        emit DisputeResolved(listingId, recipient, amt);
    }

    function getDeposit(uint256 listingId) external view returns (Deposit memory) {
        return deposits[listingId];
    }
}
