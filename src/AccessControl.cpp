#include "AccessControl.h"
namespace goc {
Transaction AccessControl::request(const std::string& key,const std::string& repo,const std::string& role) {
    Transaction tx; tx.operation=Operation::AccessRequest; tx.actor_public_key=key; tx.repository_id=repo; tx.payload={{"requested_role",role}}; return tx;
}
Transaction AccessControl::grant(const std::string& key,const std::string& repo,const std::string& subject,const std::string& role) {
    Transaction tx; tx.operation=Operation::AccessGrant; tx.actor_public_key=key; tx.repository_id=repo; tx.payload={{"subject_public_key",subject},{"role",role}}; return tx;
}
Transaction AccessControl::revoke(const std::string& key,const std::string& repo,const std::string& subject) {
    Transaction tx; tx.operation=Operation::AccessRevoke; tx.actor_public_key=key; tx.repository_id=repo; tx.payload={{"subject_public_key",subject}}; return tx;
}
}
