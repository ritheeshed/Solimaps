/**
 * Soli Maps sign-ins, waitlist and company requests -> this Google Sheet.
 * The waitlist (waitlist/ page) only needs step 1, 3 and 4: paste the /exec URL into auth/config.js as sheetUrl.
 *
 * Setup (one time, free):
 * 1. Create a Google Sheet (any name). Extensions > Apps Script. Delete what is there and paste this whole file.
 * 2. Put your OAuth client ID below (the same one that goes into SOLI_AUTH.clientId in index.html).
 * 3. Deploy > New deployment > type "Web app". Execute as: Me. Who has access: Anyone. Deploy, allow access.
 * 4. Copy the Web app URL (ends in /exec). That is SOLI_AUTH.sheetUrl in index.html.
 *
 * Only Google-verified sign-ins for this client ID are saved. Each person gets one row.
 */
const CLIENT_ID = 'PASTE-YOUR-CLIENT-ID.apps.googleusercontent.com';
const TAB = 'Users';
const HEAD = ['First seen', 'Last seen', 'Name', 'Email', 'Visits', 'Language', 'UTM source', 'UTM medium', 'UTM campaign', 'Came from', 'Key'];

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(TAB);
  if (!sh) {
    sh = ss.insertSheet(TAB);
    sh.appendRow(HEAD);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEAD.length).setFontWeight('bold');
    sh.hideColumns(HEAD.length); // the key column is only for matching visits and deletes
  }
  return sh;
}

function rowOf_(sh, email) {
  const last = sh.getLastRow();
  if (last < 2) return 0;
  const emails = sh.getRange(2, 4, last - 1, 1).getValues();
  for (let i = 0; i < emails.length; i++) if (String(emails[i][0]).toLowerCase() === email.toLowerCase()) return i + 2;
  return 0;
}

function verify_(credential) {
  const r = UrlFetchApp.fetch('https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(credential), { muteHttpExceptions: true });
  if (r.getResponseCode() !== 200) return null;
  const t = JSON.parse(r.getContentText());
  if (t.aud !== CLIENT_ID || String(t.email_verified) !== 'true') return null;
  if (['accounts.google.com', 'https://accounts.google.com'].indexOf(t.iss) < 0) return null;
  return t;
}

function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function clip_(v, n) { return String(v || '').slice(0, n || 200); }

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false }); }
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = sheet_();
    const now = new Date();
    if (body.action === 'signin') {
      const t = verify_(body.credential);
      if (!t) return out_({ ok: false });
      const r = rowOf_(sh, t.email);
      if (r) {
        const visits = Number(sh.getRange(r, 5).getValue() || 0) + 1;
        sh.getRange(r, 2).setValue(now);
        sh.getRange(r, 3).setValue(clip_(t.name));
        sh.getRange(r, 5).setValue(visits);
        sh.getRange(r, 11).setValue(clip_(body.key, 64));
      } else {
        sh.appendRow([now, now, clip_(t.name), t.email, 1, clip_(body.lang, 5), clip_(body.utm_source), clip_(body.utm_medium), clip_(body.utm_campaign), clip_(body.ref), clip_(body.key, 64)]);
      }
      return out_({ ok: true });
    }
    if (body.action === 'seen' || body.action === 'delete') {
      const r = rowOf_(sh, clip_(body.email));
      if (!r || !body.key || sh.getRange(r, 11).getValue() !== body.key) return out_({ ok: false });
      if (body.action === 'delete') sh.deleteRow(r);
      else { sh.getRange(r, 2).setValue(now); sh.getRange(r, 5).setValue(Number(sh.getRange(r, 5).getValue() || 0) + 1); }
      return out_({ ok: true });
    }
    if (body.action === 'waitlist') {
      const email = clip_(body.email, 120).trim().toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return out_({ ok: false });
      const wa = clip_(body.whatsapp, 10).replace(/\D/g, '');
      if (wa && !/^[6-9]\d{9}$/.test(wa)) return out_({ ok: false });
      const ss = SpreadsheetApp.getActiveSpreadsheet();
      const WH = ['Joined', 'Email', 'WhatsApp', 'Area', 'Role', 'Language', 'UTM source', 'UTM medium', 'UTM campaign', 'UTM content', 'Came from', 'Updated'];
      let ws = ss.getSheetByName('Waitlist');
      if (!ws) { ws = ss.insertSheet('Waitlist'); ws.appendRow(WH); ws.setFrozenRows(1); ws.getRange(1, 1, 1, WH.length).setFontWeight('bold'); ws.getRange('C:C').setNumberFormat('@'); }
      const last = ws.getLastRow();
      if (last >= 2) {
        const emails = ws.getRange(2, 2, last - 1, 1).getValues();
        for (let i = 0; i < emails.length; i++) {
          if (String(emails[i][0]).toLowerCase() === email) {
            const r = i + 2;
            if (wa) ws.getRange(r, 3).setValue(wa);
            ws.getRange(r, 4, 1, 2).setValues([[clip_(body.area, 40), clip_(body.role, 40)]]);
            ws.getRange(r, 12).setValue(now);
            return out_({ ok: true, n: i + 1 });
          }
        }
      }
      ws.appendRow([now, email, wa, clip_(body.area, 40), clip_(body.role, 40), clip_(body.lang, 5), clip_(body.utm_source, 80), clip_(body.utm_medium, 80), clip_(body.utm_campaign, 80), clip_(body.utm_content, 80), clip_(body.ref), now]);
      return out_({ ok: true, n: Math.max(1, ws.getLastRow() - 1) });
    }
    if (body.action === 'company') {
      const company = clip_(body.company, 80), careers = clip_(body.careers, 200), email = clip_(body.email, 120);
      if (!company || !/^https?:\/\//.test(careers) || !/^\S+@\S+\.\S+$/.test(email)) return out_({ ok: false });
      const ss = SpreadsheetApp.getActiveSpreadsheet();
      let cs = ss.getSheetByName('Companies');
      if (!cs) { cs = ss.insertSheet('Companies'); cs.appendRow(['Sent', 'Company', 'Careers page', 'Work email', 'Language']); cs.setFrozenRows(1); cs.getRange(1, 1, 1, 5).setFontWeight('bold'); }
      cs.appendRow([now, company, careers, email, clip_(body.lang, 5)]);
      return out_({ ok: true });
    }
    return out_({ ok: false });
  } finally {
    lock.releaseLock();
  }
}

function doGet() { return out_({ ok: true, service: 'Soli Maps sign-ins and waitlist' }); }
