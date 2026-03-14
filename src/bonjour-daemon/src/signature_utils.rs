use anyhow::{Context, Result};
use tracing::{info, warn, error, debug};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};
use crate::signature_vault::SignatureVault;

pub struct SignatureStore {
    vault: Arc<SignatureVault>,
    model_name: String,
    encryption: Arc<dyn crate::security_utils::EncryptionProvider>,
    cache: RwLock<HashMap<String, Vec<f32>>>,
}

impl SignatureStore {
    pub fn new(
        model_name: &str,
        vault: Arc<SignatureVault>,
        encryption: Arc<dyn crate::security_utils::EncryptionProvider>,
    ) -> Result<Self> {
        let store = Self {
            vault,
            model_name: model_name.to_string(),
            encryption,
            cache: RwLock::new(HashMap::new()),
        };

        // Trigger migration if needed
        store.migrate_legacy_files()?;
        store.populate_cache()?;

        Ok(store)
    }

    fn populate_cache(&self) -> Result<()> {
        let identities = self.vault.list_identities(&self.model_name)?;
        let mut cache = self.cache.write().map_err(|_| anyhow::anyhow!("Cache lock poisoned"))?;
        
        for (username, encrypted_blob) in identities {
            if let Ok(decrypted) = self.encryption.decrypt(&encrypted_blob) {
                let mut embedding = Vec::with_capacity(decrypted.len() / 4);
                for chunk in decrypted.chunks_exact(4) {
                    let bytes: [u8; 4] = chunk.try_into().unwrap();
                    embedding.push(f32::from_le_bytes(bytes));
                }
                cache.insert(username, embedding);
            }
        }
        
        info!("🧠 Population of signature cache complete ({} users).", cache.len());
        Ok(())
    }

    fn migrate_legacy_files(&self) -> Result<()> {
        let root_path = PathBuf::from("/var/lib/linux-bonjour/users");
        if !root_path.exists() { return Ok(()); }

        // 1. Migrate model-specific legacy files
        let model_legacy_path = root_path.join(&self.model_name);
        if model_legacy_path.exists() {
            info!("📂 Found legacy model storage at {:?}, migrating...", model_legacy_path);
            self.migrate_dir(&model_legacy_path)?;
        }

        // 2. Migrate top-level legacy files
        info!("📂 Checking for top-level legacy signatures...");
        self.migrate_dir(&root_path)?;

        Ok(())
    }

    fn migrate_dir(&self, path: &std::path::Path) -> Result<()> {
        if !path.is_dir() { return Ok(()); }
        
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let file_path = entry.path();
            if file_path.is_file() && file_path.extension().and_then(|s| s.to_str()) == Some("bin") {
                if let Some(username) = file_path.file_stem().and_then(|s| s.to_str()) {
                    info!("📦 Migrating legacy user: {}", username);
                    if let Ok(encrypted_data) = fs::read(&file_path) {
                        if self.vault.save_signature(username, &self.model_name, &encrypted_data).is_ok() {
                            let _ = fs::remove_file(file_path);
                        }
                    }
                }
            }
        }
        Ok(())
    }

    pub fn save_signature(&self, username: &str, embedding: &[f32]) -> Result<()> {
        let mut raw_data = Vec::with_capacity(embedding.len() * 4);
        for &val in embedding {
            raw_data.extend_from_slice(&val.to_le_bytes());
        }

        let encrypted_data = self
            .encryption
            .encrypt(&raw_data)
            .context("Encryption failed")?;
        
        self.vault.save_signature(username, &self.model_name, &encrypted_data)?;

        // Update cache
        if let Ok(mut cache) = self.cache.write() {
            cache.insert(username.to_string(), embedding.to_vec());
        }
        Ok(())
    }

    pub fn load_signature(&self, username: &str) -> Result<Vec<f32>> {
        // Check cache first
        if let Ok(cache) = self.cache.read() {
            if let Some(embedding) = cache.get(username) {
                return Ok(embedding.clone());
            }
        }

        // Check vault
        if let Some(encrypted) = self.vault.load_signature(username, &self.model_name)? {
            let data = self.encryption.decrypt(&encrypted).context("Decryption failed")?;
            let mut embedding = Vec::with_capacity(data.len() / 4);
            for chunk in data.chunks_exact(4) {
                let bytes: [u8; 4] = chunk.try_into().unwrap();
                embedding.push(f32::from_le_bytes(bytes));
            }
            
            // Populate cache
            if let Ok(mut cache) = self.cache.write() {
                cache.insert(username.to_string(), embedding.clone());
            }
            return Ok(embedding);
        }

        anyhow::bail!("Signature for user '{}' not found in vault", username)
    }

    pub fn list_identities(&self) -> Result<Vec<String>> {
        let identities = self.vault.list_identities(&self.model_name)?;
        Ok(identities.into_iter().map(|(u, _)| u).collect())
    }

    pub fn delete_identity(&self, username: &str) -> Result<()> {
        self.vault.delete_identity(username)?;
        // Invalidate cache
        if let Ok(mut cache) = self.cache.write() {
            cache.remove(username);
        }
        Ok(())
    }

    pub fn rename_identity(&self, old_name: &str, new_name: &str) -> Result<()> {
        if let Some(encrypted) = self.vault.load_signature(old_name, &self.model_name)? {
            self.vault.save_signature(new_name, &self.model_name, &encrypted)?;
            self.vault.delete_identity(old_name)?;
            
            // Update cache
            if let Ok(mut cache) = self.cache.write() {
                if let Some(emb) = cache.remove(old_name) {
                    cache.insert(new_name.to_string(), emb);
                }
            }
            Ok(())
        } else {
            anyhow::bail!("Identity not found")
        }
    }

    pub fn identify_user(
        &self,
        embedding: &[f32],
        threshold: f32,
    ) -> Result<Option<(String, f32)>> {
        let mut best_match: Option<(String, f32)> = None;
        let mut max_score = -1.0;

        // 1. Check all identities (this will populate cache if needed via load_signature)
        let identities = self.list_identities().unwrap_or_default();
        for id in identities {
            if let Ok(saved) = self.load_signature(&id) {
                let score = Self::cosine_similarity(embedding, &saved) as f32;
                if score > threshold && score > max_score {
                    max_score = score;
                    best_match = Some((id.to_string(), score));
                }
            }
        }

        Ok(best_match)
    }

    pub fn cosine_similarity(v1: &[f32], v2: &[f32]) -> f32 {
        if v1.len() != v2.len() {
            return 0.0;
        }

        let mut dot = 0.0;
        let mut n1 = 0.0;
        let mut n2 = 0.0;

        for i in 0..v1.len() {
            dot += v1[i] * v2[i];
            n1 += v1[i] * v1[i];
            n2 += v2[i] * v2[i];
        }

        dot / (n1.sqrt() * n2.sqrt())
    }
}
