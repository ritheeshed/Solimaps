/* Soli Maps sign-in settings, shared by the homepage and the map.
   Fill both to switch Google sign-in on. While either is empty, the homepage button opens the map directly. */
window.SOLI_AUTH = {
  clientId: '',   // Google Cloud > APIs & Services > Credentials > OAuth client ID (Web), ends in .apps.googleusercontent.com
  sheetUrl: 'https://script.google.com/macros/s/AKfycbzXMo_l75K6tUKWUFygM8o-mB36a36yODh8KHwMdFk2aRJnQs1IEOEEIENK8R7AKuIU/exec'    // Apps Script web-app URL from auth/apps-script.gs, ends in /exec
};
