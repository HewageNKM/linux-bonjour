use anyhow::Result;
// Note: tss-esapi usage requires careful handle management.

pub trait EncryptionProvider: Send + Sync {
    fn encrypt(&self, data: &[u8]) -> Result<Vec<u8>>;
    fn decrypt(&self, encrypted_data: &[u8]) -> Result<Vec<u8>>;
}

pub struct PlainProvider;

impl EncryptionProvider for PlainProvider {
    fn encrypt(&self, data: &[u8]) -> Result<Vec<u8>> {
        Ok(data.to_vec())
    }
    fn decrypt(&self, encrypted_data: &[u8]) -> Result<Vec<u8>> {
        Ok(encrypted_data.to_vec())
    }
}

pub struct SoftwareProvider {
    key: [u8; 32],
}

impl SoftwareProvider {
    pub fn new() -> Result<Self> {
        use std::fs;
        // Hardware bound to machine-id
        let machine_id = fs::read_to_string("/etc/machine-id")
            .unwrap_or_else(|_| "bonjour-fallback-hardware-id".to_string());
        
        // Derive key using SHA256 of machine-id
        use ring::digest;
        let hash = digest::digest(&digest::SHA256, machine_id.as_bytes());
        let mut key = [0u8; 32];
        key.copy_from_slice(hash.as_ref());
        
        Ok(Self { key })
    }
}

impl EncryptionProvider for SoftwareProvider {
    fn encrypt(&self, data: &[u8]) -> Result<Vec<u8>> {
        use ring::aead::{self, BoundKey, UnboundKey, Nonce, Aad, SealingKey};
        use ring::rand::{SystemRandom, SecureRandom};

        let rng = SystemRandom::new();
        let mut nonce_bytes = [0u8; 12];
        rng.fill(&mut nonce_bytes).map_err(|_| anyhow::anyhow!("Failed to generate random nonce"))?;

        let unbound_key = UnboundKey::new(&aead::CHACHA20_POLY1305, &self.key)
            .map_err(|_| anyhow::anyhow!("Failed count create unbound key"))?;
        
        let mut sealing_key = SealingKey::new(unbound_key, OneTimeNonce(Some(Nonce::assume_unique_for_key(nonce_bytes))));
        
        let mut in_out = data.to_vec();
        sealing_key.seal_in_place_append_tag(Aad::empty(), &mut in_out)
            .map_err(|_| anyhow::anyhow!("Encryption failed"))?;
        
        let mut final_result = nonce_bytes.to_vec();
        final_result.extend_from_slice(&in_out);
        Ok(final_result)
    }

    fn decrypt(&self, encrypted_data: &[u8]) -> Result<Vec<u8>> {
        use ring::aead::{self, BoundKey, UnboundKey, Nonce, Aad, OpeningKey};
        
        if encrypted_data.len() < 12 + 16 {
            anyhow::bail!("Invalid encrypted data: too short");
        }

        let (nonce_bytes, ciphertext) = encrypted_data.split_at(12);
        let mut nonce_arr = [0u8; 12];
        nonce_arr.copy_from_slice(nonce_bytes);

        let unbound_key = UnboundKey::new(&aead::CHACHA20_POLY1305, &self.key)
            .map_err(|_| anyhow::anyhow!("Failed count create unbound key"))?;
        
        let mut opening_key = OpeningKey::new(unbound_key, OneTimeNonce(Some(Nonce::assume_unique_for_key(nonce_arr))));
        
        let mut in_out = ciphertext.to_vec();
        let decrypted_data = opening_key.open_in_place(Aad::empty(), &mut in_out)
            .map_err(|_| anyhow::anyhow!("Decryption failed - possibly wrong key or corrupted data"))?;
        
        Ok(decrypted_data.to_vec())
    }
}

struct OneTimeNonce(Option<ring::aead::Nonce>);
impl ring::aead::NonceSequence for OneTimeNonce {
    fn advance(&mut self) -> std::result::Result<ring::aead::Nonce, ring::error::Unspecified> {
        self.0.take().ok_or(ring::error::Unspecified)
    }
}
