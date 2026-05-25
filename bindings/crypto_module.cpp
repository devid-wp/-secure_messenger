#include <pybind11/pybind11.h>
#include "../core/include/crypto.h"

namespace py = pybind11;

PYBIND11_MODULE(crypto_core, m) {
    m.doc() = "Криптографическое ядро для защищённого мессенджера";

    py::class_<CryptoEngine>(m, "CryptoEngine")
        .def(py::init<>())
        .def(
            "generate_salt",
            [](CryptoEngine& self) -> py::bytes {
                std::string salt = self.generate_salt();
                return py::bytes(salt);
            },
            "Генерирует случайную соль (16 байт) для хеширования пароля"
        )
        .def(
            "hash_password",
            [](CryptoEngine& self, const py::bytes& password, const py::bytes& salt) -> py::bytes {
                std::string pwd_str(password);
                std::string salt_str(salt);
                std::string hash = self.hash_password(pwd_str, salt_str);
                return py::bytes(hash);
            },
            py::arg("password"), py::arg("salt"),
            "Хеширует пароль с солью используя PBKDF2-HMAC-SHA256 (100000 итераций)"
        )
        .def(
            "secure_compare",
            [](CryptoEngine& self, const py::bytes& a, const py::bytes& b) -> bool {
                std::string a_str(a);
                std::string b_str(b);
                return self.secure_compare(a_str, b_str);
            },
            py::arg("a"), py::arg("b"),
            "Сравнивает две строки в постоянное время (защита от timing attack)"
        );

    py::register_exception<std::runtime_error>(m, "CryptoError", PyExc_RuntimeError);
}
