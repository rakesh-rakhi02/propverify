// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/// @title PropertyVerifier
/// @notice Public, tamper-proof registry of AI-verified property listings.
/// Only hashes are stored on-chain (cheap + private). Scores are signed by an
/// off-chain AI oracle, so listers cannot submit fake scores.
contract PropertyVerifier {
    using MessageHashUtils for bytes32;

    enum Status { Verified, UnderReview }

    struct Lister { bool registered; uint32 verifiedCount; uint32 reportsAgainst; }

    struct Listing {
        uint256 id;
        bytes32 listingHash;   // keccak256 of the listing data
        bytes32 imageHash;     // keccak256 of the photos' perceptual hashes
        uint8 score;           // AI trust score at verification time
        address lister;
        uint64 timestamp;
        Status status;
        uint32 reportCount;
    }

    uint8 public constant THRESHOLD = 70;
    uint8 public constant PENALTY_PER_REPORT = 10;
    uint32 public constant REPORTS_FOR_REVIEW = 3;

    address public admin;
    address public oracle;
    uint256 public listingCount;

    mapping(address => Lister) public listers;
    mapping(uint256 => Listing) private listings;
    mapping(bytes32 => bool) public usedImageHash;
    mapping(bytes32 => bool) public usedListingHash;
    mapping(uint256 => mapping(address => bool)) public hasReported;

    event ListerRegistered(address indexed lister);
    event ListingVerified(uint256 indexed id, address indexed lister, bytes32 listingHash, uint8 score);
    event ListingReported(uint256 indexed id, address indexed reporter, uint32 reportCount, uint8 trustScore);

    modifier onlyAdmin() { require(msg.sender == admin, "not admin"); _; }

    constructor(address _oracle) {
        admin = msg.sender;
        oracle = _oracle;
    }

    /// Demo KYC: admin approves a wallet. Production: DigiLocker / eKYC + soulbound token.
    function registerLister(address who) external onlyAdmin {
        listers[who].registered = true;
        emit ListerRegistered(who);
    }

    function recordVerification(
        bytes32 listingHash,
        bytes32 imageHash,
        uint8 score,
        bytes calldata signature
    ) external returns (uint256 id) {
        require(listers[msg.sender].registered, "not registered");
        require(score >= THRESHOLD, "score too low");
        require(!usedListingHash[listingHash], "listing already recorded");
        require(!usedImageHash[imageHash], "image already used");

        bytes32 digest = keccak256(
            abi.encodePacked(listingHash, imageHash, score, msg.sender, block.chainid, address(this))
        ).toEthSignedMessageHash();
        require(ECDSA.recover(digest, signature) == oracle, "bad signature");

        usedListingHash[listingHash] = true;
        usedImageHash[imageHash] = true;

        id = ++listingCount;
        listings[id] = Listing(id, listingHash, imageHash, score, msg.sender, uint64(block.timestamp), Status.Verified, 0);
        listers[msg.sender].verifiedCount++;
        emit ListingVerified(id, msg.sender, listingHash, score);
    }

    function reportListing(uint256 id) external {
        Listing storage l = listings[id];
        require(l.id != 0, "no such listing");
        require(l.lister != msg.sender, "own listing");
        require(!hasReported[id][msg.sender], "already reported");

        hasReported[id][msg.sender] = true;
        l.reportCount++;
        listers[l.lister].reportsAgainst++;
        if (l.reportCount >= REPORTS_FOR_REVIEW) l.status = Status.UnderReview;
        emit ListingReported(id, msg.sender, l.reportCount, trustScore(id));
    }

    function getListing(uint256 id) external view returns (Listing memory) {
        require(listings[id].id != 0, "no such listing");
        return listings[id];
    }

    /// AI score minus 10 per report (floor 0).
    function trustScore(uint256 id) public view returns (uint8) {
        Listing storage l = listings[id];
        uint256 penalty = uint256(l.reportCount) * PENALTY_PER_REPORT;
        return penalty >= l.score ? 0 : uint8(l.score - penalty);
    }

    /// verified listings * 10 - reports received * 5
    function reputation(address who) external view returns (int256) {
        Lister storage l = listers[who];
        return int256(uint256(l.verifiedCount)) * 10 - int256(uint256(l.reportsAgainst)) * 5;
    }
}
