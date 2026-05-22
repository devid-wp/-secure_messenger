#include "../include/crypto.h"
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdexcept>

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
