#pragma once
#include "Block.h"
#include <boost/multiprecision/cpp_int.hpp>
#include <string>
#include <utility>

namespace goc {
using BigInt = boost::multiprecision::cpp_int;
struct KeyPair { std::string public_key_pem; std::string private_key_pem; };

class Crypto {
public:
    static KeyPair generateKeyPair();
    static std::string sha256Hex(const std::string& data);
    static std::string canonicalBlockHeader(const BlockHeader& header);
    static std::string calculateBlockHash(const Block& block);
    static std::string sign(const std::string& private_key_pem, const std::string& message);
    static bool verifySignature(const std::string& public_key_pem, const std::string& message, const std::string& signature_hex);
    static BigInt hexToBigInt(const std::string& hex);
    static std::string bigIntToHex(const BigInt& value);
    static BigInt integerSqrt(const BigInt& value);
    static BigInt blockScore(const std::string& target_hex, const std::string& hash_hex);
    static bool verifyPow(const Block& block);
    static bool verifyProducerSignature(const Block& block);
    static std::string signTransaction(const Transaction& tx, const std::string& private_key_pem);
};
}
