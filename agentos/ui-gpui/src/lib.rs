//! Transport + model shared by the optional GPUI desktop surface.
//! A single read-only localhost endpoint is the source of truth for web and GPUI.
use serde::Deserialize;
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

const MAX_REPLY: u64 = 8 * 1024 * 1024;

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct Task {
    pub id: String,
    pub status: String,
    pub elapsed_s: f64,
    pub attempts: u32,
    pub error: String,
    pub stdout: String,
    pub stderr: String,
    pub filesystem_branch: String,
    pub filesystem_commit: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct TaskSpec {
    pub deps: Vec<String>,
    pub tenant: String,
    pub kind: String,
    pub cpu_units: u32,
    pub memory_mib: u64,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct Snapshot {
    pub total: usize,
    pub tasks: BTreeMap<String, Task>,
    pub dag: BTreeMap<String, TaskSpec>,
    pub counts: BTreeMap<String, u64>,
    pub declared_by: BTreeMap<String, String>,
    pub isolation: String,
}

pub fn parse_snapshot(body: &[u8]) -> Result<Snapshot, String> {
    if body.len() > MAX_REPLY as usize {
        return Err("snapshot exceeds 8 MiB".into());
    }
    let value: Snapshot = serde_json::from_slice(body).map_err(|e| e.to_string())?;
    if value.tasks.len() > 10000 {
        return Err("task count exceeds supported UI limit".into());
    }
    Ok(value)
}

/// Never connect to arbitrary hosts or paths: only the UI server on loopback.
pub fn fetch_local(port: u16) -> Result<Snapshot, String> {
    let endpoint = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&endpoint, Duration::from_secs(2))
        .map_err(|e| format!("localhost dashboard unavailable: {e}"))?;
    stream.set_read_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    stream.write_all(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nAccept: application/json\r\n\r\n")
        .map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    stream.take(MAX_REPLY + 4096).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    if bytes.len() as u64 >= MAX_REPLY + 4096 {
        return Err("HTTP response exceeds 8 MiB".into());
    }
    let separator = bytes.windows(4).position(|v| v == b"\r\n\r\n")
        .ok_or("invalid HTTP response")?;
    let headers = String::from_utf8_lossy(&bytes[..separator]);
    if !headers.starts_with("HTTP/1.1 200 ") && !headers.starts_with("HTTP/1.0 200 ") {
        return Err(format!("dashboard HTTP status: {}", headers.lines().next().unwrap_or("?")));
    }
    // Python ThreadingHTTPServer sends Content-Length and no chunked transfer.
    parse_snapshot(&bytes[separator + 4..])
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn parses_dynamic_dag_and_fc_metadata() {
        let state = parse_snapshot(br#"{
            "total":2,"tasks":{"a":{"id":"a","status":"succeeded",
            "filesystem_commit":"fc123","filesystem_branch":"ag-a-1"},
            "b":{"status":"running"}},
            "dag":{"b":{"deps":["a"],"kind":"tool","cpu_units":1}},
            "counts":{"running":1,"succeeded":1},
            "declared_by":{"b":"a"},"isolation":"layerfs"
        }"#).unwrap();
        assert_eq!(state.tasks["a"].filesystem_commit.as_deref(), Some("fc123"));
        assert_eq!(state.dag["b"].deps, vec!["a"]);
        assert_eq!(state.declared_by["b"], "a");
    }

    #[test]
    fn malformed_json_and_large_response_rejected() {
        assert!(parse_snapshot(b"{broken").is_err());
        assert!(parse_snapshot(&vec![b' '; MAX_REPLY as usize + 1]).is_err());
    }

    #[test]
    fn default_missing_fields_are_compatible() {
        let state = parse_snapshot(br#"{"tasks":{"single":{"status":"pending"}}}"#).unwrap();
        assert_eq!(state.tasks["single"].attempts, 0);
        assert!(state.dag.is_empty());
    }

    #[test]
    fn http_parser_consumes_real_local_response() {
        use std::net::TcpListener;
        use std::thread;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 1024];
            socket.read(&mut buffer).unwrap();
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 32\r\nConnection: close\r\n\r\n{\"total\":1,\"tasks\":{\"a\":{}}}").unwrap();
        });
        let state = fetch_local(port).unwrap();
        assert_eq!(state.tasks.len(), 1);
        handle.join().unwrap();
    }
}
