#include "Block.h"
#include <stdexcept>

namespace goc {
std::string operationName(Operation op) {
    switch (op) {
        case Operation::UserCreate: return "USER_CREATE";
        case Operation::RepoCreate: return "REPO_CREATE";
        case Operation::RuleUpdate: return "RULE_UPDATE";
        case Operation::AccessRequest: return "ACCESS_REQUEST";
        case Operation::AccessGrant: return "ACCESS_GRANT";
        case Operation::AccessRevoke: return "ACCESS_REVOKE";
        case Operation::FileChange: return "FILE_CHANGE";
    }
    throw std::invalid_argument("Unknown operation");
}
Operation operationFromName(const std::string& name) {
    if (name == "USER_CREATE") return Operation::UserCreate;
    if (name == "REPO_CREATE") return Operation::RepoCreate;
    if (name == "RULE_UPDATE") return Operation::RuleUpdate;
    if (name == "ACCESS_REQUEST") return Operation::AccessRequest;
    if (name == "ACCESS_GRANT") return Operation::AccessGrant;
    if (name == "ACCESS_REVOKE") return Operation::AccessRevoke;
    if (name == "FILE_CHANGE") return Operation::FileChange;
    throw std::invalid_argument("Unknown operation: " + name);
}
std::string toHex(const nlohmann::json& value) { return value.dump(); }
nlohmann::json transactionToJson(const Transaction& tx) {
    return {{"operation", operationName(tx.operation)}, {"actor_public_key", tx.actor_public_key},
            {"repository_id", tx.repository_id}, {"payload", tx.payload}, {"signature_hex", tx.signature_hex}};
}
nlohmann::json blockToJson(const Block& b) {
    nlohmann::json txs = nlohmann::json::array();
    for (const auto& tx : b.transactions) txs.push_back(transactionToJson(tx));
    return {{"header", {{"chain_type", b.header.chain_type == ChainType::L1 ? "L1" : "L2"},
                         {"chain_id", b.header.chain_id}, {"height", b.header.height},
                         {"previous_hash", b.header.previous_hash}, {"timestamp", b.header.timestamp},
                         {"nonce", b.header.nonce}, {"target_hex", b.header.target_hex}}},
            {"transactions", txs}, {"producer_public_key", b.producer_public_key},
            {"producer_signature_hex", b.producer_signature_hex}, {"hash_hex", b.hash_hex}};
}
Block blockFromJson(const nlohmann::json& j) {
    Block b;
    const auto& h = j.at("header");
    const auto ct = h.at("chain_type").get<std::string>();
    if (ct != "L1" && ct != "L2") throw std::invalid_argument("Invalid chain_type");
    b.header.chain_type = ct == "L1" ? ChainType::L1 : ChainType::L2;
    b.header.chain_id = h.at("chain_id").get<std::string>();
    b.header.height = h.at("height").get<std::uint64_t>();
    b.header.previous_hash = h.at("previous_hash").get<std::string>();
    b.header.timestamp = h.at("timestamp").get<std::uint64_t>();
    b.header.nonce = h.at("nonce").get<std::string>();
    b.header.target_hex = h.at("target_hex").get<std::string>();
    for (const auto& t : j.at("transactions")) {
        Transaction tx;
        tx.operation = operationFromName(t.at("operation").get<std::string>());
        tx.actor_public_key = t.at("actor_public_key").get<std::string>();
        tx.repository_id = t.at("repository_id").get<std::string>();
        tx.payload = t.at("payload");
        tx.signature_hex = t.at("signature_hex").get<std::string>();
        b.transactions.push_back(std::move(tx));
    }
    b.producer_public_key = j.at("producer_public_key").get<std::string>();
    b.producer_signature_hex = j.at("producer_signature_hex").get<std::string>();
    b.hash_hex = j.at("hash_hex").get<std::string>();
    return b;
}
}
