//! Transport + model shared by the optional GPUI desktop surface.
//! A single read-only localhost endpoint is the source of truth for web and GPUI.
use serde::Deserialize;
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Read, Write};
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
    pub resource_metrics: serde_json::Value,
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
pub struct TaskDetail {
    pub task: Task,
    pub spec: TaskSpec,
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

/// Only the localhost read-only server is reachable: no redirects, proxies or DNS.
fn connect(port: u16, path: &str) -> Result<BufReader<TcpStream>, String> {
    let endpoint = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&endpoint, Duration::from_secs(2))
        .map_err(|e| format!("localhost dashboard unavailable: {e}"))?;
    stream.set_read_timeout(Some(Duration::from_secs(25))).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    let request = format!(
        "GET {path} HTTP/1.0\\r\\nHost: 127.0.0.1:{port}\\r\\nConnection: close\\r\\nAccept: application/json, text/event-stream\\r\\n\\r\\n"
    );
    stream.write_all(request.as_bytes()).map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).map_err(|e| e.to_string())?;
    if !line.starts_with("HTTP/1.1 200 ") && !line.starts_with("HTTP/1.0 200 ") {
        return Err(format!("dashboard HTTP status: {}", line.trim_end()));
    }
    loop {
        line.clear();
        reader.read_line(&mut line).map_err(|e| e.to_string())?;
        if line == "\\r\\n" || line == "\\n" {
            break;
        }
        if line.len() > 4096 {
            return Err("oversized HTTP header".into());
        }
        if line.is_empty() {
            return Err("incomplete HTTP header".into());
        }
    }
    Ok(reader)
}

fn get_local(port: u16, path: &str) -> Result<Vec<u8>, String> {
    let mut reader = connect(port, path)?;
    let mut bytes = Vec::new();
    reader.by_ref().take(MAX_REPLY + 1).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > MAX_REPLY {
        return Err("HTTP response exceeds 8 MiB".into());
    }
    Ok(bytes)
}

/// Fetch small task/status index, NOT stdout/stderr. Detail is lazy on selection.
pub fn fetch_local(port: u16) -> Result<Snapshot, String> {
    parse_snapshot(&get_local(port, "/api/state?view=summary")?)
}

pub fn fetch_task(port: u16, id: &str) -> Result<TaskDetail, String> {
    if id.is_empty() || id.len() > 64 ||
       !id.bytes().enumerate().all(|(i, b)| {
           if i == 0 { b.is_ascii_alphabetic() }
           else { b.is_ascii_alphanumeric() || b"_.-".contains(&b) }
       }) {
        return Err("invalid task ID".into());
    }
    serde_json::from_slice(&get_local(port, &format!("/api/task/{id}"))?)
        .map_err(|e| e.to_string())
}

/// Blocking long-lived event stream. Run ONLY on a worker thread. The closure
/// executes for server pushes, never on a timer. Comment heartbeats are ignored.
pub fn watch_local_changes<F: FnMut()>(port: u16, mut changed: F) -> Result<(), String> {
    let mut reader = connect(port, "/api/changes")?;
    let mut line = Vec::new();
    loop {
        line.clear();
        let bytes = reader.read_until(b'\\n', &mut line).map_err(|e| e.to_string())?;
        if bytes == 0 {
            return Err("SSE disconnected".into());
        }
        if line.len() > 256 {
            return Err("oversized SSE event".into());
        }
        if line.starts_with(b"data: ") {
            changed();
        }
    }
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
