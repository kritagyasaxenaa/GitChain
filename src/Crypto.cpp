#include "Crypto.h"
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/obj_mac.h>
#include <openssl/err.h>
#include <array>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>

namespace goc {
namespace {
using PKey = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;
using MdCtx = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
std::string bytesToHex(const unsigned char* bytes, std::size_t n) {
    std::ostringstream out; out << std::hex << std::setfill('0');
    for (std::size_t i=0;i<n;++i) out << std::setw(2) << static_cast<unsigned>(bytes[i]);
    return out.str();
}
std::vector<unsigned char> hexToBytes(const std::string& hex) {
    if (hex.size()%2) throw std::invalid_argument("Hex string has odd length");
    std::vector<unsigned char> out; out.reserve(hex.size()/2);
    auto digit=[](char c)->int { if(c>='0'&&c<='9')return c-'0'; if(c>='a'&&c<='f')return c-'a'+10; if(c>='A'&&c<='F')return c-'A'+10; return -1; };
    for(std::size_t i=0;i<hex.size();i+=2){ int a=digit(hex[i]),b=digit(hex[i+1]); if(a<0||b<0)throw std::invalid_argument("Invalid hex"); out.push_back(static_cast<unsigned char>((a<<4)|b)); }
    return out;
}
PKey readPrivate(const std::string& pem) {
    BIO* raw = BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size()));
    if (!raw) throw std::runtime_error("BIO allocation failed");
    PKey key(PEM_read_bio_PrivateKey(raw, nullptr, nullptr, nullptr), EVP_PKEY_free); BIO_free(raw);
    if (!key) throw std::runtime_error("Unable to parse private key PEM"); return key;
}
PKey readPublic(const std::string& pem) {
    BIO* raw = BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size()));
    if (!raw) throw std::runtime_error("BIO allocation failed");
    PKey key(PEM_read_bio_PUBKEY(raw, nullptr, nullptr, nullptr), EVP_PKEY_free); BIO_free(raw);
    if (!key) throw std::runtime_error("Unable to parse public key PEM"); return key;
}
}
KeyPair Crypto::generateKeyPair() {
    EVP_PKEY_CTX* rawctx = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, nullptr);
    if (!rawctx) throw std::runtime_error("EVP_PKEY_CTX_new_id failed");
    std::unique_ptr<EVP_PKEY_CTX, decltype(&EVP_PKEY_CTX_free)> ctx(rawctx, EVP_PKEY_CTX_free);
    if (EVP_PKEY_keygen_init(ctx.get()) <= 0 || EVP_PKEY_CTX_set_ec_paramgen_curve_nid(ctx.get(), NID_X9_62_prime256v1) <= 0)
        throw std::runtime_error("ECDSA P-256 initialization failed");
    EVP_PKEY* rawkey = nullptr; if (EVP_PKEY_keygen(ctx.get(), &rawkey) <= 0) throw std::runtime_error("Key generation failed");
    PKey key(rawkey, EVP_PKEY_free);
    auto writePem=[&](bool priv){ BIO* bio=BIO_new(BIO_s_mem()); if(!bio)throw std::runtime_error("BIO allocation failed");
        int ok=priv?PEM_write_bio_PrivateKey(bio,key.get(),nullptr,nullptr,0,nullptr,nullptr):PEM_write_bio_PUBKEY(bio,key.get());
        if(ok!=1){BIO_free(bio);throw std::runtime_error("PEM encoding failed");} BUF_MEM* mem=nullptr; BIO_get_mem_ptr(bio,&mem); std::string s(mem->data,mem->length); BIO_free(bio); return s;};
    return {writePem(false), writePem(true)};
}
std::string Crypto::sha256Hex(const std::string& data) {
    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{}; unsigned int len=0;
    if (EVP_Digest(data.data(), data.size(), digest.data(), &len, EVP_sha256(), nullptr) != 1) throw std::runtime_error("SHA-256 failed");
    return bytesToHex(digest.data(), len);
}
std::string Crypto::canonicalBlockHeader(const BlockHeader& h) {
    // Fixed field order and JSON encoding are part of this prototype's consensus rules.
    return nlohmann::json{{"chain_type",h.chain_type==ChainType::L1?"L1":"L2"},{"chain_id",h.chain_id},
      {"height",h.height},{"previous_hash",h.previous_hash},{"timestamp",h.timestamp},{"nonce",h.nonce},{"target_hex",h.target_hex}}.dump();
}
std::string Crypto::calculateBlockHash(const Block& b) {
    nlohmann::json txs=nlohmann::json::array();
    for (const auto& tx : b.transactions) txs.push_back(transactionToJson(tx));
    // Include all consensus-relevant block content. Producer signature is excluded to avoid circular hashing.
    nlohmann::json preimage={{"header",nlohmann::json::parse(canonicalBlockHeader(b.header))},
                             {"transactions",txs},{"producer_public_key",b.producer_public_key}};
    return sha256Hex(preimage.dump());
}
std::string Crypto::sign(const std::string& private_pem, const std::string& message) {
    auto key=readPrivate(private_pem); MdCtx ctx(EVP_MD_CTX_new(),EVP_MD_CTX_free); if(!ctx)throw std::runtime_error("MD context allocation failed");
    if(EVP_DigestSignInit(ctx.get(),nullptr,EVP_sha256(),nullptr,key.get())!=1 || EVP_DigestSignUpdate(ctx.get(),message.data(),message.size())!=1) throw std::runtime_error("ECDSA sign init/update failed");
    std::size_t n=0; if(EVP_DigestSignFinal(ctx.get(),nullptr,&n)!=1)throw std::runtime_error("ECDSA signature size failed");
    std::vector<unsigned char> sig(n); if(EVP_DigestSignFinal(ctx.get(),sig.data(),&n)!=1)throw std::runtime_error("ECDSA signing failed"); return bytesToHex(sig.data(),n);
}
bool Crypto::verifySignature(const std::string& public_pem,const std::string& message,const std::string& sig_hex) {
    try { auto key=readPublic(public_pem); auto sig=hexToBytes(sig_hex); MdCtx ctx(EVP_MD_CTX_new(),EVP_MD_CTX_free); if(!ctx)return false;
        if(EVP_DigestVerifyInit(ctx.get(),nullptr,EVP_sha256(),nullptr,key.get())!=1 || EVP_DigestVerifyUpdate(ctx.get(),message.data(),message.size())!=1)return false;
        return EVP_DigestVerifyFinal(ctx.get(),sig.data(),sig.size())==1;
    } catch (...) { return false; }
}
BigInt Crypto::hexToBigInt(const std::string& hex) {
    std::string s=hex; if(s.rfind("0x",0)==0||s.rfind("0X",0)==0)s=s.substr(2); if(s.empty()||s.size()>64)throw std::invalid_argument("Expected 1-64 hex digits");
    BigInt v=0; for(char c:s){int d;if(c>='0'&&c<='9')d=c-'0';else if(c>='a'&&c<='f')d=c-'a'+10;else if(c>='A'&&c<='F')d=c-'A'+10;else throw std::invalid_argument("Invalid hex");v=(v<<4)|d;} return v;
}
std::string Crypto::bigIntToHex(const BigInt& v) { std::ostringstream out; out<<std::hex<<std::setfill('0')<<std::setw(64)<<v; return out.str(); }
BigInt Crypto::integerSqrt(const BigInt& n) {
    if(n==0)return 0; BigInt x=n, y=(x+1)>>1; while(y<x){x=y;y=(x+n/x)>>1;} return x;
}
BigInt Crypto::blockScore(const std::string& target_hex,const std::string& hash_hex) {
    BigInt t=hexToBigInt(target_hex), h=hexToBigInt(hash_hex); if(h>t)throw std::invalid_argument("Hash exceeds target"); return integerSqrt(t-h);
}
bool Crypto::verifyPow(const Block& b) {
    try { if(b.header.target_hex.size()!=64 || b.hash_hex.size()!=64)return false; if(calculateBlockHash(b)!=b.hash_hex)return false; return hexToBigInt(b.hash_hex)<=hexToBigInt(b.header.target_hex); } catch (...) { return false; }
}
bool Crypto::verifyProducerSignature(const Block& b) { return verifySignature(b.producer_public_key, b.hash_hex, b.producer_signature_hex); }
std::string Crypto::signTransaction(const Transaction& tx, const std::string& private_key_pem) {
    Transaction unsigned_tx=tx; unsigned_tx.signature_hex.clear();
    return sign(private_key_pem, transactionToJson(unsigned_tx).dump());
}
}
