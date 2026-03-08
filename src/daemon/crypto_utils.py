import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

# Static salt for key derivation (ideally this would be unique per machine but stable)
# We use a hash of the machine-id to make it machine-specific.
SALT_BASE = b"linux-bonjour-salt-v1"

def get_machine_id():
    """Retrieve a unique hardware-bound ID."""
    paths = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read().strip()
    return "fallback-id-not-secure"

def get_tpm_pubek():
    """Retrieve the TPM's Public Endorsement Key (EK) if available."""
    path = "/sys/class/tpm/tpm0/pubek"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except: pass
    return None

def derive_key(use_tpm=True):
    """Derive a 256-bit key from the machine-id and optionally the TPM PubEK."""
    machine_id = get_machine_id()
    tpm_ek = get_tpm_pubek() if use_tpm else None
    
    # Combine ingredients for the secret
    secret = machine_id
    if tpm_ek:
        secret += f"-tpm-{tpm_ek}"
    
    # Use a stable salt
    salt = hashlib.sha256(SALT_BASE + machine_id.encode()).digest()
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(secret.encode())

def encrypt_data(data: bytes) -> bytes:
    """Encrypt data using AES-GCM with the best available hardware-bound key."""
    # Always try to use TPM if it exists
    key = derive_key(use_tpm=True)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext

def decrypt_data(encrypted_data: bytes) -> bytes:
    """Decrypt data, trying TPM-bound key first, then machine-id-only fallback."""
    if len(encrypted_data) < 13:
        raise ValueError("Invalid encrypted data format")
    
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]

    # Step 1: Try the "best" available key (TPM-bound if TPM exists)
    try:
        key = derive_key(use_tpm=True)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        # Step 2: Fallback to machine-id only (if we haven't already tried it as the "best" above)
        if get_tpm_pubek(): # Only worth falling back if we actually used a TPM-bound key in Step 1
            try:
                key = derive_key(use_tpm=False)
                aesgcm = AESGCM(key)
                return aesgcm.decrypt(nonce, ciphertext, None)
            except: pass
        raise e
