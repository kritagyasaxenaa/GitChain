#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <nlohmann/json.hpp>

#include "AccessControl.h"
#include "Consensus.h"
#include "CreateBlock.h"
#include "Crypto.h"
#include "PostGres.h"
#include "UserReg.h"

#include <memory>
#include <stdexcept>

namespace py = pybind11;
using nlohmann::json;

namespace {
goc::ChainType parseChainType(const std::string& value) {
    if (value == "L1") return goc::ChainType::L1;
    if (value == "L2") return goc::ChainType::L2;
    throw std::invalid_argument("chain_type must be 'L1' or 'L2'");
}

json keyPairJson(const goc::KeyPair& keys) {
    return {{"public_key_pem", keys.public_key_pem}, {"private_key_pem", keys.private_key_pem}};
}

json identityJson(const goc::LocalIdentity& identity) {
    return {{"username", identity.username}, {"identity_id", identity.identity_id},
            {"keys", keyPairJson(identity.keys)}};
}

json transactionFromInput(const std::string& input) {
    json j = json::parse(input);
    if (!j.is_object()) throw std::invalid_argument("Transaction JSON must be an object");
    return j;
}

class Engine {
public:
    Engine(const std::string& rocks_path, const std::string& chain_id,
           const std::string& chain_type, const std::string& postgres_connection_string)
        : chainId_(chain_id),
          postgres_(postgres_connection_string.empty() ? nullptr : std::make_unique<goc::PostGres>(postgres_connection_string)),
          consensus_(std::make_unique<goc::Consensus>(rocks_path, chain_id, parseChainType(chain_type), postgres_.get())) {}

    py::dict submitBlock(const std::string& block_json) {
        auto block = goc::blockFromJson(json::parse(block_json));
        std::string reason;
        bool accepted = consensus_->receiveBlock(block, &reason);
        py::dict result;
        result["accepted"] = accepted;
        result["reason"] = reason;
        result["tip_hash"] = consensus_->tipHash();
        result["tip_height"] = consensus_->tipHeight();
        result["chain_score"] = consensus_->accumulatedScore().convert_to<std::string>();
        return result;
    }

    py::dict status() const {
        py::dict result;
        result["chain_id"] = chainId_;
        result["tip_hash"] = consensus_->tipHash();
        result["tip_height"] = consensus_->tipHeight();
        result["chain_score"] = consensus_->accumulatedScore().convert_to<std::string>();
        return result;
    }

    std::string tipHash() const { return consensus_->tipHash(); }
    std::uint64_t tipHeight() const { return consensus_->tipHeight(); }
    std::vector<std::string> locator(std::size_t max_entries) const { return consensus_->getLocator(max_entries); }

    std::string getBlockJson(const std::string& hash) const {
        auto block = consensus_->getBlock(hash);
        if (!block) return "null";
        return goc::blockToJson(*block).dump();
    }

    std::string blocksAfter(const std::vector<std::string>& locator_hashes, std::size_t max_blocks) const {
        json result = json::array();
        for (const auto& block : consensus_->blocksAfterCommonAncestor(locator_hashes, max_blocks))
            result.push_back(goc::blockToJson(block));
        return result.dump();
    }

private:
    // Keep PostgreSQL alive for at least as long as Consensus.
    std::string chainId_;
    std::unique_ptr<goc::PostGres> postgres_;
    std::unique_ptr<goc::Consensus> consensus_;
};
} // namespace

PYBIND11_MODULE(goc_core, m) {
    m.doc() = "GitHub-on-Chain C++ core bindings. Prototype APIs; not production security software.";

    m.def("generate_keypair", []() { return keyPairJson(goc::Crypto::generateKeyPair()).dump(); },
          "Generate an ECDSA P-256 keypair; returns JSON containing PEM keys.");
    m.def("create_local_identity", [](const std::string& username) {
        return identityJson(goc::UserReg::createLocalIdentity(username)).dump();
    }, py::arg("username"), "Create a local identity without creating a blockchain block.");
    m.def("identity_id", &goc::UserReg::identityId, py::arg("public_key_pem"));
    m.def("sha256", &goc::Crypto::sha256Hex, py::arg("data"));
    m.def("sign_message", &goc::Crypto::sign, py::arg("private_key_pem"), py::arg("message"));
    m.def("verify_signature", &goc::Crypto::verifySignature,
          py::arg("public_key_pem"), py::arg("message"), py::arg("signature_hex"));

    m.def("sign_transaction", [](const std::string& transaction_json, const std::string& private_key_pem) {
        json j = transactionFromInput(transaction_json);
        goc::Transaction tx;
        tx.operation = goc::operationFromName(j.at("operation").get<std::string>());
        tx.actor_public_key = j.at("actor_public_key").get<std::string>();
        tx.repository_id = j.value("repository_id", "");
        tx.payload = j.value("payload", json::object());
        tx.signature_hex = "";
        return goc::Crypto::signTransaction(tx, private_key_pem);
    }, py::arg("transaction_json"), py::arg("private_key_pem"));

    m.def("score_block", [](const std::string& target_hex, const std::string& hash_hex) {
        return goc::Crypto::blockScore(target_hex, hash_hex).convert_to<std::string>();
    }, py::arg("target_hex"), py::arg("hash_hex"),
       "Return floor(sqrt(target - hash)) as a decimal integer string.");
    m.def("verify_block_pow", [](const std::string& block_json) {
        return goc::Crypto::verifyPow(goc::blockFromJson(json::parse(block_json)));
    }, py::arg("block_json"));
    m.def("build_block", [](const std::string& chain_type, const std::string& chain_id,
                              std::uint64_t height, const std::string& previous_hash,
                              const std::string& target_hex, const std::string& transactions_json,
                              const std::string& producer_public_key) {
        json txs = json::parse(transactions_json);
        if (!txs.is_array()) throw std::invalid_argument("transactions_json must encode a JSON array");
        std::vector<goc::Transaction> transactions;
        for (const auto& item : txs) {
            goc::Transaction tx;
            tx.operation = goc::operationFromName(item.at("operation").get<std::string>());
            tx.actor_public_key = item.at("actor_public_key").get<std::string>();
            tx.repository_id = item.value("repository_id", "");
            tx.payload = item.value("payload", json::object());
            tx.signature_hex = item.value("signature_hex", "");
            transactions.push_back(std::move(tx));
        }
        auto block = goc::CreateBlock::build(parseChainType(chain_type), chain_id, height,
            previous_hash, target_hex, transactions, producer_public_key);
        return goc::blockToJson(block).dump();
    }, py::arg("chain_type"), py::arg("chain_id"), py::arg("height"),
       py::arg("previous_hash"), py::arg("target_hex"), py::arg("transactions_json"),
       py::arg("producer_public_key"));

    m.def("mine_block", [](const std::string& block_json, const std::string& private_key_pem,
                             std::uint64_t max_attempts) {
        auto block = goc::blockFromJson(json::parse(block_json));
        if (!goc::CreateBlock::mine(block, private_key_pem, max_attempts))
            throw std::runtime_error("Mining attempt limit reached without finding a valid nonce");
        return goc::blockToJson(block).dump();
    }, py::arg("block_json"), py::arg("private_key_pem"), py::arg("max_attempts") = 1000000);

    m.def("access_request", [](const std::string& public_key, const std::string& repo_id, const std::string& role) {
        return goc::transactionToJson(goc::AccessControl::request(public_key, repo_id, role)).dump();
    });
    m.def("access_grant", [](const std::string& admin_public_key, const std::string& repo_id,
                               const std::string& subject_public_key, const std::string& role) {
        return goc::transactionToJson(goc::AccessControl::grant(admin_public_key, repo_id, subject_public_key, role)).dump();
    });
    m.def("access_revoke", [](const std::string& admin_public_key, const std::string& repo_id,
                                const std::string& subject_public_key) {
        return goc::transactionToJson(goc::AccessControl::revoke(admin_public_key, repo_id, subject_public_key)).dump();
    });

    py::class_<Engine>(m, "Engine")
        .def(py::init<const std::string&, const std::string&, const std::string&, const std::string&>(),
             py::arg("rocks_path"), py::arg("chain_id"), py::arg("chain_type") = "L1",
             py::arg("postgres_connection_string") = "",
             "Open a chain database. Leave PostgreSQL connection empty to disable projection.")
        .def("submit_block", &Engine::submitBlock, py::arg("block_json"))
        .def("status", &Engine::status)
        .def("tip_hash", &Engine::tipHash)
        .def("tip_height", &Engine::tipHeight)
        .def("locator", &Engine::locator, py::arg("max_entries") = 32)
        .def("get_block_json", &Engine::getBlockJson, py::arg("hash"))
        .def("blocks_after_common_ancestor_json", &Engine::blocksAfter,
             py::arg("locator_hashes"), py::arg("max_blocks") = 512);
}
