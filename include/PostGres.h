#pragma once
#include "Block.h"
#include <memory>
#include <string>
#include <pqxx/pqxx>

namespace goc {
class PostGres {
public:
    explicit PostGres(const std::string& connection_string);
    void applyCanonicalBlock(const Block& block);
    void rollbackBlock(const Block& block);
    nlohmann::json getRepository(const std::string& repository_id);
    void executeReadOnly(const std::string& sql); // deliberately rejects arbitrary writes
private:
    pqxx::connection connection_;
    void applyTransaction(pqxx::work& tx, const Transaction& item);
};
}
