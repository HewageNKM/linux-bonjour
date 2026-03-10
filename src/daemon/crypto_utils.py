import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

# Try to import TPM2.0 library
try:
    from tpm2_pytss import ESAPI, TPM2B_DIGEST
    HAS_TPM_LIB = True
except ImportError:
    HAS_TPM_LIB = False

def check_tpm_hardware():
    """Verify if TPM 2.0 hardware is actually accessible to avoid TCTI errors."""
    if not os.path.exists("/dev/tpm0"):
        return False
    # Check version if sysfs is available
    version_path = "/sys/class/tpm/tpm0/tpm_version_major"
    if os.path.exists(version_path):
        try:
            with open(version_path, "r") as f:
                version = f.read().strip()
                return version == "2"
        except:
            pass
    # If we can't determine version but tpmrm0 exists, it's likely TPM 2.0
    return os.path.exists("/dev/tpmrm0")

HAS_TPM_HARDWARE = check_tpm_hardware() if HAS_TPM_LIB else False

SALT_BASE = b"linux-bonjour-salt-v2"

def get_machine_id():
    """Retrieve a unique hardware-bound ID."""
    paths = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read().strip()
    return "fallback-id-not-secure"

def get_config():
    """Helper to load config for crypto settings."""
    import json
    try:
        paths = ["config/config.json", "/etc/linux-bonjour/config.json"]
        for p in paths:
            if os.path.exists(p):
                with open(p, "r") as f:
                    return json.load(f)
    except: pass
    return {}

def get_tpm_seed():
    """Generate a stable seed from the TPM2.0 using the Endorsement Hierarchy."""
    if not HAS_TPM_LIB or not HAS_TPM_HARDWARE:
        return None
    try:
        config = get_config()
        with ESAPI() as ectx:
            # Step 1: Get the EK (Endorsement Key) unique part as base seed
            cap = ectx.get_capability(0x00000006, 0x81010001, 1) # TPM_CAP_HANDLES
            base_seed = b""
            if cap and cap[1]: 
                handle = cap[1][0]
                public, _, _ = ectx.read_public(handle)
                base_seed = bytes(public.publicArea.unique.rsa)
            
            if not base_seed:
                return None

            # Step 2: Optionally bind to PCRs (Platform Configuration Registers)
            # PCR 0: BIOS / Firmware | PCR 7: Secure Boot State
            if config.get("tpm_pcr_binding", False):
                try:
                    # Select PCRs 0 and 7
                    pcr_selection = [
                        {"hash": 0x000B, "pcr": [0, 7]} # TPM_ALG_SHA256
                    ]
                    _, pcr_values = ectx.pcr_read(pcr_selection)
                    pcr_data = b"".join([v.buffer for v in pcr_values.digests])
                    base_seed += pcr_data
                except Exception as e:
                    # Log failure to bind PCRs but maybe fall back to base if risky
                    pass

            return hashlib.sha256(base_seed).digest()
    except Exception as e:
        pass
    return None

def derive_key(use_tpm=True):
    """Derive a 256-bit key from the machine-id and optionally the TPM seed."""
    machine_id = get_machine_id()
    tpm_seed = get_tpm_seed() if use_tpm else None
    
    # Combine ingredients for the secret
    secret = machine_id
    if tpm_seed:
        secret += f"-tpm-{tpm_seed.hex()}"
    
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
    # Try to use TPM if enabled and available
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
        # Step 2: Fallback to machine-id only (if TPM key failed or TPM not available)
        try:
            key = derive_key(use_tpm=False)
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(nonce, ciphertext, None)
        except:
            raise e
