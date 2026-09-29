"""Native Keychain access via SecItem APIs; secrets never enter process argv.

The service/account match the previous security CLI implementation, so existing
login-keychain credentials remain accessible. Frameworks are loaded on demand.
"""

import ctypes
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

SERVICE = "com.flyall.JournalRadar.Universal"
ACCOUNT = "translation-api-key"
NOT_FOUND = -25300
DUPLICATE_ITEM = -25299


class Keychain:
    def __init__(self, account: str = ACCOUNT):
        self.account = account
        self.security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        pointer = ctypes.c_void_p
        self._bind(
            self.cf,
            "CFStringCreateWithCString",
            [pointer, ctypes.c_char_p, ctypes.c_uint32],
            pointer,
        )
        self._bind(
            self.cf,
            "CFDictionaryCreateMutable",
            [pointer, ctypes.c_long, pointer, pointer],
            pointer,
        )
        self._bind(self.cf, "CFDictionarySetValue", [pointer, pointer, pointer], None)
        self._bind(self.cf, "CFDataCreate", [pointer, pointer, ctypes.c_long], pointer)
        self._bind(self.cf, "CFDataGetLength", [pointer], ctypes.c_long)
        self._bind(self.cf, "CFDataGetBytePtr", [pointer], pointer)
        self._bind(self.cf, "CFRelease", [pointer], None)
        self._bind(
            self.security, "SecItemCopyMatching", [pointer, ctypes.POINTER(pointer)], ctypes.c_int32
        )
        self._bind(self.security, "SecItemAdd", [pointer, pointer], ctypes.c_int32)
        self._bind(self.security, "SecItemUpdate", [pointer, pointer], ctypes.c_int32)
        self._bind(self.security, "SecItemDelete", [pointer], ctypes.c_int32)

    @staticmethod
    def _bind(library, name, arguments, result):
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result

    def _constant(self, name):
        library = self.cf if name == "kCFBooleanTrue" else self.security
        return ctypes.c_void_p.in_dll(library, name).value

    @contextmanager
    def _dictionary(self, attributes):
        # CFType callbacks retain keys and values. Owned temporary objects can
        # therefore be released immediately after insertion.
        keys = ctypes.addressof(
            (ctypes.c_byte * 1).in_dll(self.cf, "kCFTypeDictionaryKeyCallBacks")
        )
        values = ctypes.addressof(
            (ctypes.c_byte * 1).in_dll(self.cf, "kCFTypeDictionaryValueCallBacks")
        )
        query = self.cf.CFDictionaryCreateMutable(None, 0, keys, values)
        if not query:
            raise MemoryError("无法创建钥匙串查询")
        try:
            for name, value in attributes.items():
                owned = False
                if isinstance(value, str):
                    reference = self.cf.CFStringCreateWithCString(
                        None, value.encode("utf-8"), 0x08000100
                    )
                    owned = True
                elif isinstance(value, bytes):
                    reference = self.cf.CFDataCreate(None, value, len(value))
                    owned = True
                else:
                    reference = value
                try:
                    self.cf.CFDictionarySetValue(query, self._constant(name), reference)
                finally:
                    if owned and reference:
                        self.cf.CFRelease(reference)
            yield query
        finally:
            self.cf.CFRelease(query)

    def _identity(self):
        return {
            "kSecClass": self._constant("kSecClassGenericPassword"),
            "kSecAttrService": SERVICE,
            "kSecAttrAccount": self.account,
        }

    @staticmethod
    def _check(status):
        if status != 0:
            raise RuntimeError(
                f"macOS 钥匙串操作失败（错误码 {status}）；请检查钥匙串是否锁定或拒绝了访问"
            )

    def load(self) -> str:
        attributes = self._identity()
        attributes["kSecReturnData"] = self._constant("kCFBooleanTrue")
        result = ctypes.c_void_p()
        with self._dictionary(attributes) as query:
            status = self.security.SecItemCopyMatching(query, ctypes.byref(result))
        if status == NOT_FOUND:
            return ""
        self._check(status)
        try:
            length = self.cf.CFDataGetLength(result)
            return ctypes.string_at(self.cf.CFDataGetBytePtr(result), length).decode("utf-8")
        finally:
            if result:
                self.cf.CFRelease(result)

    def save(self, key: str) -> None:
        identity = self._identity()
        if not key:
            with self._dictionary(identity) as query:
                status = self.security.SecItemDelete(query)
            if status != NOT_FOUND:
                self._check(status)
            return
        # Update first to retain the access control of an existing credential.
        password = {"kSecValueData": key.encode("utf-8")}
        with self._dictionary(identity) as query, self._dictionary(password) as changes:
            status = self.security.SecItemUpdate(query, changes)
        if status == NOT_FOUND:
            with self._dictionary({**identity, **password}) as query:
                status = self.security.SecItemAdd(query, None)
            if status == DUPLICATE_ITEM:
                # Another instance may have created it between update and add.
                with self._dictionary(identity) as query, self._dictionary(password) as changes:
                    status = self.security.SecItemUpdate(query, changes)
        self._check(status)


@lru_cache(maxsize=2)
def _keychain(account: str = ACCOUNT) -> Keychain:
    return Keychain(account)


def save_api_key(path: Path, key: str) -> None:
    _keychain("easyscholar-key" if path.name == "easyscholar-key.bin" else ACCOUNT).save(key)


def load_api_key(path: Path) -> str:
    return _keychain("easyscholar-key" if path.name == "easyscholar-key.bin" else ACCOUNT).load()
