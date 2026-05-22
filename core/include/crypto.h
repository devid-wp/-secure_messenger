#ifndef SECURE_MESSENGER_CRYPTO_H
#define SECURE_MESSENGER_CRYPTO_H

#include <string>

class CryptoEngine {
public:
    std::string generate_salt();
    std::string hash_password(const std::string& password, const std::string& salt);
    bool secure_compare(const std::string& a, const std::string& b);
};

#endif // SECURE_MESSENGER_CRYPTO_H
