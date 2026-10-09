#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

std::string hexString(uint64_t value) {
    std::stringstream stream;
    stream << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return stream.str();
}

std::string buildTransactionFingerprint(
    const std::string& repoId,
    const std::string& author,
    const std::string& operation,
    const std::string& commitId,
    const std::string& payload,
    const std::string& parentCommit
) {
    std::string input = repoId + "|" + author + "|" + operation + "|" + commitId + "|" + payload;
    if (!parentCommit.empty()) {
        input += "|" + parentCommit;
    }

    uint64_t hash = 14695981039346656037ull;
    for (unsigned char ch : input) {
        hash ^= static_cast<uint64_t>(ch);
        hash *= 1099511628211ull;
    }

    return hexString(hash);
}

int main(int argc, char** argv) {
    std::string repoId;
    std::string author;
    std::string operation;
    std::string commitId;
    std::string payload;
    std::string parentCommit;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--repo-id" && i + 1 < argc) {
            repoId = argv[++i];
        } else if (arg == "--author" && i + 1 < argc) {
            author = argv[++i];
        } else if (arg == "--operation" && i + 1 < argc) {
            operation = argv[++i];
        } else if (arg == "--commit-id" && i + 1 < argc) {
            commitId = argv[++i];
        } else if (arg == "--payload" && i + 1 < argc) {
            payload = argv[++i];
        } else if (arg == "--parent-commit" && i + 1 < argc) {
            parentCommit = argv[++i];
        }
    }

    if (repoId.empty() || author.empty() || operation.empty() || commitId.empty() || payload.empty()) {
        std::cerr << "Missing required arguments" << std::endl;
        return 1;
    }

    std::string txHash = buildTransactionFingerprint(repoId, author, operation, commitId, payload, parentCommit);
    std::cout << "{\"repo_id\":\"" << repoId << "\",\"author\":\"" << author << "\",\"operation\":\"" << operation
              << "\",\"commit_id\":\"" << commitId << "\",\"parent_commit\":\"" << parentCommit << "\",\"tx_hash\":\""
              << txHash << "\",\"valid\":true}\n";

    return 0;
}
