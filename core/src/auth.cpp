#include "../include/auth.h"
#include "../include/crypto.h"
#include <stdexcept>

UserRecord AuthManager::register_user(const std::string& login, const std::string& password) {
    if (login.empty()) {
        throw std::runtime_error("Login must not be empty");
    }
    if (password.size() < 8) {
        throw std::runtime_error("Password must be at least 8 characters long");
    }

    CryptoEngine engine;
    std::string password_copy = password;
    MemoryGuard password_guard(password_copy.data(), password_copy.size());

    const std::string salt = engine.generate_salt();
    std::string hash = engine.hash_password(password_copy, salt);

    UserRecord record{login, hash, salt};
    clear_string(hash);

    return record;
}
