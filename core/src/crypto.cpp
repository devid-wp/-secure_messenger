#include "../include/crypto.h"
#include <algorithm>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdexcept>

MemoryGuard::MemoryGuard(void* buffer, std::size_t size)
    : buffer_(buffer), size_(size) {}

MemoryGuard::~MemoryGuard() {
    if (buffer_ && size_ > 0) {
        OPENSSL_cleanse(buffer_, size_);
    }
}

std::string CryptoEngine::generate_salt() {
    constexpr size_t SALT_LEN = 16;
    std::string salt;
    salt.resize(SALT_LEN);

    // Заполняем буфер случайными байтами через OpenSSL RAND_bytes.
    if (RAND_bytes(reinterpret_cast<unsigned char*>(&salt[0]), SALT_LEN) != 1) {
        throw std::runtime_error("Failed to generate salt with OpenSSL RAND_bytes");
    }

    return salt;
}

std::string CryptoEngine::hash_password(const std::string& password, const std::string& salt) {
    constexpr int HASH_LEN = 32;
    constexpr int ITERATIONS = 100000;

    std::string hash;
    hash.resize(HASH_LEN);

    // Выполняем PBKDF2-HMAC-SHA256 с указанным количеством итераций.
    if (PKCS5_PBKDF2_HMAC(
            password.c_str(), static_cast<int>(password.size()),
            reinterpret_cast<const unsigned char*>(salt.data()), static_cast<int>(salt.size()),
            ITERATIONS,
            EVP_sha256(),
            HASH_LEN,
            reinterpret_cast<unsigned char*>(&hash[0])) != 1) {
        throw std::runtime_error("Failed to hash password with PBKDF2-HMAC-SHA256");
    }

    return hash;
}

bool CryptoEngine::secure_compare(const std::string& a, const std::string& b) {
    const size_t len = std::max(a.size(), b.size());
    unsigned char diff = static_cast<unsigned char>(a.size() ^ b.size());

    for (size_t i = 0; i < len; ++i) {
        unsigned char ca = i < a.size() ? static_cast<unsigned char>(a[i]) : 0;
        unsigned char cb = i < b.size() ? static_cast<unsigned char>(b[i]) : 0;
        diff |= ca ^ cb;
    }

    return diff == 0;
}
