#pragma once
#include "Crypto.h"
#include <string>
namespace goc {
struct LocalIdentity { std::string username; std::string identity_id; KeyPair keys; };
class UserReg {
public:
    // Generates local keys only. It deliberately does not create or mine a block.
    static LocalIdentity createLocalIdentity(const std::string& username);
    static std::string identityId(const std::string& public_key_pem);
    static Transaction registrationTransaction(const LocalIdentity& identity);
};
}
