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

  function offerUpdate(registration) {
    if (!registration || !registration.waiting || !navigator.serviceWorker.controller) return;
    if (document.getElementById('eduaiPwaUpdateNotice')) return;
    var notice = document.createElement('div');
    notice.id = 'eduaiPwaUpdateNotice';
    notice.className = 'position-fixed bottom-0 start-50 translate-middle-x mb-3 p-3 shadow rounded-4 border';
    notice.style.cssText = 'z-index:1085;max-width:calc(100vw - 24px);background:var(--bs-body-bg);color:var(--bs-body-color);';
    notice.innerHTML = '<div class="d-flex align-items-center gap-3"><div><strong class="d-block">EduAI update available</strong><span class="small text-muted">Refresh when you are ready to use the latest version.</span></div><button type="button" class="btn btn-sm btn-primary" id="eduaiPwaUpdateButton">Update now</button><button type="button" class="btn-close" aria-label="Dismiss"></button></div>';
    document.body.appendChild(notice);
    notice.querySelector('.btn-close').addEventListener('click', function () { notice.remove(); });
    notice.querySelector('#eduaiPwaUpdateButton').addEventListener('click', function () {
      var button = this;
      button.disabled = true;
      button.textContent = 'Updating…';
      registration.waiting.postMessage({ type: 'EDUAI_SKIP_WAITING' });
    });
  }

  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/', updateViaCache: 'none' })
        .then(function (registration) {
          offerUpdate(registration);
          registration.addEventListener('updatefound', function () {
            var installing = registration.installing;
            if (!installing) return;
            installing.addEventListener('statechange', function () {
              if (installing.state === 'installed') offerUpdate(registration);
            });
          });
          // Ask the browser to check for a newer worker when the page is loaded.
          registration.update().catch(function () {});
        })
        .catch(function (error) { console.warn('EduAI service worker registration failed:', error); });
      var refreshing = false;
      navigator.serviceWorker.addEventListener('controllerchange', function () {
        if (refreshing) return;
        refreshing = true;
        window.location.reload();
      });
    });
  }
})();