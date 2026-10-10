#include "UserReg.h"
#include "CreateBlock.h"
#include "Crypto.h"
#include <iostream>
#include <stdexcept>

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            std::cout << "GitHub-on-Chain prototype\n"
                      << "Usage: github_on_chain create-identity <username>\n"
                      << "This command creates a local keypair only; it does not register on-chain.\n";
            return 0;
        }
        const std::string command=argv[1];
        if(command=="create-identity") {
            if(argc!=3)throw std::invalid_argument("Expected username");
            auto identity=goc::UserReg::createLocalIdentity(argv[2]);
            std::cout << "Identity ID: " << identity.identity_id << "\n"
                      << "Public key PEM:\n" << identity.keys.public_key_pem
                      << "Private key PEM (keep secret; store securely):\n" << identity.keys.private_key_pem;
            return 0;
        }
        throw std::invalid_argument("Unknown command: "+command);
    } catch(const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n'; return 1;
    }
}
