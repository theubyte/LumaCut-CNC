use std::{net::IpAddr, str::FromStr, time::Duration};

fn is_local_host(host: &str) -> bool {
    let parsed = IpAddr::from_str(host);
    match parsed {
        Ok(IpAddr::V4(ip)) => ip.is_private() || ip.is_loopback(),
        Ok(IpAddr::V6(ip)) => ip.is_unique_local() || ip.is_loopback(),
        Err(_) => false,
    }
}

fn pi_url(host: &str, path: &str) -> Result<String, String> {
    let host = host.trim();
    if !is_local_host(host) {
        return Err("Nur numerische lokale Pi-IP-Adressen sind zulässig".into());
    }
    Ok(match IpAddr::from_str(host).map_err(|e| e.to_string())? {
        IpAddr::V6(ip) => format!("http://[{}]:8080{}", ip, path),
        IpAddr::V4(ip) => format!("http://{}:8080{}", ip, path),
    })
}

fn pi_client(timeout_s: u64) -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(timeout_s))
        .redirect(reqwest::redirect::Policy::none())
        .build().map_err(|e| format!("Client: {e}"))
}

/// The Pi answers rejected actions with HTTP 4xx/5xx and {"error": "..."}.
/// Hand that German explanation to the UI instead of a bare status code.
async fn pi_json(result: reqwest::Response) -> Result<serde_json::Value, String> {
    let status = result.status();
    let data: serde_json::Value = result.json().await
        .map_err(|e| format!("Ungültige Pi-Antwort (HTTP {status}): {e}"))?;
    if !status.is_success() {
        let reason = data.get("error").and_then(|v| v.as_str()).unwrap_or("ohne Begründung");
        return Err(format!("Pi lehnt ab (HTTP {status}): {reason}"));
    }
    Ok(data)
}

/// Operations of the Pi /api/action endpoint that Studio may trigger.
/// Every safety rule (homing state, 30 mm safe zone, Z floor, laser
/// interlocks) stays on the Pi; Studio only asks for these actions.
const PI_ACTIONS: &[&str] = &[
    "home", "jog", "probe", "light", "exhaust", "start", "autorun", "abort", "estop",
];
const PI_FIELDS: &[&str] = &["axis", "distance", "on", "name", "x", "y"];

#[tauri::command]
async fn pi_action(
    host: String,
    op: String,
    fields: std::collections::HashMap<String, String>,
) -> Result<serde_json::Value, String> {
    if !PI_ACTIONS.contains(&op.as_str()) {
        return Err(format!("Aktion nicht freigegeben: {op}"));
    }
    let mut form: Vec<(String, String)> = vec![("op".into(), op.clone())];
    for (key, value) in fields {
        if !PI_FIELDS.contains(&key.as_str()) || value.len() > 120 {
            return Err(format!("Unzulässiges Feld: {key}"));
        }
        form.push((key, value));
    }
    // Homing and probing hold the HTTP request until the SKR finished.
    let timeout = if op == "home" || op == "probe" { 240 } else { 60 };
    let result = pi_client(timeout)?
        .post(pi_url(&host, "/api/action")?)
        .form(&form)
        .send().await.map_err(|e| format!("Pi nicht erreichbar: {e}"))?;
    pi_json(result).await
}

#[tauri::command]
async fn pi_upload_job(host: String, filename: String, gcode: String) -> Result<serde_json::Value, String> {
    let valid_name = !filename.is_empty() && filename.len() <= 80
        && filename.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
        && filename.to_ascii_lowercase().ends_with(".gcode");
    if !valid_name {
        return Err("Dateiname: nur A-Z, 0-9, - _ . und Endung .gcode".into());
    }
    if gcode.len() > 32 * 1024 * 1024 {
        return Err("Auftrag über 32 MB".into());
    }
    let part = reqwest::multipart::Part::text(gcode)
        .file_name(filename)
        .mime_str("text/plain").map_err(|e| e.to_string())?;
    let result = pi_client(120)?
        .post(pi_url(&host, "/api/upload")?)
        .multipart(reqwest::multipart::Form::new().part("file", part))
        .send().await.map_err(|e| format!("Pi nicht erreichbar: {e}"))?;
    pi_json(result).await
}

/// Pi 400 status bridge used by the machine panel.
#[tauri::command]
async fn read_pi_status(host: String) -> Result<serde_json::Value, String> {
    let url = pi_url(&host, "/api/status")?;
    let client = pi_client(5)?;
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
        "connected": data.get("connected"),
        "lights": data.get("lights"),
        "exhaust": data.get("exhaust"),
        "workpiece_surface_z": data.get("workpiece_surface_z"),
        "laser_focus_z": data.get("laser_focus_z"),
        "probe_xy_offset_mm": data.get("probe_xy_offset_mm"),
        "emergency_latched": data.get("emergency_latched"),
    }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![read_pi_status, pi_action, pi_upload_job])
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
