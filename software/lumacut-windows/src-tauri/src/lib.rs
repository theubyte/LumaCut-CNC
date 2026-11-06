//! LumaCut Studio shell: Pi transport, system fonts, updater. All machine logic lives on the Pi;
//! all design logic in the frontend.
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{net::IpAddr, path::PathBuf, time::Duration};
use tauri::ipc::{InvokeBody, Request, Response};

const REPO: &str = "theubyte/LumaCut-CNC";
const RELEASE_PREFIX: &str = "windows-";

fn header(req: &Request, name: &str) -> String {
    req.headers().get(name).and_then(|v| v.to_str().ok()).unwrap_or("").to_string()
}

/// Only home-network addresses: this app never sends machine commands to the internet.
fn allowed_base(base: &str) -> Result<reqwest::Url, String> {
    let url = reqwest::Url::parse(base).map_err(|e| e.to_string())?;
    if url.scheme() != "http" {
        return Err("Nur http im Heimnetz".into());
    }
    let host = url.host_str().unwrap_or("").trim_matches(|c| c == '[' || c == ']').to_string();
    let ok = match host.parse::<IpAddr>() {
        Ok(IpAddr::V4(ip)) => ip.is_private() || ip.is_loopback() || ip.is_link_local(),
        Ok(IpAddr::V6(ip)) => ip.is_loopback(),
        Err(_) => host.ends_with(".local") || host == "localhost",
    };
    if ok { Ok(url) } else { Err(format!("Adresse {host} liegt nicht im Heimnetz")) }
}

#[tauri::command]
async fn pi_request(request: Request<'_>) -> Result<Response, String> {
    let base = allowed_base(&header(&request, "x-lc-base"))?;
    let method = reqwest::Method::from_bytes(header(&request, "x-lc-method").as_bytes()).map_err(|e| e.to_string())?;
    let path = header(&request, "x-lc-path");
    if !path.starts_with("/api/") {
        return Err("Nur /api/".into());
    }
    let timeout: u64 = header(&request, "x-lc-timeout").parse().unwrap_or(8000);
    let ctype = header(&request, "x-lc-ctype");
    let body = match request.body() {
        InvokeBody::Raw(b) => b.clone(),
        _ => Vec::new(),
    };

    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_millis(2500))
        .timeout(Duration::from_millis(timeout))
        .no_proxy()
        .build()
        .map_err(|e| e.to_string())?;
    let url = base.join(&path).map_err(|e| e.to_string())?;
    let mut rq = client.request(method, url);
    if !ctype.is_empty() {
        rq = rq.header("Content-Type", ctype);
    }
    if !body.is_empty() {
        rq = rq.body(body);
    }
    let r = rq.send().await.map_err(|e| {
        if e.is_timeout() {
            "Zeitüberschreitung".to_string()
        } else if e.is_connect() {
            "keine Verbindung".to_string()
        } else {
            e.to_string()
        }
    })?;
    let status = r.status().as_u16();
    let ct = r.headers().get("content-type").and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
    let bytes = r.bytes().await.map_err(|e| e.to_string())?;
    // Frame: u16 status, u16 content-type length, content-type, body. Raw bytes, so images stay fast.
    let mut out = Vec::with_capacity(4 + ct.len() + bytes.len());
    out.extend_from_slice(&status.to_le_bytes());
    out.extend_from_slice(&(ct.len() as u16).to_le_bytes());
    out.extend_from_slice(ct.as_bytes());
    out.extend_from_slice(&bytes);
    Ok(Response::new(out))
}

/// Test run of the installed app against the simulator: set LUMACUT_PI_URL before starting it.
#[tauri::command]
fn pi_url_override() -> Option<String> {
    std::env::var("LUMACUT_PI_URL").ok().filter(|s| !s.is_empty())
}

#[derive(Serialize)]
struct SystemFont {
    family: String,
    file: String,
    bold: bool,
    italic: bool,
}

fn font_dirs() -> Vec<PathBuf> {
    let mut dirs = vec![PathBuf::from(std::env::var("WINDIR").unwrap_or_else(|_| "C:\\Windows".into())).join("Fonts")];
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        dirs.push(PathBuf::from(local).join("Microsoft\\Windows\\Fonts"));
    }
    dirs
}

#[tauri::command]
async fn list_system_fonts() -> Result<Vec<SystemFont>, String> {
    let mut fonts = Vec::new();
    for dir in font_dirs() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase();
            if ext != "ttf" && ext != "otf" {
                continue;
            }
            let Ok(data) = std::fs::read(&path) else { continue };
            let Ok(face) = ttf_parser::Face::parse(&data, 0) else { continue };
            let family = face
                .names()
                .into_iter()
                .filter(|n| n.name_id == ttf_parser::name_id::TYPOGRAPHIC_FAMILY || n.name_id == ttf_parser::name_id::FAMILY)
                .find_map(|n| n.to_string());
            if let Some(family) = family {
                fonts.push(SystemFont { family, file: path.to_string_lossy().to_string(), bold: face.is_bold(), italic: face.is_italic() });
            }
        }
    }
    fonts.sort_by(|a, b| a.family.to_lowercase().cmp(&b.family.to_lowercase()));
    Ok(fonts)
}

#[tauri::command]
async fn read_system_font(file: String) -> Result<Response, String> {
    let path = PathBuf::from(&file);
    if !font_dirs().iter().any(|d| path.starts_with(d)) {
        return Err("Keine Schriftdatei".into());
    }
    std::fs::read(path).map(Response::new).map_err(|e| e.to_string())
}

// ---- Updates: pre-releases "windows-<version>" on GitHub with LumaCut-Studio.msi + .json. ----
// Marked pre-release so the Pi's /releases/latest (Android) never sees them.

#[derive(Serialize, Default)]
#[serde(rename_all = "camelCase")]
struct UpdateInfo {
    available: bool,
    current: String,
    version: Option<String>,
    notes: Option<String>,
    size_bytes: Option<u64>,
    error: Option<String>,
}

fn newer(a: &str, b: &str) -> bool {
    let parse = |s: &str| s.split('.').map(|p| p.parse::<u64>().unwrap_or(0)).collect::<Vec<_>>();
    parse(a) > parse(b)
}

fn http() -> Result<reqwest::Client, String> {
    reqwest::Client::builder().user_agent("LumaCut-Studio").connect_timeout(Duration::from_secs(8)).build().map_err(|e| e.to_string())
}

struct Latest {
    version: String,
    notes: String,
    msi_url: String,
    size: u64,
    sha256: String,
}

async fn fetch_json(client: &reqwest::Client, url: &str) -> Result<serde_json::Value, String> {
    client
        .get(url)
        .timeout(Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?
        .json()
        .await
        .map_err(|e| e.to_string())
}

async fn latest_release() -> Result<Option<Latest>, String> {
    let client = http()?;
    let list = fetch_json(&client, &format!("https://api.github.com/repos/{REPO}/releases?per_page=30")).await?;
    let Some(rel) = list.as_array().and_then(|l| l.iter().find(|r| r["tag_name"].as_str().unwrap_or("").starts_with(RELEASE_PREFIX))) else {
        return Ok(None);
    };
    let version = rel["tag_name"].as_str().unwrap_or("").trim_start_matches(RELEASE_PREFIX).to_string();
    let assets = rel["assets"].as_array().cloned().unwrap_or_default();
    let url_of = |name: &str| assets.iter().find(|a| a["name"] == name).and_then(|a| a["browser_download_url"].as_str()).map(String::from);
    let (Some(msi_url), Some(meta_url)) = (url_of("LumaCut-Studio.msi"), url_of("LumaCut-Studio.json")) else {
        return Ok(None);
    };
    let meta = fetch_json(&client, &meta_url).await?;
    Ok(Some(Latest {
        version,
        notes: rel["body"].as_str().unwrap_or("").to_string(),
        msi_url,
        size: meta["size"].as_u64().unwrap_or(0),
        sha256: meta["sha256"].as_str().unwrap_or("").to_lowercase(),
    }))
}

#[tauri::command]
async fn update_check(app: tauri::AppHandle) -> UpdateInfo {
    let current = app.package_info().version.to_string();
    match latest_release().await {
        Ok(Some(l)) if newer(&l.version, &current) => {
            UpdateInfo { available: true, current, version: Some(l.version), notes: Some(l.notes), size_bytes: Some(l.size), error: None }
        }
        Ok(_) => UpdateInfo { current, ..Default::default() },
        Err(e) => UpdateInfo { current, error: Some(e), ..Default::default() },
    }
}

#[tauri::command]
async fn update_install(app: tauri::AppHandle) -> Result<(), String> {
    let l = latest_release().await?.ok_or("Kein Update gefunden")?;
    if l.sha256.len() != 64 {
        return Err("Prüfsumme fehlt".into());
    }
    let bytes = http()?
        .get(&l.msi_url)
        .timeout(Duration::from_secs(600))
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?
        .bytes()
        .await
        .map_err(|e| e.to_string())?;
    let sum: String = Sha256::digest(&bytes).iter().map(|b| format!("{b:02x}")).collect();
    if sum != l.sha256 {
        return Err("Prüfsumme stimmt nicht, Update verworfen".into());
    }
    let path = std::env::temp_dir().join(format!("LumaCut-Studio-{}.msi", l.version));
    std::fs::write(&path, &bytes).map_err(|e| e.to_string())?;
    std::process::Command::new("msiexec").arg("/i").arg(&path).arg("/passive").spawn().map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![pi_request, pi_url_override, list_system_fonts, read_system_font, update_check, update_install])
        .run(tauri::generate_context!())
        .expect("LumaCut Studio konnte nicht starten");
}
