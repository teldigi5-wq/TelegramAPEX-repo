'use strict';
function safeWebLink(raw) {
  try {
    const link = new URL(String(raw));
    return (link.protocol === 'https:' || link.protocol === 'http:') &&
      !link.username && !link.password;
  } catch { return false; }
}
function appBackendNavigation(raw, port) {
  try {
    const link = new URL(String(raw));
    const target = new URL('http://127.0.0.1:' + Number(port) + '/');
    return Number.isInteger(Number(port)) && Number(port) > 0 &&
      Number(port) <= 65535 && link.origin === target.origin &&
      !link.username && !link.password;
  } catch { return false; }
}
module.exports = { safeWebLink, appBackendNavigation };
