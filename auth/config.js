/* Soli Maps sign-in settings, shared by the homepage and the map.
   Fill both to switch Google sign-in on. While either is empty, the homepage button opens the map directly. */
window.SOLI_AUTH = {
  clientId: '',   // Google Cloud > APIs & Services > Credentials > OAuth client ID (Web), ends in .apps.googleusercontent.com
  sheetUrl: ''    // Apps Script web-app URL from auth/apps-script.gs, ends in /exec
};
