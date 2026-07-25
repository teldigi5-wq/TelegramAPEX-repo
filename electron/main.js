const { app, BrowserWindow, Menu, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const net = require('net');
const { spawn } = require('child_process');

let backendProc = null;
let win = null;
let backendPort = null;

// --- find a free local port --------------------------------------------------
function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

// --- locate the backend executable / script ----------------------------------
function resolveBackend() {
  if (app.isPackaged) {
    // Bundled via electron-builder's "extraResources" - see package.json.
    const exePath = path.join(process.resourcesPath, 'backend', 'TelegramAPEX_v10.exe');
    return { cmd: exePath, args: [] };
  }
  // Dev mode: run the Python script directly from the repo root.
  const scriptPath = path.join(__dirname, '..', 'TelegramAPEX_v9.py');
  const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
  return { cmd: pythonCmd, args: [scriptPath] };
}

// --- spawn the backend and wait for it to report ready -----------------------
function startBackend(port) {
  return new Promise((resolve, reject) => {
    const { cmd, args } = resolveBackend();
    const cwd = app.isPackaged
      ? path.join(process.resourcesPath, 'backend')
      : path.join(__dirname, '..');

    if (!fs.existsSync(cmd) && app.isPackaged) {
      reject(new Error(`Backend not found at ${cmd}. Did the build bundle it into resources/backend?`));
      return;
    }

    backendProc = spawn(cmd, args, {
      cwd,
      env: { ...process.env, APEX_PORT: String(port), APEX_HEADLESS: '1' },
      windowsHide: true,
    });

    let settled = false;
    const onData = (buf) => {
      const text = buf.toString();
      console.log('[backend]', text.trim());
      if (!settled && text.includes(`APEX_READY:${port}`)) {
        settled = true;
        resolve();
      }
    };
    backendProc.stdout.on('data', onData);
    backendProc.stderr.on('data', onData);

    backendProc.on('error', (err) => {
      if (!settled) { settled = true; reject(err); }
    });
    backendProc.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`);
      if (!settled) { settled = true; reject(new Error(`Backend exited early (code ${code})`)); }
    });

    // Fallback: even if we miss the exact ready line, give it a few seconds.
    setTimeout(() => { if (!settled) { settled = true; resolve(); } }, 8000);
  });
}

function stopBackend() {
  if (backendProc && !backendProc.killed) {
    if (process.platform === 'win32') {
      // Ensure the whole process tree (Flask thread lives in-process, but
      // be defensive in case PyInstaller spawns a child bootloader proc).
      spawn('taskkill', ['/pid', String(backendProc.pid), '/T', '/F']);
    } else {
      backendProc.kill('SIGTERM');
    }
    backendProc = null;
  }
}

async function createWindow() {
  try {
    backendPort = await findFreePort();
    await startBackend(backendPort);
  } catch (err) {
    dialog.showErrorBox('Telegram APEX - Backend failed to start', String(err));
    app.quit();
    return;
  }

  win = new BrowserWindow({
    width: 1580,
    height: 970,
    minWidth: 1000,
    minHeight: 640,
    backgroundColor: '#0b0f14',
    title: 'Telegram APEX',
    icon: path.join(__dirname, 'build', 'icon.png'),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  Menu.setApplicationMenu(null);
  win.loadURL(`http://127.0.0.1:${backendPort}/`);

  // Open any target="_blank" links (e.g. GitHub release links) in the
  // system browser instead of a new Electron window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  win.on('closed', () => { win = null; });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', stopBackend);

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
