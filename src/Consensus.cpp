#include "Consensus.h"
#include "PostGres.h"
#include "Crypto.h"
#include <nlohmann/json.hpp>
#include <rocksdb/options.h>
#include <rocksdb/write_batch.h>
#include <stdexcept>

namespace goc {
namespace {
std::string scoreString(const BigInt& v) { return v.convert_to<std::string>(); }
BigInt parseScore(const std::string& s) { BigInt v=0; for(char c:s){if(c<'0'||c>'9')throw std::runtime_error("Corrupt score in RocksDB");v=v*10+(c-'0');}return v; }
std::string canonicalKey(std::uint64_t height) { return "canonical:"+std::to_string(height); }
}
Consensus::Consensus(const std::string& path,std::string chain_id,ChainType type,PostGres* projection)
 :chain_id_(std::move(chain_id)),type_(type),projection_(projection) {
    rocksdb::Options options; options.create_if_missing=true;
    auto status=rocksdb::DB::Open(options,path,&db_); if(!status.ok())throw std::runtime_error("RocksDB open failed: "+status.ToString());
    loadTip();
}
Consensus::~Consensus(){delete db_;}
void Consensus::setError(std::string* out,const std::string& msg) const { if(out)*out=msg; }
std::string Consensus::blockKey(const std::string& h) const { return "block:"+h; }
std::string Consensus::scoreKey(const std::string& h) const { return "score:"+h; }
std::optional<Block> Consensus::readBlock(const std::string& hash) const {
    std::string value; auto s=db_->Get(rocksdb::ReadOptions(),blockKey(hash),&value); if(s.IsNotFound())return std::nullopt; if(!s.ok())throw std::runtime_error(s.ToString());
    return blockFromJson(nlohmann::json::parse(value));
}
BigInt Consensus::readScore(const std::string& hash) const { std::string value; auto s=db_->Get(rocksdb::ReadOptions(),scoreKey(hash),&value); if(!s.ok())throw std::runtime_error("Missing accumulated score for block: "+hash); return parseScore(value); }
void Consensus::loadTip() {
    std::string hash; auto s=db_->Get(rocksdb::ReadOptions(),"meta:tip_hash",&hash); if(s.IsNotFound())return; if(!s.ok())throw std::runtime_error(s.ToString());
    tip_hash_=hash; std::string h; if(db_->Get(rocksdb::ReadOptions(),"meta:tip_height",&h).ok())tip_height_=std::stoull(h); tip_score_=readScore(hash);
}
std::string Consensus::tipHash() const { std::lock_guard<std::mutex> lock(mutex_); return tip_hash_; }
std::uint64_t Consensus::tipHeight() const { std::lock_guard<std::mutex> lock(mutex_); return tip_height_; }
BigInt Consensus::accumulatedScore() const { std::lock_guard<std::mutex> lock(mutex_); return tip_score_; }
std::optional<Block> Consensus::getBlock(const std::string& hash) const { return readBlock(hash); }
bool Consensus::validateBlock(const Block& b,std::string* reason) const {
    if(b.header.chain_id!=chain_id_ || b.header.chain_type!=type_){setError(reason,"Wrong chain ID or chain type");return false;}
    if(!Crypto::verifyPow(b)){setError(reason,"Invalid block hash or proof-of-work target");return false;}
    if(!Crypto::verifyProducerSignature(b)){setError(reason,"Invalid producer signature");return false;}
    if(b.header.height==0) { if(!b.header.previous_hash.empty()){setError(reason,"Genesis block must have empty previous_hash");return false;} }
    else {
        auto parent=readBlock(b.header.previous_hash); if(!parent){setError(reason,"Unknown parent block; synchronize parent first");return false;}
        if(parent->header.height+1!=b.header.height){setError(reason,"Height does not follow parent");return false;}
        if(parent->header.chain_id!=b.header.chain_id){setError(reason,"Parent belongs to another chain");return false;}
        if(parent->header.timestamp>b.header.timestamp){setError(reason,"Block timestamp precedes parent");return false;}
    }
    // Transaction signature and permission/state validation must be implemented against the parent-state snapshot
    // before enabling untrusted peers. This starter rejects unsigned transactions but leaves operation-specific
    // authorization to the application layer for now.
    for(const auto& tx:b.transactions) {
        if(tx.actor_public_key.empty() || tx.signature_hex.empty()){setError(reason,"Unsigned transaction");return false;}
        if(!Crypto::verifySignature(tx.actor_public_key,transactionToJson(Transaction{tx.operation,tx.actor_public_key,tx.repository_id,tx.payload,""}).dump(),tx.signature_hex)) {
            setError(reason,"Invalid transaction signature");return false;
        }
    }
    return true;
}
bool Consensus::persistCandidate(const Block& b,const std::string& hash,const std::string& parent_hash,const BigInt& score) {
    rocksdb::WriteBatch batch; batch.Put(blockKey(hash),blockToJson(b).dump()); batch.Put(scoreKey(hash),scoreString(score)); batch.Put("parent:"+hash,parent_hash);
    // All nodes use integer sqrt and sum; the score is persisted as a decimal integer.
    auto status=db_->Write(rocksdb::WriteOptions(),&batch); if(!status.ok())throw std::runtime_error("RocksDB write failed: "+status.ToString()); return true;
}
void Consensus::recomputeCanonicalTip() {
    // This prototype keeps candidate branches, but automatic PostgreSQL state rollback/replay is intentionally
    // not claimed complete. Canonical index is updated only for an extension of the current tip below.
}
bool Consensus::receiveBlock(const Block& b,std::string* reason) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(!validateBlock(b,reason))return false;
    if(readBlock(b.hash_hex)){setError(reason,"Block already known");return true;}
    const bool extends_tip = (b.header.height==0 && tip_hash_.empty()) || (!tip_hash_.empty() && b.header.previous_hash==tip_hash_);
    if(!extends_tip){setError(reason,"Block must extend the current chain tip");return false;}
    BigInt parent_score=0;
    if(b.header.height>0) parent_score=readScore(b.header.previous_hash);
    BigInt score;
    try { score=parent_score+Crypto::blockScore(b.header.target_hex,b.hash_hex); }
    catch(const std::exception& e){setError(reason,e.what());return false;}
    persistCandidate(b,b.hash_hex,b.header.previous_hash,score);
    rocksdb::WriteBatch batch; batch.Put(canonicalKey(b.header.height),b.hash_hex); batch.Put("meta:tip_hash",b.hash_hex); batch.Put("meta:tip_height",std::to_string(b.header.height));
    auto status=db_->Write(rocksdb::WriteOptions(),&batch); if(!status.ok())throw std::runtime_error("Canonical index update failed: "+status.ToString());
    tip_hash_=b.hash_hex; tip_height_=b.header.height; tip_score_=score;
    if(projection_) projection_->applyCanonicalBlock(b);
    return true;
}
std::vector<std::string> Consensus::getLocator(std::size_t max_entries) const {
    std::lock_guard<std::mutex> lock(mutex_); std::vector<std::string> out; if(tip_hash_.empty())return out;
    std::string current=tip_hash_; std::uint64_t height=tip_height_; std::uint64_t step=1;
    while(out.size()<max_entries){out.push_back(current);if(height==0)break; auto b=readBlock(current);if(!b)break;current=b->header.previous_hash;--height;if(out.size()>10)step=2; if(step>1 && height>0){for(std::uint64_t j=1;j<step;++j){auto p=readBlock(current);if(!p)break;current=p->header.previous_hash;--height;}step*=2;}}
    return out;
}
std::vector<Block> Consensus::blocksAfterCommonAncestor(const std::vector<std::string>& locator) const {
    std::lock_guard<std::mutex> lock(mutex_); std::string ancestor;
    for(const auto& hash:locator){std::string canonical; if(db_->Get(rocksdb::ReadOptions(),canonicalKey(readBlock(hash)?readBlock(hash)->header.height:UINT64_MAX),&canonical).ok()&&canonical==hash){ancestor=hash;break;}}
    std::uint64_t start=0;if(!ancestor.empty()){auto a=readBlock(ancestor);start=a->header.height+1;}
    std::vector<Block> result;for(std::uint64_t h=start;h<=tip_height_&&!tip_hash_.empty();++h){std::string hash;if(!db_->Get(rocksdb::ReadOptions(),canonicalKey(h),&hash).ok())break;auto b=readBlock(hash);if(b)result.push_back(*b);}
    return result;
}
}
