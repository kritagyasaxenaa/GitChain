#include "CreateBlock.h"
#include "Crypto.h"
#include <chrono>
#include <stdexcept>

namespace goc {
Block CreateBlock::build(ChainType type,const std::string& chain_id,std::uint64_t height,const std::string& previous_hash,
                         const std::string& target_hex,const std::vector<Transaction>& txs,
                         const std::string& public_key) {
    Block b; b.header.chain_type=type; b.header.chain_id=chain_id; b.header.height=height; b.header.previous_hash=previous_hash;
    b.header.timestamp=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count());
    b.header.target_hex=target_hex; b.transactions=txs; b.producer_public_key=public_key;
    b.header.nonce="0";
    // The caller supplies the private key to mine(); private keys are never stored in a block.
    return b;
}
bool CreateBlock::mine(Block& b,const std::string& private_key,std::uint64_t max_attempts) {
    const auto target=Crypto::hexToBigInt(b.header.target_hex);
    for(std::uint64_t i=0;i<max_attempts;++i){ b.header.nonce=std::to_string(i); b.hash_hex=Crypto::calculateBlockHash(b);
        if(Crypto::hexToBigInt(b.hash_hex)<=target){ b.producer_signature_hex=Crypto::sign(private_key,b.hash_hex); return true; } }
    return false;
}
std::string CreateBlock::encode(const Block& b) { return blockToJson(b).dump(); }
}
