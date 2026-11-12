// static/js/ajax-handler.js

(function() {
    'use strict';

    // ============================================================
    // GLOBAL AJAX MESSAGE HANDLER
    // ============================================================
    window.AJAXHandler = {
        // Show toast notification
        showToast: function(message, type) {
            const toastContainer = document.getElementById('toastContainer') || createToastContainer();
            const toastId = 'toast-' + Date.now();

            const toast = document.createElement('div');
            toast.id = toastId;
            toast.className = 'toast align-items-center border-0 shadow-sm rounded-4 show';
            toast.role = 'alert';
            toast.ariaLive = 'assertive';
            toast.ariaAtomic = 'true';

            const bgClass = type === 'success' ? 'bg-success-subtle' :
                           type === 'error' ? 'bg-danger-subtle' :
                           type === 'warning' ? 'bg-warning-subtle' : 'bg-info-subtle';

            const icon = type === 'success' ? 'bi-check-circle-fill text-success' :
                        type === 'error' ? 'bi-exclamation-circle-fill text-danger' :
                        type === 'warning' ? 'bi-exclamation-triangle-fill text-warning' :
                        'bi-info-circle-fill text-info';

            toast.innerHTML = `
                <div class="d-flex">
                    <div class="toast-body">
                        <i class="bi ${icon} me-2"></i>
                        ${message}
                    </div>
                    <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            `;

            toastContainer.appendChild(toast);

            // Auto dismiss after 4 seconds
            setTimeout(() => {
                const toastEl = document.getElementById(toastId);
                if (toastEl) {
                    const bsToast = bootstrap.Toast.getInstance(toastEl);
                    if (bsToast) {
                        bsToast.hide();
                    }
                    setTimeout(() => {
                        if (toastEl.parentNode) {
                            toastEl.parentNode.removeChild(toastEl);
                        }
                    }, 300);
                }
            }, 4000);
        },

        // Add a message to the messages container
        addMessage: function(message, type) {
            const container = document.getElementById('ajaxMessagesContainer');
            if (!container) return;

            // Remove old messages after 5 seconds
            const existingMessages = container.querySelectorAll('.alert');
            existingMessages.forEach(function(el) {
                setTimeout(function() {
                    const bsAlert = new bootstrap.Alert(el);
                    bsAlert.close();
                }, 5000);
            });

            const alertDiv = document.createElement('div');
            const alertClass = type === 'error' ? 'danger' :
                              type === 'warning' ? 'warning' :
                              type === 'success' ? 'success' : 'info';

            const icon = type === 'success' ? 'bi-check-circle-fill text-success' :
                        type === 'error' ? 'bi-exclamation-circle-fill text-danger' :
                        type === 'warning' ? 'bi-exclamation-triangle-fill text-warning' :
                        'bi-info-circle-fill text-info';

            alertDiv.className = `alert alert-${alertClass} border-0 shadow-sm rounded-4 alert-dismissible fade show mt-2`;
            alertDiv.role = 'alert';
            alertDiv.innerHTML = `
                <div class="d-flex align-items-center gap-2">
                    <i class="bi ${icon} fs-5"></i>
                    <span>${message}</span>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            `;

            container.prepend(alertDiv);

            // Auto dismiss after 5 seconds
            setTimeout(() => {
                if (alertDiv.parentNode) {
                    const bsAlert = new bootstrap.Alert(alertDiv);
                    bsAlert.close();
                }
            }, 5000);
        },

        // Handle AJAX response
        handleResponse: function(data, successCallback, errorCallback) {
            if (data.success) {
                if (data.message) {
                    this.showToast(data.message, 'success');
                    this.addMessage(data.message, 'success');
                }
                if (typeof successCallback === 'function') {
                    successCallback(data);
                }
                return true;
            } else {
                const errorMsg = data.error || data.message || 'An error occurred.';
                this.showToast(errorMsg, 'error');
                this.addMessage(errorMsg, 'error');
                if (typeof errorCallback === 'function') {
                    errorCallback(data);
                }
                return false;
            }
        }
    };

    // ============================================================
    // CREATE TOAST CONTAINER
    // ============================================================
    function createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }

    // ============================================================
    // AUTO-DISMISS MESSAGES ON PAGE LOAD
    // ============================================================
    document.addEventListener('DOMContentLoaded', function() {
        // Auto dismiss server-side messages after 5 seconds
        document.querySelectorAll('#ajaxMessagesContainer .alert-dismissible').forEach(function(alert) {
            setTimeout(function() {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }, 5000);
        });
    });

})();