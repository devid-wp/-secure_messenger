#ifndef SECURE_MESSENGER_AUTH_H
#define SECURE_MESSENGER_AUTH_H

#include <string>

struct UserRecord {
    std::string login;
    std::string hash;
    std::string salt;
};

class AuthManager {
public:
    UserRecord register_user(const std::string& login, const std::string& password);
    bool verify_user(const std::string& login,
                     const std::string& password,
                     const std::string& hash,
                     const std::string& salt);
};

#endif // SECURE_MESSENGER_AUTH_H
