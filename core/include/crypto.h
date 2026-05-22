#ifndef SECURE_MESSENGER_CRYPTO_H
#define SECURE_MESSENGER_CRYPTO_H

#include <openssl/crypto.h>
#include <string>
#include <cstddef>

class CryptoEngine {
public:
    std::string generate_salt();
    std::string hash_password(const std::string& password, const std::string& salt);
    bool secure_compare(const std::string& a, const std::string& b);
};

class MemoryGuard {
public:
    MemoryGuard(void* buffer, std::size_t size);
    MemoryGuard(const MemoryGuard&) = delete;
    MemoryGuard& operator=(const MemoryGuard&) = delete;
    ~MemoryGuard();

private:
    void* buffer_;
    std::size_t size_;
};

template <typename StringType>
inline void clear_string(StringType& s) {
    if (!s.empty()) {
        OPENSSL_cleanse(const_cast<char*>(s.data()), s.size());
        s.clear();
    }
}

#endif // SECURE_MESSENGER_CRYPTO_H
