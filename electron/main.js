"use strict";
/**
 * Electron main process for ScriptToVideo desktop app.
 *
 * Flow:
 *  1. Show a "Starting…" splash window immediately.
 *  2. Spawn the PyInstaller-bundled Python backend as a child process.
 *  3. Poll /health until the backend is ready (up to 60 s).
 *  4. Open the main browser window at http://127.0.0.1:8000/
 *  5. After main window is ready, silently check for updates on GitHub.
 *  6. On quit, kill the backend process.
 */

const { app, BrowserWindow, dialog, shell, Menu, ipcMain } = require("electron");
const { spawn }      = require("child_process");
const path           = require("path");
const http           = require("http");
const fs             = require("fs");
const { autoUpdater } = require("electron-updater");

let backendProcess = null;
let mainWindow     = null;
let splashWindow   = null;

// ── Port config ───────────────────────────────────────────────────────────────
// Packaged app uses 8765 to avoid conflicting with a dev server on 8000.
// Dev mode (npm start / NODE_ENV=development) uses 5173 (Vite) for the UI
// and 8000 for the backend.
const BACKEND_PORT = 8765;
const DEV_UI_URL   = "http://127.0.0.1:5173/";
const PROD_URL     = `http://127.0.0.1:${BACKEND_PORT}/`;

// ── Helpers ───────────────────────────────────────────────────────────────────

function isDev() {
  return !app.isPackaged || process.env.NODE_ENV === "development";
}

// ── Auto-updater ──────────────────────────────────────────────────────────────

/**
 * Configure electron-updater and kick off a silent background check.
 * Called once the main window is ready to show.
 */
function setupAutoUpdater() {
  if (isDev()) return; // never run updater in dev mode

  // Silent by default — we show our own dialogs
  autoUpdater.autoDownload    = false;
  autoUpdater.autoInstallOnAppQuit = true;

  // ── Update found → ask the user ─────────────────────────────────────────────
  autoUpdater.on("update-available", (info) => {
    dialog.showMessageBox(mainWindow, {
      type:    "info",
      title:   "Update Available",
      message: `ScriptToVideo ${info.version} is available`,
      detail:  `You are running ${app.getVersion()}.\n\nWould you like to download and install the update now? The app will restart automatically when complete.`,
      buttons: ["Download Update", "Later"],
      defaultId: 0,
      cancelId:  1,
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.downloadUpdate();
        // Show a progress notification
        if (mainWindow) {
          mainWindow.webContents.executeJavaScript(`
            (function() {
              const el = document.createElement("div");
              el.id = "stv-update-banner";
              el.style.cssText = "position:fixed;bottom:0;left:0;right:0;background:#6366f1;color:#fff;text-align:center;padding:10px 16px;font-family:sans-serif;font-size:13px;z-index:99999;";
              el.textContent = "⬇️  Downloading update… please wait.";
              document.body.appendChild(el);
            })()
          `).catch(() => {});
        }
      }
    });
  });

  // ── Download complete → prompt restart ──────────────────────────────────────
  autoUpdater.on("update-downloaded", (info) => {
    // Remove the download banner if present
    if (mainWindow) {
      mainWindow.webContents.executeJavaScript(`
        (function() {
          const el = document.getElementById("stv-update-banner");
          if (el) el.remove();
        })()
      `).catch(() => {});
    }

    dialog.showMessageBox(mainWindow, {
      type:    "info",
      title:   "Update Ready",
      message: `ScriptToVideo ${info.version} downloaded`,
      detail:  "The update has been downloaded. Restart the app now to install it.",
      buttons: ["Restart & Install", "Later"],
      defaultId: 0,
      cancelId:  1,
    }).then(({ response }) => {
      if (response === 0) {
        killBackend();
        setImmediate(() => autoUpdater.quitAndInstall());
      }
    });
  });

  // ── Already on latest ───────────────────────────────────────────────────────
  autoUpdater.on("update-not-available", () => {
    console.log("[updater] App is up to date.");
  });

  // ── Errors — log only, don't bother the user for network glitches ───────────
  autoUpdater.on("error", (err) => {
    console.error("[updater] Error:", err.message);
  });

  // Check now (silently — no dialog if already up to date)
  autoUpdater.checkForUpdates().catch((err) => {
    console.warn("[updater] checkForUpdates failed:", err.message);
  });

  // Also check once every 4 hours while the app is open
  setInterval(() => {
    autoUpdater.checkForUpdates().catch(() => {});
  }, 4 * 60 * 60 * 1000);
}

// Allow renderer to manually trigger an update check (Help → Check for Updates menu item)
ipcMain.handle("check-for-updates-manual", async () => {
  if (isDev()) {
    return { status: "dev" };
  }
  try {
    const result = await autoUpdater.checkForUpdates();
    return { status: "checked", version: result?.updateInfo?.version ?? null };
  } catch (err) {
    return { status: "error", message: err.message };
  }
});

/** Absolute path to the bundled backend executable. */
function getBackendExe() {
  const ext  = process.platform === "win32" ? ".exe" : "";
  const name = `scriptovideo-backend${ext}`;
  if (isDev()) {
    // In dev, the backend is already running via uvicorn — nothing to spawn.
    return null;
  }
  // electron-builder copies extraResources → <app>/resources/backend/
  return path.join(process.resourcesPath, "backend", name);
}

/** Path where user data (outputs, uploads, .env) is stored. */
function getUserDataPath() {
  return app.getPath("userData"); // e.g. %APPDATA%/ScriptToVideo
}

// ── Backend lifecycle ────────────────────────────────────────────────────────

function startBackend() {
  const exe = getBackendExe();
  if (!exe) {
    console.log("[electron] Dev mode — assuming backend is already running.");
    return;
  }
  if (!fs.existsSync(exe)) {
    dialog.showErrorBox(
      "Missing backend",
      `Backend executable not found:\n${exe}\n\nPlease reinstall the application.`
    );
    app.quit();
    return;
  }

  const userData = getUserDataPath();
  fs.mkdirSync(path.join(userData, "outputs", "audio"), { recursive: true });
  fs.mkdirSync(path.join(userData, "outputs", "video"), { recursive: true });
  fs.mkdirSync(path.join(userData, "uploads"),          { recursive: true });

  // Pass ffmpeg path via env var so startup.py can set it if needed
  const ffmpegDir  = path.join(process.resourcesPath, "ffmpeg");
  const ffmpegExt  = process.platform === "win32" ? ".exe" : "";
  const ffmpegBin  = path.join(ffmpegDir, `ffmpeg${ffmpegExt}`);

  const env = Object.assign({}, process.env, {
    AUDIO_OUTPUT_DIR:  path.join(userData, "outputs", "audio"),
    VIDEO_OUTPUT_DIR:  path.join(userData, "outputs", "video"),
    UPLOAD_DIR:        path.join(userData, "uploads"),
    FFMPEG_BINARY:     fs.existsSync(ffmpegBin) ? ffmpegBin : "ffmpeg",
    BACKEND_PORT:      String(BACKEND_PORT),  // tell startup.py which port to bind
  });

  console.log("[electron] Starting backend:", exe);
  backendProcess = spawn(exe, [], {
    cwd:    userData,
    env,
    stdio:  ["ignore", "pipe", "pipe"],
    detached: false,
  });

  // Write backend output to a log file in userData so crashes can be diagnosed
  const logPath = path.join(getUserDataPath(), "backend.log");
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  logStream.write(`\n\n=== Backend started ${new Date().toISOString()} ===\n`);

  let stderrBuf = "";
  backendProcess.stdout.on("data", (d) => {
    process.stdout.write(`[backend] ${d}`);
    logStream.write(d);
  });
  backendProcess.stderr.on("data", (d) => {
    process.stderr.write(`[backend] ${d}`);
    logStream.write(d);
    stderrBuf += d.toString();
    if (stderrBuf.length > 4000) stderrBuf = stderrBuf.slice(-4000);
  });
  backendProcess.on("exit", (code) => {
    logStream.end(`\n=== Backend exited code ${code} ===\n`);
    console.log(`[electron] Backend exited with code ${code}`);
    if (code !== 0 && mainWindow) {
      const detail = stderrBuf.trim()
        ? `Error output:\n${stderrBuf.trim().slice(-1500)}\n\nLog: ${logPath}`
        : `Log saved to: ${logPath}`;
      dialog.showErrorBox("Backend crashed", `The backend process exited unexpectedly (code ${code}).\n\n${detail}`);
    }
  });
}

/** Poll the backend /health endpoint until it returns 200 or timeout. */
function waitForBackend(maxAttempts = 60) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      const req = http.get(`http://127.0.0.1:${BACKEND_PORT}/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
      });
      req.on("error", retry);
      req.setTimeout(1000, () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (++attempts >= maxAttempts) {
        reject(new Error(`Backend did not start after ${maxAttempts} seconds.`));
      } else {
        setTimeout(check, 1000);
      }
    };
    check();
  });
}

function killBackend() {
  if (backendProcess && !backendProcess.killed) {
    console.log("[electron] Killing backend process…");
    backendProcess.kill("SIGTERM");
  }
}

// ── Windows ───────────────────────────────────────────────────────────────────

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420, height: 280,
    frame: false,
    transparent: false,
    alwaysOnTop: true,
    center: true,
    resizable: false,
    webPreferences: { nodeIntegration: false },
    backgroundColor: "#0f172a",
  });

  splashWindow.loadURL(`data:text/html;charset=utf-8,<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: #0f172a;
    color: #f1f5f9;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    height: 100vh; gap: 16px;
  }
  .icon  { font-size: 52px; }
  h1     { font-size: 24px; font-weight: 700; }
  p      { font-size: 13px; color: #94a3b8; }
  .dots  { display:flex; gap:6px; margin-top:8px; }
  .dot   {
    width:8px; height:8px; border-radius:50%;
    background:#6366f1; animation: pulse 1.2s infinite;
  }
  .dot:nth-child(2) { animation-delay:.2s; }
  .dot:nth-child(3) { animation-delay:.4s; }
  @keyframes pulse { 0%,80%,100%{opacity:.3} 40%{opacity:1} }
</style>
</head>
<body>
  <div class="icon">🎬</div>
  <h1>ScriptToVideo</h1>
  <p>Starting backend service…</p>
  <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
</body>
</html>`);
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: "ScriptToVideo",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      // Allow local audio/video blobs for the region editor
      webSecurity: true,
    },
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    backgroundColor: "#0f172a",
  });

  const url = isDev() ? DEV_UI_URL : PROD_URL;
  mainWindow.loadURL(url);

  mainWindow.once("ready-to-show", () => {
    splashWindow?.close();
    splashWindow = null;
    mainWindow.show();
    if (isDev()) mainWindow.webContents.openDevTools();
    // Start background update check ~3 seconds after the window appears
    setTimeout(setupAutoUpdater, 3000);
  });

  mainWindow.on("closed", () => { mainWindow = null; });

  // Open external links in the system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  buildMenu();
}

function buildMenu() {
  const userData = getUserDataPath();
  const template = [
    ...(process.platform === "darwin" ? [{ role: "appMenu" }] : []),
    {
      label: "File",
      submenu: [
        {
          label: "Open Outputs Folder",
          click: () => shell.openPath(path.join(userData, "outputs")),
        },
        {
          label: "Open Config (.env)",
          click: () => shell.openPath(path.join(userData, ".env")),
        },
        { type: "separator" },
        { role: process.platform === "darwin" ? "close" : "quit" },
      ],
    },
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Check for Updates…",
          click: async () => {
            if (isDev()) {
              dialog.showMessageBox(mainWindow, {
                type: "info", title: "Dev Mode",
                message: "Auto-update is disabled in development mode.",
                buttons: ["OK"],
              });
              return;
            }
            try {
              const result = await autoUpdater.checkForUpdates();
              const latest = result?.updateInfo?.version;
              const current = app.getVersion();
              if (latest && latest !== current) {
                // update-available event will fire and show download dialog
              } else {
                dialog.showMessageBox(mainWindow, {
                  type: "info", title: "No Updates",
                  message: `You're up to date!`,
                  detail: `ScriptToVideo ${current} is the latest version.`,
                  buttons: ["OK"],
                });
              }
            } catch (err) {
              dialog.showMessageBox(mainWindow, {
                type: "warning", title: "Update Check Failed",
                message: "Could not check for updates.",
                detail: err.message,
                buttons: ["OK"],
              });
            }
          },
        },
        { type: "separator" },
        {
          label: `Version ${app.getVersion()}`,
          enabled: false,
        },
        { type: "separator" },
        {
          label: "Open User Data Folder",
          click: () => shell.openPath(userData),
        },
        {
          label: "API Docs",
          click: () => shell.openExternal(`http://127.0.0.1:${BACKEND_PORT}/docs`),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  createSplash();
  startBackend();

  try {
    await waitForBackend(isDev() ? 10 : 60);
    createMainWindow();
  } catch (err) {
    killBackend();
    dialog.showErrorBox(
      "Startup Failed",
      `ScriptToVideo could not start:\n\n${err.message}\n\nCheck that no other app is using port ${BACKEND_PORT}.`
    );
    app.quit();
  }

  app.on("activate", () => {
    // macOS: re-create window when dock icon is clicked
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    killBackend();
    app.quit();
  }
});

app.on("before-quit", killBackend);
app.on("will-quit",   killBackend);
