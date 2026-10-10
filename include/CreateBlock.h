#pragma once
#include "Block.h"
#include <string>
#include <vector>
namespace goc {
class CreateBlock {
public:
    static Block build(ChainType type, const std::string& chain_id, std::uint64_t height,
                       const std::string& previous_hash, const std::string& target_hex,
                       const std::vector<Transaction>& transactions,
                       const std::string& producer_public_key);
    static bool mine(Block& block, const std::string& producer_private_key_pem, std::uint64_t max_attempts = 10'000'000);
    // Network layer calls this after a block is mined. No transport implementation is assumed.
    static std::string encode(const Block& block);
};
}
