import pytest
import sys
from pathlib import Path

# Добавляем папку build в sys.path для импорта скомпилированных модулей
build_path = Path(__file__).parent.parent / "core" / "build"
if build_path.exists():
    sys.path.insert(0, str(build_path))


class TestBindings:
    """Тесты для проверки pybind11 биндингов auth_core и crypto_core"""

    def test_imports(self):
        """Проверяем что модули импортируются без ошибок"""
        try:
            import auth_core
            import crypto_core
        except ImportError as e:
            pytest.skip(f"Модули не скомпилированы: {e}")


class TestCryptoCore:
    """Тесты для модуля crypto_core"""

    @pytest.fixture(autouse=True)
    def setup_crypto(self):
        """Инициализируем CryptoEngine для каждого теста"""
        try:
            import crypto_core
            self.crypto = crypto_core.CryptoEngine()
        except ImportError:
            pytest.skip("crypto_core не скомпилирован")

    def test_generate_salt_returns_bytes(self):
        """generate_salt() возвращает bytes"""
        salt = self.crypto.generate_salt()
        assert isinstance(salt, bytes), f"Ожидаем bytes, получили {type(salt)}"

    def test_generate_salt_length(self):
        """generate_salt() возвращает 16 байт"""
        salt = self.crypto.generate_salt()
        assert len(salt) == 16, f"Ожидаем 16 байт, получили {len(salt)}"

    def test_generate_salt_randomness(self):
        """Два вызова generate_salt() дают разные результаты"""
        salt1 = self.crypto.generate_salt()
        salt2 = self.crypto.generate_salt()
        assert salt1 != salt2, "Две соли не должны быть одинаковыми"

    def test_secure_compare_equal(self):
        """secure_compare('abc', 'abc') == True"""
        result = self.crypto.secure_compare(b"abc", b"abc")
        assert result is True, "Одинаковые строки должны быть равны"

    def test_secure_compare_not_equal(self):
        """secure_compare('abc', 'abd') == False"""
        result = self.crypto.secure_compare(b"abc", b"abd")
        assert result is False, "Разные строки должны быть не равны"

    def test_hash_password_returns_bytes(self):
        """hash_password() возвращает bytes"""
        salt = self.crypto.generate_salt()
        hash_result = self.crypto.hash_password(b"password", salt)
        assert isinstance(hash_result, bytes), f"Ожидаем bytes, получили {type(hash_result)}"


class TestAuthCore:
    """Тесты для модуля auth_core"""

    @pytest.fixture(autouse=True)
    def setup_auth(self):
        """Инициализируем AuthManager для каждого теста"""
        try:
            import auth_core
            self.auth = auth_core.AuthManager()
        except ImportError:
            pytest.skip("auth_core не скомпилирован")

    def test_register_user_returns_dict(self):
        """register_user возвращает dict"""
        record = self.auth.register_user("alice", "password123")
        assert isinstance(record, dict), f"Ожидаем dict, получили {type(record)}"

    def test_register_user_dict_keys(self):
        """register_user возвращает dict с ключами login, hash, salt"""
        record = self.auth.register_user("bob", "password456")
        assert "login" in record, "Должен быть ключ 'login'"
        assert "hash" in record, "Должен быть ключ 'hash'"
        assert "salt" in record, "Должен быть ключ 'salt'"

    def test_register_user_login_value(self):
        """register_user сохраняет логин в результате"""
        login = "charlie"
        record = self.auth.register_user(login, "password789")
        assert record["login"] == login, f"Логин должен быть '{login}'"

    def test_register_user_hash_and_salt_bytes(self):
        """register_user возвращает hash и salt как bytes"""
        record = self.auth.register_user("dave", "securePass1")
        assert isinstance(record["hash"], bytes), f"hash должен быть bytes, получили {type(record['hash'])}"
        assert isinstance(record["salt"], bytes), f"salt должен быть bytes, получили {type(record['salt'])}"

    def test_verify_user_correct_password(self):
        """verify_user возвращает True для правильного пароля"""
        password = "password123"
        record = self.auth.register_user("eve", password)
        result = self.auth.verify_user("eve", password, record["hash"], record["salt"])
        assert result is True, "verify_user должен вернуть True для правильного пароля"

    def test_verify_user_wrong_password(self):
        """verify_user возвращает False для неправильного пароля"""
        record = self.auth.register_user("frank", "password456")
        result = self.auth.verify_user("frank", "wrongpassword", record["hash"], record["salt"])
        assert result is False, "verify_user должен вернуть False для неправильного пароля"

    def test_register_user_different_hashes(self):
        """Два вызова register_user с одинаковым паролем дают разные hash"""
        password = "samePassword"
        record1 = self.auth.register_user("user1", password)
        record2 = self.auth.register_user("user2", password)
        assert record1["hash"] != record2["hash"], "Разные соли должны дать разные хеши"
        assert record1["salt"] != record2["salt"], "Каждый вызов должен генерировать новую соль"

    def test_register_user_empty_password_raises(self):
        """register_user бросает исключение на пустой пароль"""
        try:
            import auth_core
            with pytest.raises(RuntimeError):
                self.auth.register_user("grace", "")
        except ImportError:
            pytest.skip("auth_core не скомпилирован")

    def test_register_user_short_password_raises(self):
        """register_user бросает исключение на пароль менее 8 символов"""
        try:
            import auth_core
            with pytest.raises(RuntimeError):
                self.auth.register_user("henry", "short")
        except ImportError:
            pytest.skip("auth_core не скомпилирован")
