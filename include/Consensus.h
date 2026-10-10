#pragma once
#include "Block.h"
#include "Crypto.h"
#include <rocksdb/db.h>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace goc {
class PostGres;
class Consensus {
public:
    Consensus(const std::string& rocks_path, std::string chain_id, ChainType type, PostGres* projection);
    ~Consensus();
    bool receiveBlock(const Block& block, std::string* reason = nullptr);
    std::optional<Block> getBlock(const std::string& hash) const;
    std::vector<std::string> getLocator(std::size_t max_entries = 32) const;
    std::string tipHash() const;
    std::uint64_t tipHeight() const;
    BigInt accumulatedScore() const;
    // Peer transport is intentionally injected by the application; these return the data a peer needs.
    std::vector<Block> blocksAfterCommonAncestor(const std::vector<std::string>& locator) const;
private:
    rocksdb::DB* db_{nullptr};
    std::string chain_id_;
    ChainType type_;
    PostGres* projection_;
    mutable std::mutex mutex_;
    std::string tip_hash_;
    std::uint64_t tip_height_{0};
    BigInt tip_score_{0};
    bool validateBlock(const Block& block, std::string* reason) const;
    bool persistCandidate(const Block& block, const std::string& hash, const std::string& parent_hash, const BigInt& score);
    void loadTip();
    void recomputeCanonicalTip();
    void setError(std::string* reason, const std::string& message) const;
    std::string blockKey(const std::string& hash) const;
    std::string scoreKey(const std::string& hash) const;
    std::optional<Block> readBlock(const std::string& hash) const;
    BigInt readScore(const std::string& hash) const;
};
}
