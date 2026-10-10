#include "UserReg.h"
#include "Block.h"
#include <stdexcept>
namespace goc {
std::string UserReg::identityId(const std::string& public_key) { return Crypto::sha256Hex(public_key); }
LocalIdentity UserReg::createLocalIdentity(const std::string& username) {
    if(username.empty()||username.size()>64)throw std::invalid_argument("Username must contain 1-64 characters");
    auto keys=Crypto::generateKeyPair(); return {username,identityId(keys.public_key_pem),std::move(keys)};
}
Transaction UserReg::registrationTransaction(const LocalIdentity& identity) {
    Transaction tx; tx.operation=Operation::UserCreate; tx.actor_public_key=identity.keys.public_key_pem;
    tx.payload={{"username",identity.username},{"identity_id",identity.identity_id}};
    // Caller must sign transactionToJson(tx) with the local private key before submission.
    return tx;
}
}
