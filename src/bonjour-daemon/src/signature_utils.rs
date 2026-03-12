use anyhow::{Context, Result};
use std::fs;
use std::path::PathBuf;

pub struct SignatureStore {
    base_path: PathBuf,
    encryption: std::sync::Arc<dyn crate::security_utils::EncryptionProvider>,
}

impl SignatureStore {
    pub fn new(
        model_name: &str,
        encryption: std::sync::Arc<dyn crate::security_utils::EncryptionProvider>,
    ) -> Result<Self> {
        let base_path = PathBuf::from("/var/lib/linux-bonjour")
            .join("users")
            .join(model_name);

        if !base_path.exists() {
            fs::create_dir_all(&base_path).context("Failed to create signature directory")?;
        }

        Ok(Self {
            base_path,
            encryption,
        })
    }

    pub fn save_signature(&self, username: &str, embedding: &[f32]) -> Result<()> {
        let file_path = self.base_path.join(format!("{}.bin", username));
        let mut raw_data = Vec::with_capacity(embedding.len() * 4);
        for &val in embedding {
            raw_data.extend_from_slice(&val.to_le_bytes());
        }

        let encrypted_data = self
            .encryption
            .encrypt(&raw_data)
            .context("Encryption failed")?;
        fs::write(file_path, encrypted_data).context("Failed to save signature file")?;
        Ok(())
    }

    pub fn load_signature(&self, username: &str) -> Result<Vec<f32>> {
        let bin_path = self.base_path.join(format!("{}.bin", username));

        // 1. Try modern model-specific path
        if bin_path.exists() {
            return self.read_and_decrypt(&bin_path);
        }

        // 2. Fallback to legacy path (top-level users/ folder)
        let legacy_path = PathBuf::from("/var/lib/linux-bonjour")
            .join("users")
            .join(format!("{}.bin", username));

        if legacy_path.exists() {
            println!("📂 Legacy signature found for {}, migrating...", username);
            let embedding = self.read_and_decrypt(&legacy_path)?;

            // Auto-migrate to new path
            if let Ok(encrypted_data) = fs::read(&legacy_path) {
                if let Ok(_) = fs::write(&bin_path, encrypted_data) {
                    let _ = fs::remove_file(&legacy_path);
                    println!(
                        "✅ Successfully migrated {} to model-specific storage.",
                        username
                    );
                }
            }
            return Ok(embedding);
        }

        anyhow::bail!(
            "Signature for user '{}' not found in current model or legacy store",
            username
        )
    }

    fn read_and_decrypt(&self, path: &PathBuf) -> Result<Vec<f32>> {
        let encrypted_data = fs::read(path).context("Failed to read signature file")?;
        let data = self
            .encryption
            .decrypt(&encrypted_data)
            .context("Decryption failed")?;

        let mut embedding = Vec::with_capacity(data.len() / 4);
        for chunk in data.chunks_exact(4) {
            let bytes: [u8; 4] = chunk.try_into().unwrap();
            embedding.push(f32::from_le_bytes(bytes));
        }
        Ok(embedding)
    }

    pub fn list_identities(&self) -> Result<Vec<String>> {
        let mut users = Vec::new();
        if self.base_path.exists() {
            for entry in fs::read_dir(&self.base_path)? {
                let entry = entry?;
                let path = entry.path();
                if path.extension().and_then(|s| s.to_str()) == Some("bin") {
                    if let Some(name) = path.file_stem().and_then(|s| s.to_str()) {
                        users.push(name.to_string());
                    }
                }
            }
        }
        Ok(users)
    }

    pub fn delete_identity(&self, username: &str) -> Result<()> {
        let file_path = self.base_path.join(format!("{}.bin", username));
        if file_path.exists() {
            fs::remove_file(file_path)?;
            Ok(())
        } else {
            anyhow::bail!("Identity not found")
        }
    }

    pub fn rename_identity(&self, old_name: &str, new_name: &str) -> Result<()> {
        let old_path = self.base_path.join(format!("{}.bin", old_name));
        let new_path = self.base_path.join(format!("{}.bin", new_name));
        if !old_path.exists() {
            anyhow::bail!("Identity '{}' not found", old_name);
        }
        if new_path.exists() {
            anyhow::bail!("Identity '{}' already exists", new_name);
        }
        fs::rename(old_path, new_path).context("Failed to rename signature file")?;
        Ok(())
    }

    pub fn identify_user(
        &self,
        embedding: &[f32],
        threshold: f32,
    ) -> Result<Option<(String, f32)>> {
        let mut best_match = None;
        let mut max_score = -1.0;

        // 1. Check all identities in current model folder
        let users = self.list_identities().unwrap_or_default();
        for user in users {
            if let Ok(saved) = self.load_signature(&user) {
                let score = Self::cosine_similarity(embedding, &saved);
                if score > threshold && score > max_score {
                    max_score = score;
                    best_match = Some((user, score));
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
