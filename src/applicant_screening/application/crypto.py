import base64
import hashlib
import hmac

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


def load_public_key_from_env(b64_pem: str) -> RSAPublicKey:
    pem_bytes = base64.b64decode(b64_pem)
    key = serialization.load_pem_public_key(pem_bytes)
    if not isinstance(key, RSAPublicKey):
        raise TypeError("Expected RSA public key")
    return key


def load_private_key_from_env(b64_pem: str) -> RSAPrivateKey:
    pem_bytes = base64.b64decode(b64_pem)
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise TypeError("Expected RSA private key")
    return key


def encrypt_field(value: str, public_key: RSAPublicKey) -> str:
    ciphertext = public_key.encrypt(
        value.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("utf-8")


def decrypt_field(encrypted_value: str, private_key: RSAPrivateKey) -> str:
    ciphertext = base64.b64decode(encrypted_value)
    plaintext = private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return plaintext.decode("utf-8")


def compute_blind_index(value: str, hmac_key: bytes) -> str:
    return hmac.new(hmac_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
