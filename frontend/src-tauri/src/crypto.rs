use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CryptoStatus {
    available: bool,
    protocol: &'static str,
    implementation: &'static str,
    reason: &'static str,
}

/// Reports capability only. No fallback cipher is allowed here: message sending
/// must remain blocked until the OpenMLS state machine is connected.
#[tauri::command]
pub fn crypto_status() -> CryptoStatus {
    CryptoStatus {
        available: false,
        protocol: "MLS 1.0",
        implementation: "OpenMLS 0.8.1",
        reason: "OpenMLS state is not initialized for this device",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unavailable_status_cannot_be_mistaken_for_e2ee() {
        let status = crypto_status();
        assert!(!status.available);
        assert_eq!(status.protocol, "MLS 1.0");
        assert_eq!(status.implementation, "OpenMLS 0.8.1");
    }
}
