(function () {
  'use strict';
  var deferredPrompt = null;
  var installButton = document.getElementById('eduaiInstallBtn');
  var isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true;

  function hideInstall() {
    if (installButton) installButton.classList.add('d-none');
  }
  function showInstall() {
    if (installButton && !isStandalone) installButton.classList.remove('d-none');
  }
  if (isStandalone) hideInstall();

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredPrompt = event;
    showInstall();
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    hideInstall();
  });

  if (installButton) {
    installButton.addEventListener('click', async function () {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        try {
          await deferredPrompt.userChoice;
        } catch (e) { /* Browser may dismiss the native prompt. */ }
        deferredPrompt = null;
        hideInstall();
        return;
      }
      // iOS Safari does not expose beforeinstallprompt. Show actionable instructions.
      var ios = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
      var message = ios
        ? 'To install EduAI: tap Share in Safari, then choose “Add to Home Screen”.'
        : 'If your browser supports installation, use its Install app option in the browser menu. Make sure you are using EduAI over HTTPS.';
      if (window.eduAIShowToast) window.eduAIShowToast(message, 'info');
      else window.alert(message);
    });
  }

  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
        .catch(function (error) { console.warn('EduAI service worker registration failed:', error); });
    });
  }
})();