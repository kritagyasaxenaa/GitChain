#pragma once
#include "Block.h"
#include <string>
namespace goc {
class AccessControl {
public:
    static Transaction request(const std::string& requester_public_key, const std::string& repo_id, const std::string& role);
    static Transaction grant(const std::string& admin_public_key, const std::string& repo_id, const std::string& subject_public_key, const std::string& role);
    static Transaction revoke(const std::string& admin_public_key, const std::string& repo_id, const std::string& subject_public_key);
};
}
