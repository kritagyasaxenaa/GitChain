#include "PostGres.h"
#include <stdexcept>
namespace goc {
PostGres::PostGres(const std::string& cs):connection_(cs) {
    pqxx::work tx(connection_);
    tx.exec(R"SQL(
      CREATE TABLE IF NOT EXISTS goc_projection_meta (chain_id TEXT PRIMARY KEY, height BIGINT NOT NULL DEFAULT -1, tip_hash TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS goc_users (identity_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, public_key TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS goc_repositories (repository_id TEXT PRIMARY KEY, owner_key TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb);
      CREATE TABLE IF NOT EXISTS goc_access (repository_id TEXT NOT NULL, subject_key TEXT NOT NULL, role TEXT NOT NULL, PRIMARY KEY(repository_id,subject_key));
      CREATE TABLE IF NOT EXISTS goc_events (chain_id TEXT NOT NULL, height BIGINT NOT NULL, block_hash TEXT NOT NULL, operation TEXT NOT NULL, payload JSONB NOT NULL, PRIMARY KEY(chain_id,height,operation,payload));
    )SQL"); tx.commit();
}
void PostGres::applyTransaction(pqxx::work& tx,const Transaction& item) {
    switch(item.operation) {
    case Operation::UserCreate: {
        const auto id=item.payload.at("identity_id").get<std::string>(); const auto username=item.payload.at("username").get<std::string>();
        tx.exec_params("INSERT INTO goc_users(identity_id,username,public_key) VALUES($1,$2,$3) ON CONFLICT(identity_id) DO NOTHING",id,username,item.actor_public_key); break;
    }
    case Operation::RepoCreate: {
        const auto id=item.payload.at("repository_id").get<std::string>();
        tx.exec_params("INSERT INTO goc_repositories(repository_id,owner_key,metadata) VALUES($1,$2,$3::jsonb) ON CONFLICT(repository_id) DO NOTHING",id,item.actor_public_key,item.payload.dump()); break;
    }
    case Operation::AccessGrant: {
        tx.exec_params("INSERT INTO goc_access(repository_id,subject_key,role) VALUES($1,$2,$3) ON CONFLICT(repository_id,subject_key) DO UPDATE SET role=EXCLUDED.role",item.repository_id,item.payload.at("subject_public_key").get<std::string>(),item.payload.at("role").get<std::string>()); break;
    }
    case Operation::AccessRevoke:
        tx.exec_params("DELETE FROM goc_access WHERE repository_id=$1 AND subject_key=$2",item.repository_id,item.payload.at("subject_public_key").get<std::string>()); break;
    case Operation::RuleUpdate:
        tx.exec_params("UPDATE goc_repositories SET metadata=metadata || $2::jsonb WHERE repository_id=$1",item.repository_id,item.payload.dump()); break;
    case Operation::AccessRequest:
    case Operation::FileChange:
        // File content and pending requests can be projected by a later application-specific schema.
        break;
    }
}
void PostGres::applyCanonicalBlock(const Block& block) {
    pqxx::work tx(connection_);
    auto existing=tx.exec_params("SELECT height FROM goc_projection_meta WHERE chain_id=$1 FOR UPDATE",block.header.chain_id);
    if(!existing.empty() && block.header.height <= existing[0][0].as<long long>()) {
        tx.abort(); throw std::runtime_error("Projection only accepts blocks in ascending canonical order; handle reorg explicitly");
    }
    for(const auto& item:block.transactions) applyTransaction(tx,item);
    tx.exec_params("INSERT INTO goc_projection_meta(chain_id,height,tip_hash) VALUES($1,$2,$3) ON CONFLICT(chain_id) DO UPDATE SET height=EXCLUDED.height,tip_hash=EXCLUDED.tip_hash",block.header.chain_id,block.header.height,block.hash_hex);
    for(const auto& item:block.transactions) tx.exec_params("INSERT INTO goc_events(chain_id,height,block_hash,operation,payload) VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT DO NOTHING",block.header.chain_id,block.header.height,block.hash_hex,operationName(item.operation),item.payload.dump());
    tx.commit();
}
void PostGres::rollbackBlock(const Block& block) {
    // Generic reverse execution is unsafe; a production implementation must reverse each operation from stored undo data.
    pqxx::work tx(connection_); tx.exec_params("DELETE FROM goc_events WHERE chain_id=$1 AND height=$2 AND block_hash=$3",block.header.chain_id,block.header.height,block.hash_hex);
    tx.exec_params("UPDATE goc_projection_meta SET height=$2,tip_hash=$3 WHERE chain_id=$1",block.header.chain_id,static_cast<long long>(block.header.height)-1,block.header.previous_hash);
    tx.commit();
    throw std::runtime_error("Rollback metadata updated, but application-state undo is not implemented; do not use reorgs in production yet");
}
nlohmann::json PostGres::getRepository(const std::string& id) {
    pqxx::read_transaction tx(connection_); auto r=tx.exec_params("SELECT repository_id,owner_key,metadata FROM goc_repositories WHERE repository_id=$1",id);
    if(r.empty())return nullptr; return {{"repository_id",r[0][0].c_str()},{"owner_key",r[0][1].c_str()},{"metadata",nlohmann::json::parse(r[0][2].c_str())}};
}
void PostGres::executeReadOnly(const std::string& sql) {
    // Keep arbitrary SQL out of public CRUD APIs. This function intentionally supports only SELECT.
    auto first=sql.find_first_not_of(" \t\r\n"); if(first==std::string::npos || sql.substr(first,6)!="SELECT") throw std::invalid_argument("Only SELECT statements are allowed");
    pqxx::read_transaction tx(connection_); (void)tx.exec(sql);
}
}
