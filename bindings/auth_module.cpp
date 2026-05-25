#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "../core/include/auth.h"

namespace py = pybind11;

PYBIND11_MODULE(auth_core, m) {
    m.doc() = "Модуль аутентификации для защищённого мессенджера";

    py::class_<UserRecord>(m, "UserRecord")
        .def(py::init<>())
        .def_readwrite("login", &UserRecord::login, "Логин пользователя")
        .def_readwrite("hash", &UserRecord::hash, "Хеш пароля (бинарные данные)")
        .def_readwrite("salt", &UserRecord::salt, "Соль (бинарные данные)")
        .def(
            "__repr__",
            [](const UserRecord& self) {
                return std::string("<UserRecord login='") + self.login + "'>";
            }
        );

    py::class_<AuthManager>(m, "AuthManager")
        .def(py::init<>())
        .def(
            "register_user",
            [](AuthManager& self, const std::string& login, const std::string& password) -> py::dict {
                UserRecord record = self.register_user(login, password);
                py::dict result;
                result["login"] = record.login;
                result["hash"] = py::bytes(record.hash);
                result["salt"] = py::bytes(record.salt);
                return result;
            },
            py::arg("login"), py::arg("password"),
            "Регистрирует нового пользователя. Возвращает dict с login, hash, salt"
        )
        .def(
            "verify_user",
            [](AuthManager& self, const std::string& login, const std::string& password,
               const py::bytes& stored_hash, const py::bytes& stored_salt) -> bool {
                std::string hash_str(stored_hash);
                std::string salt_str(stored_salt);
                return self.verify_user(login, password, hash_str, salt_str);
            },
            py::arg("login"), py::arg("password"), py::arg("stored_hash"), py::arg("stored_salt"),
            "Проверяет пароль пользователя. Возвращает True если пароль верен"
        );

    py::register_exception<std::runtime_error>(m, "AuthError", PyExc_RuntimeError);
}
