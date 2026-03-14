use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tracing::{info, warn, error};

pub struct SignatureVault {
    conn: Mutex<Connection>,
}

impl SignatureVault {
    pub fn new(db_path: &Path) -> Result<Self> {
        let conn = Connection::open(db_path)
            .with_context(|| format!("Failed to open database at {:?}", db_path))?;
        
        let vault = Self { conn: Mutex::new(conn) };
        vault.ensure_schema()?;
        Ok(vault)
    }

    fn ensure_schema(&self) -> Result<()> {
        let conn = self.conn.lock().map_err(|_| anyhow::anyhow!("DB Mutex poisoned"))?;
        conn.execute(
            "CREATE TABLE IF NOT EXISTS signatures (
                username TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (username, model_name)
            )",
            [],
        ).context("Failed to create signatures table")?;
        
        info!("🗄️ Signature Vault schema verified.");
        Ok(())
    }

    pub fn save_signature(&self, username: &str, model_name: &str, embedding: &[u8]) -> Result<()> {
        let conn = self.conn.lock().map_err(|_| anyhow::anyhow!("DB Mutex poisoned"))?;
        conn.execute(
            "INSERT OR REPLACE INTO signatures (username, model_name, embedding) VALUES (?1, ?2, ?3)",
            params![username, model_name, embedding],
        ).context("Failed to save signature to vault")?;
        Ok(())
    }

    pub fn load_signature(&self, username: &str, model_name: &str) -> Result<Option<Vec<u8>>> {
        let conn = self.conn.lock().map_err(|_| anyhow::anyhow!("DB Mutex poisoned"))?;
        let mut stmt = conn.prepare(
            "SELECT embedding FROM signatures WHERE username = ?1 AND model_name = ?2"
        )?;
        
        let mut rows = stmt.query(params![username, model_name])?;
        if let Some(row) = rows.next()? {
            let data: Vec<u8> = row.get(0)?;
            Ok(Some(data))
        } else {
            Ok(None)
        }
    }

    pub fn delete_identity(&self, username: &str) -> Result<()> {
        let conn = self.conn.lock().map_err(|_| anyhow::anyhow!("DB Mutex poisoned"))?;
        conn.execute(
            "DELETE FROM signatures WHERE username = ?1",
            params![username],
        ).context("Failed to delete identity from vault")?;
        Ok(())
    }

    pub fn list_identities(&self, model_name: &str) -> Result<Vec<(String, Vec<u8>)>> {
        let conn = self.conn.lock().map_err(|_| anyhow::anyhow!("DB Mutex poisoned"))?;
        let mut stmt = conn.prepare(
            "SELECT username, embedding FROM signatures WHERE model_name = ?1"
        )?;
        
        let rows = stmt.query_map(params![model_name], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row?);
        }
        Ok(results)
    }
}
