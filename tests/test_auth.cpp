#define CATCH_CONFIG_MAIN
#include <catch2/catch.hpp>
#include "../core/include/auth.h"
#include "../core/include/crypto.h"

TEST_CASE("register_user returns non-empty hash and salt") {
    AuthManager auth;
    UserRecord record = auth.register_user("alice", "password123");

    REQUIRE(record.login == "alice");
    REQUIRE_FALSE(record.hash.empty());
    REQUIRE_FALSE(record.salt.empty());
}

TEST_CASE("verify_user returns true for correct password") {
    AuthManager auth;
    UserRecord record = auth.register_user("bob", "securePass9");

    REQUIRE(auth.verify_user("bob", "securePass9", record.hash, record.salt));
}

TEST_CASE("verify_user returns false for incorrect password") {
    AuthManager auth;
    UserRecord record = auth.register_user("charlie", "password456");

    REQUIRE_FALSE(auth.verify_user("charlie", "wrongpassword", record.hash, record.salt));
}

TEST_CASE("register_user with same password generates different hashes") {
    AuthManager auth;
    UserRecord first = auth.register_user("dave", "commonPass1");
    UserRecord second = auth.register_user("eve", "commonPass1");

    REQUIRE(first.hash != second.hash);
    REQUIRE(first.salt != second.salt);
}

TEST_CASE("secure_compare works correctly") {
    CryptoEngine crypto;
    REQUIRE(crypto.secure_compare("abc", "abc"));
    REQUIRE_FALSE(crypto.secure_compare("abc", "abd"));
    REQUIRE_FALSE(crypto.secure_compare("abc", "abcd"));
}

TEST_CASE("register_user throws on empty password") {
    AuthManager auth;
    REQUIRE_THROWS_AS(auth.register_user("frank", ""), std::runtime_error);
}
