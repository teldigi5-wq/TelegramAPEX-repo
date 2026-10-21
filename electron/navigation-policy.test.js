'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {safeWebLink,appBackendNavigation}=require('./navigation-policy');
test('external links only open ordinary web protocols',()=>{
 for(const item of ['https://github.com/example','http://example.org/'])assert.equal(safeWebLink(item),true);
 for(const item of ['file:///etc/passwd','javascript:alert(1)','data:text/html,hi','tel:1234','mailto:test@example.org','not a url'])assert.equal(safeWebLink(item),false);
});
test('desktop webview cannot navigate away from its exact loopback backend',()=>{
 assert.equal(appBackendNavigation('http://127.0.0.1:5005/?v=1',5005),true);
 for(const url of ['https://example.org','http://localhost:5005/','http://127.0.0.1:5006/','file:///etc/passwd','http://127.0.0.1:5005.evil.org/'])assert.equal(appBackendNavigation(url,5005),false);
});
