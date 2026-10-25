use std::{net::IpAddr, str::FromStr, time::Duration};

fn is_local_host(host: &str) -> bool {
    let parsed = IpAddr::from_str(host);
    match parsed {
        Ok(IpAddr::V4(ip)) => ip.is_private() || ip.is_loopback(),
        Ok(IpAddr::V6(ip)) => ip.is_unique_local() || ip.is_loopback(),
        Err(_) => false,
    }
}

/// Read-only Pi 400 status bridge. This never takes serial ownership,
/// triggers homing, enables PWM, or starts a laser job.
#[tauri::command]
async fn read_pi_status(host: String) -> Result<serde_json::Value, String> {
    let host = host.trim();
    if !is_local_host(host) {
        return Err("Nur numerische lokale Pi-IP-Adressen sind zulässig".into());
    }
    let url = match IpAddr::from_str(host).map_err(|e| e.to_string())? {
        IpAddr::V6(ip) => format!("http://[{}]:8080/api/status", ip),
        IpAddr::V4(ip) => format!("http://{}:8080/api/status", ip),
    };
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .redirect(reqwest::redirect::Policy::none())
        .build().map_err(|e| format!("Client: {e}"))?;
    let result = client.get(url).send().await.map_err(|e| format!("Pi nicht erreichbar: {e}"))?;
    if !result.status().is_success() {
        return Err(format!("Pi antwortet mit HTTP {}", result.status()));
    }
    let data: serde_json::Value = result.json().await
        .map_err(|e| format!("Ungültige Pi-Statusantwort: {e}"))?;
    if data.get("firmware").and_then(|v| v.as_str()) != Some("marlin") {
        return Err("Der Server meldet nicht die erwartete LumaCut-Marlin-Firmware".into());
    }
    let job = data.get("job").cloned().unwrap_or(serde_json::Value::Null);
    Ok(serde_json::json!({
        "firmware": "marlin",
        "state": data.get("state"),
        "homed": data.get("homed"),
        "position": data.get("position"),
        "owner": data.get("owner"),
        "fault": data.get("fault"),
        "job": job,
        "focus_gap_mm": data.pointer("/config/focus_gap_mm"),
        "validated": data.pointer("/config/validated"),
    }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![read_pi_status])
        .run(tauri::generate_context!())
        .expect("failed to run LumaCut Studio");
}

#[cfg(test)]
mod tests {
    use super::is_local_host;
    #[test]
    fn only_private_or_loopback_ip_literal_is_accepted() {
        assert!(is_local_host("192.168.2.10"));
        assert!(is_local_host("10.0.0.8"));
        assert!(is_local_host("127.0.0.1"));
        assert!(!is_local_host("1.1.1.1"));
        assert!(!is_local_host("example.com"));
        assert!(!is_local_host("192.168.2.10:8080"));
    }
}
