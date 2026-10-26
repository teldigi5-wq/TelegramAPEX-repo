'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const manifest = require('./package.json');

test('Electron is pinned to a release with the compromised intermediate certificate block', () => {
  assert.equal(manifest.devDependencies.electron, '44.9.1');
  const lockPath = path.join(__dirname, 'package-lock.json');
  assert.ok(fs.existsSync(lockPath), 'reproducible Electron lockfile must be committed');
  const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  assert.equal(lock.packages['node_modules/electron'].version, '44.9.1');
  assert.equal(lock.packages[''].devDependencies.electron, '44.9.1');
});
test('Desktop shell maintains an isolated renderer and does not expose native IPC', () => {
  const main = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
  assert.match(main, /contextIsolation:\s*true/);
  assert.match(main, /nodeIntegration:\s*false/);
  assert.match(main, /sandbox:\s*true/);
  assert.match(main, /appBackendNavigation/);
  assert.match(main, /setWindowOpenHandler/);
  const preload = fs.readFileSync(path.join(__dirname, 'preload.js'), 'utf8');
  assert.doesNotMatch(preload, /contextBridge\.exposeInMainWorld|ipcRenderer\.invoke/);
});
