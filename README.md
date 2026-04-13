# 🛰️ VezhaSFTP

![Version](https://img.shields.io/badge/version-1.0.0--stable-007acc?style=for-the-badge)
![Python](https://img.shields.io/badge/python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)
![Framework](https://img.shields.io/badge/framework-PyQt6-41cd52?style=for-the-badge&logo=qt&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-9e2a2b?style=for-the-badge)

**VezhaSFTP** is a professional-grade, lightweight SFTP client tailored for developers. It combines the power of the `paramiko` SSH engine with a sleek, high-performance **PyQt6** interface.

---

### 💎 The Experience

> *"Because managing remote servers shouldn't feel like a chore from the 90s."*

VezhaSFTP is built to be fast, dark, and dependable. It features a custom-engineered **QSS (Qt Style Sheet)** skin that mimics the aesthetics of modern IDEs like VS Code, ensuring that your eyes stay fresh even during midnight deployments.

---

### 🔥 Feature Showcase

* **⚡ Lightning Fast Navigation**
    Integrated `QFileSystemModel` for local browsing and a high-speed remote listing engine with smart sorting (directories always on top).
* **🖱️ Drag-and-Drop DNA**
    Fully implemented MIME-data handling. Grab a file from your OS file manager and drop it directly into the remote pane.
* **🧵 Threaded Execution**
    Zero UI freezing. All networking operations are offloaded to dedicated worker threads (`QThread`), ensuring 60fps interface responsiveness.
* **📊 Live Telemetry**
    A terminal-inspired log console coupled with real-time byte-calculation progress bars.
* **🛡️ Hardened Security**
    Native SSHv2 support with secure credential handling and session management.

---

### 🚀 Installation & Ignition

| Step | Action | Command |
| :--- | :--- | :--- |
| **1** | Clone the repository | `git clone https://github.com/vadronyx/VezhaSFTP.git` |
| **2** | Enter directory | `cd VezhaSFTP` |
| **3** | Install dependencies | `pip install PyQt6 paramiko` |
| **4** | Launch App | `python main.py` |

---

### 📦 Distribution Status

| Format | Status | Platform |
| :--- | :--- | :--- |
| **Native .deb** | ✅ Available | Debian / Ubuntu / Mint |
| **AppImage** | ⏳ In Progress | Universal Linux |
| **Standalone .exe** | ⏳ Planned | Windows 10/11 |
| **Source Code** | ✅ Available | Cross-platform |

---

### 🛠️ Roadmap to v2.0

- [ ] **Recursive Uploads:** Drag whole folders with nested structures.
- [ ] **Site Manager:** Save multiple server profiles with encrypted passwords.
- [ ] **Quick Search:** Filter files in the current directory in real-time.
- [ ] **Keep-Alive:** Automatic session restoration on timeout.

---

### 🤝 Contributing & Support

If you love the dark aesthetic and the speed of VezhaSFTP:
1. Give the project a ⭐ **Star**
2. Open an **Issue** if you find a bug
3. Submit a **Pull Request** to improve the code

**Developed with precision by [vadronyx](https://github.com/vadronyx)**
*Vezha — Your reliable tower in the world of remote servers.*
