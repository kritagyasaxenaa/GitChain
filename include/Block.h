#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

namespace goc {
enum class ChainType { L1, L2 };
enum class Operation { UserCreate, RepoCreate, RuleUpdate, AccessRequest, AccessGrant, AccessRevoke, FileChange };

struct Transaction {
    Operation operation{Operation::FileChange};
    std::string actor_public_key;
    std::string repository_id;
    nlohmann::json payload = nlohmann::json::object();
    std::string signature_hex;
};

struct BlockHeader {
    ChainType chain_type{ChainType::L1};
    std::string chain_id{"L1"};
    std::uint64_t height{0};
    std::string previous_hash; // empty only for genesis
    std::uint64_t timestamp{0};
    std::string nonce{"0"};
    std::string target_hex; // exactly 64 hex digits, interpreted as unsigned 256-bit integer
};

struct Block {
    BlockHeader header;
    std::vector<Transaction> transactions;
    std::string producer_public_key;
    std::string producer_signature_hex;
    std::string hash_hex;
};

std::string toHex(const nlohmann::json& value);
nlohmann::json transactionToJson(const Transaction& tx);
nlohmann::json blockToJson(const Block& block);
Block blockFromJson(const nlohmann::json& value);
std::string operationName(Operation op);
Operation operationFromName(const std::string& name);
}
