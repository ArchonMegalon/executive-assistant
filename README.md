# 🫀 Matrix Vital Scanner (`matrix-health`)

Welcome to the **FUSE Enterprise Matrix**. You have successfully engineered a completely headless, zero-click, VPN-routed, TRaSH-aligned automation pipeline. 

To monitor this architecture without ever needing to open a web browser, the `matrix-health` CLI tool has been permanently forged into your Ubuntu system binaries.

## 🚀 How to Use It

Because it is a global command, you can run it from **anywhere** in your terminal. Simply type:

    matrix-health

## 📡 What It Monitors

The scanner bypasses traditional Docker container status checks and physically interrogates the live REST APIs of your .NET and C++ engines. It provides real-time telemetry across four distinct layers:

### 🛡️ Layer 1: The Kinetic Shield (Gluetun VPN)
* **What it does:** Verifies the tunnel is active and extracts your masked Exit Node IP.
* **What to look for:** `[ACTIVE]` and your masked Exit Node IP.

### ⚙️ Layer 2: The Engine (qBittorrent)
* **What it does:** Proves the C++ daemon is actively listening behind the VPN.
* **What to look for:** `[ONLINE]` and the current qBittorrent version.

### 🧠 Layer 3: The Cores (The Arrs)
* **What it does:** Interrogates the .NET System Health monitors for Sonarr, Radarr, Lidarr, Readarr, and Prowlarr.
* **What to look for:** `FLAWLESS (0 Errors, 0 Warnings)`.

### 👁️ Layer 4: The Neural Link (Overseerr)
* **What it does:** Pings the frontend API to ensure the user interface is online.
* **What to look for:** `[ONLINE] Overseerr is accepting user requests.`

---

## 🔐 Master Credentials

All core backend services (Sonarr, Radarr, Lidarr, Readarr, Prowlarr, qBittorrent) are permanently secured by:
* **Username:** tibor
* **Password:** rangersofB5

---

## EA OS Runtime Docs

This repository also carries EA OS design/runtime artifacts used by release gates:

- `EA OS (Assistant Runtime)` control-plane docs and smoke gates.
- `v1.20 commitment OS foundations` docs and runtime checks.
- runtime architecture includes `capability + skill registries`.
- `docs/EA_OS_Change_Guide_for_Dev_v1_21_Task_Contracts.md`
- `scripts/run_v120_smoke.sh`
- `scripts/run_v121_smoke.sh`
- `scripts/run_v122_smoke.sh`
- optional proactive lane: `docker compose --profile proactive up -d ea-proactive`
