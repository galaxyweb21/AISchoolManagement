// static/js/global-handler.js
(function() {
    'use strict';

    // ============================================================
    // GLOBAL STATE
    // ============================================================
    const state = {
        messages: [],
        isProcessing: false,
        modalInstances: new Map()
    };

    // ============================================================
    // TOAST SYSTEM
    // ============================================================
    function createToastContainer() {
        let container = document.getElementById('toastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toastContainer';
            container.className = 'position-fixed top-0 end-0 p-3';
            container.style.zIndex = '9999';
            container.style.maxWidth = '400px';
            document.body.appendChild(container);
        }
        return container;
    }

    function showToast(message, type = 'success', duration = 4000) {
        const container = createToastContainer();
        const toastId = 'toast-' + Date.now() + '-' + Math.random().toString(36).substr(2, 4);

        const toast = document.createElement('div');
        toast.id = toastId;
        toast.className = `toast align-items-center border-0 shadow-lg rounded-4 show`;
        toast.role = 'alert';
        toast.ariaLive = 'assertive';
        toast.ariaAtomic = 'true';

        const config = {
            success: { bg: 'bg-success-subtle', icon: 'bi-check-circle-fill text-success', border: 'border-success' },
            error: { bg: 'bg-danger-subtle', icon: 'bi-exclamation-circle-fill text-danger', border: 'border-danger' },
            warning: { bg: 'bg-warning-subtle', icon: 'bi-exclamation-triangle-fill text-warning', border: 'border-warning' },
            info: { bg: 'bg-info-subtle', icon: 'bi-info-circle-fill text-info', border: 'border-info' }
        };

        const cfg = config[type] || config.info;

        toast.style.animation = 'slideInRight 0.4s ease';
        toast.innerHTML = `
            <div class="d-flex align-items-center p-2 ${cfg.bg} ${cfg.border} rounded-4">
                <div class="flex-shrink-0 ms-2">
                    <i class="bi ${cfg.icon} fs-4"></i>
                </div>
                <div class="flex-grow-1 ms-2 me-2">
                    <span class="fw-medium">${message}</span>
                </div>
                <button type="button" class="btn-close me-2" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;

        container.appendChild(toast);

        // Auto dismiss
        setTimeout(() => {
            const el = document.getElementById(toastId);
            if (el) {
                el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                el.style.opacity = '0';
                el.style.transform = 'translateX(20px)';
                setTimeout(() => {
                    if (el.parentNode) el.parentNode.removeChild(el);
                }, 300);
            }
        }, duration);
    }

    // ============================================================
    // MESSAGE HANDLER
    // ============================================================
    function handleMessages(messages) {
        if (!messages || messages.length === 0) return;

        messages.forEach(msg => {
            const type = msg.tags || 'info';
            const text = msg.message || msg;
            showToast(text, type);
        });
    }

    // ============================================================
    // AJAX FETCH WITH MESSAGE HANDLING
    // ============================================================
    function ajaxFetch(url, options = {}) {
        const defaultOptions = {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json'
            },
            credentials: 'same-origin'
        };

        const mergedOptions = {
            ...defaultOptions,
            ...options,
            headers: {
                ...defaultOptions.headers,
                ...(options.headers || {})
            }
        };

        // Add CSRF token
        const csrfToken = getCSRFToken();
        if (csrfToken) {
            mergedOptions.headers['X-CSRFToken'] = csrfToken;
        }

        return fetch(url, mergedOptions)
            .then(async response => {
                const contentType = response.headers.get('content-type');
                let data;

                if (contentType && contentType.includes('application/json')) {
                    data = await response.json();
                } else {
                    const text = await response.text();
                    try { data = JSON.parse(text); }
                    catch (e) { data = { success: response.ok, data: text }; }
                }

                // Handle messages from response
                if (data && data.messages) {
                    handleMessages(data.messages);
                }

                if (!response.ok) {
                    throw new Error(data.error || data.message || 'Request failed');
                }

                return data;
            });
    }

    // ============================================================
    // CSRF TOKEN HELPER
    // ============================================================
    function getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    }

    // ============================================================
    // MODAL HANDLER
    // ============================================================
    class GlobalModalHandler {
        constructor() {
            this.modals = new Map();
            this.init();
        }

        init() {
            // Setup on page load
            document.addEventListener('DOMContentLoaded', () => {
                this.setupModals();
            });

            // Setup when modal is shown
            document.addEventListener('shown.bs.modal', (e) => {
                const modal = e.target;
                if (modal.id && !this.modals.has(modal.id)) {
                    this.setupModal(modal.id);
                }
            });

            // Handle dynamic content
            document.addEventListener('modalContentLoaded', (e) => {
                if (e.detail && e.detail.modalId) {
                    this.setupModal(e.detail.modalId);
                }
            });
        }

        setupModals() {
            document.querySelectorAll('[data-modal-handler]').forEach(modal => {
                if (modal.id) this.setupModal(modal.id);
            });
        }

        setupModal(modalId) {
            const modal = document.getElementById(modalId);
            if (!modal || this.modals.has(modalId)) return;

            const form = modal.querySelector('form');
            if (!form) return;

            // Store config
            this.modals.set(modalId, {
                modal: modal,
                form: form,
                action: form.getAttribute('data-action') || 'update'
            });

            this.bindForm(modalId);
        }

        bindForm(modalId) {
            const config = this.modals.get(modalId);
            if (!config) return;

            const { modal, form } = config;

            // Clone to remove old listeners
            const newForm = form.cloneNode(true);
            form.parentNode.replaceChild(newForm, form);
            config.form = newForm;
            this.modals.set(modalId, config);

            newForm.addEventListener('submit', async (e) => {
                e.preventDefault();

                if (state.isProcessing) return;
                state.isProcessing = true;

                const submitBtn = newForm.querySelector('button[type="submit"]');
                const originalText = submitBtn?.innerHTML || 'Submit';

                // Disable button
                if (submitBtn) {
                    submitBtn.disabled = true;
                    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Processing...';
                }

                // Remove old errors
                newForm.querySelectorAll('.alert-danger').forEach(el => el.remove());

                try {
                    const formData = new FormData(newForm);
                    const data = await ajaxFetch(newForm.action, {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'Accept': 'application/json'
                        }
                    });

                    if (data.success) {
                        // Show success message
                        if (data.message) {
                            showToast(data.message, 'success');
                        }

                        // Close modal
                        const modalInstance = bootstrap.Modal.getInstance(modal);
                        if (modalInstance) modalInstance.hide();

                        // Dispatch events
                        document.dispatchEvent(new CustomEvent('modalSuccess', {
                            detail: {
                                modalId: modalId,
                                data: data,
                                action: config.action
                            }
                        }));

                        document.dispatchEvent(new CustomEvent('dataUpdated', {
                            detail: {
                                data: data,
                                action: config.action
                            }
                        }));

                    } else {
                        // Show error in modal
                        const errorMsg = data.error || data.message || 'An error occurred.';
                        showToast(errorMsg, 'error');

                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'alert alert-danger border-0 shadow-sm rounded-4 mb-3';
                        errorDiv.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i> ${errorMsg}`;
                        newForm.insertBefore(errorDiv, newForm.firstChild);
                    }

                } catch (err) {
                    console.error('Form submission error:', err);
                    showToast(err.message || 'An unexpected error occurred.', 'error');
                }

                // Re-enable button
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalText;
                }

                state.isProcessing = false;
            });
        }

        // Public method to register modal
        register(modalId, options = {}) {
            const modal = document.getElementById(modalId);
            if (!modal) return;

            if (!this.modals.has(modalId)) {
                this.setupModal(modalId);
            }

            const config = this.modals.get(modalId);
            if (config) {
                Object.assign(config, options);
                this.modals.set(modalId, config);
            }
        }
    }

    // ============================================================
    // TABLE UPDATER
    // ============================================================
    class GlobalTableUpdater {
        constructor() {
            this.init();
        }

        init() {
            document.addEventListener('dataUpdated', (e) => {
                this.handleUpdate(e.detail);
            });

            document.addEventListener('modalSuccess', (e) => {
                this.handleModalSuccess(e.detail);
            });
        }

        handleUpdate(detail) {
            const { data, action } = detail;
            const table = document.querySelector('[data-table-update]');

            // Most pages in this app were never annotated with the
            // data-table-update / data-id / data-field markup this partial
            // updater needs, so this used to just silently do nothing —
            // the modal would close having saved or deleted successfully,
            // but the page behind it stayed stale. Falling back to a full
            // reload guarantees every page reflects the change, while
            // pages that ARE properly annotated still get the smoother
            // no-reload partial update below.
            if (!table) {
                this.reloadPage();
                return;
            }

            const tbody = table.querySelector('tbody');
            if (!tbody) {
                this.reloadPage();
                return;
            }

            if (action === 'create' || action === 'add') {
                this.addRow(tbody, data);
            } else if (action === 'edit' || action === 'update') {
                this.updateRow(tbody, data);
            } else if (action === 'delete' || action === 'remove') {
                this.removeRow(tbody, data);
            } else if (action === 'reload') {
                this.reloadTable(table);
            }
        }

        reloadPage() {
            // Small delay so the just-shown success toast and modal-close
            // animation are visible before the page navigates away.
            setTimeout(() => window.location.reload(), 300);
        }

        handleModalSuccess(detail) {
            // NOTE: the actual add/update/remove work (and the reload
            // fallback for pages without data-table-update markup) is
            // done once, in handleUpdate() below, which runs off the
            // 'dataUpdated' event fired right after this one. This
            // handler used to duplicate that work here too, which meant
            // a single save could insert or highlight the same row
            // twice. All this does now is the highlight-flash polish for
            // rows that are already on screen and about to be updated.
            const { data, action } = detail;
            if (!data || !data.id) return;
            if (action !== 'edit' && action !== 'update') return;

            const table = document.querySelector('[data-table-update]');
            if (!table) return;

            const tbody = table.querySelector('tbody');
            if (!tbody) return;

            const row = tbody.querySelector(`[data-id="${data.id}"]`);
            if (!row) return;

            row.style.transition = 'background-color 0.5s ease';
            row.style.backgroundColor = 'rgba(13, 110, 253, 0.1)';
            setTimeout(() => {
                row.style.backgroundColor = '';
            }, 1000);
        }

        addRow(tbody, data) {
            // Remove empty state
            const emptyRow = tbody.querySelector('.empty-state-row');
            if (emptyRow) emptyRow.remove();

            // Use template if available
            const template = document.getElementById('rowTemplate');
            let row;

            if (template) {
                const content = template.content.cloneNode(true);
                row = content.querySelector('tr');
                if (row) {
                    this.updateRowContent(row, data);
                }
            }

            if (!row) {
                row = this.createRow(data);
            }

            if (row) {
                row.setAttribute('data-id', data.id);
                // Animation
                row.style.opacity = '0';
                row.style.transform = 'translateY(-20px)';
                tbody.prepend(row);
                requestAnimationFrame(() => {
                    row.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                    row.style.opacity = '1';
                    row.style.transform = 'translateY(0)';
                });
            }
        }

        updateRow(tbody, data) {
            const row = tbody.querySelector(`[data-id="${data.id}"]`);
            if (row) {
                this.updateRowContent(row, data);
            } else {
                // Table opted into partial updates but doesn't have a
                // matching row for this id (e.g. rows aren't annotated
                // with data-id, or ids don't line up) — fall back to a
                // full reload rather than silently leaving stale data.
                this.reloadPage();
            }
        }

        removeRow(tbody, data) {
            const row = tbody.querySelector(`[data-id="${data.id}"]`);
            if (row) {
                row.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                row.style.opacity = '0';
                row.style.transform = 'translateX(20px)';
                setTimeout(() => {
                    row.remove();
                    if (tbody.children.length === 0) {
                        this.showEmptyState(tbody);
                    }
                }, 300);
            } else {
                // Same fallback as updateRow — can't find the row to
                // remove, so reload instead of leaving a deleted item
                // still showing on screen.
                this.reloadPage();
            }
        }

        updateRowContent(row, data) {
            // Update by data-field attribute
            row.querySelectorAll('[data-field]').forEach(el => {
                const field = el.getAttribute('data-field');
                const value = data[field];

                if (value !== undefined) {
                    if (typeof value === 'boolean') {
                        el.innerHTML = value ?
                            '<span class="badge bg-success-subtle text-success">Yes</span>' :
                            '<span class="badge bg-secondary-subtle text-secondary">No</span>';
                    } else if (value === null || value === undefined) {
                        el.textContent = '—';
                    } else {
                        // Check if it's a badge or special element
                        if (el.querySelector('.badge')) {
                            el.textContent = value;
                        } else {
                            el.textContent = value;
                        }
                    }
                }
            });

            // Update data attributes
            for (const [key, value] of Object.entries(data)) {
                row.setAttribute(`data-${key}`, value);
            }
        }

        createRow(data) {
            const tr = document.createElement('tr');
            tr.setAttribute('data-id', data.id || '');

            // Create cells from data
            const fields = Object.keys(data);
            fields.forEach(key => {
                const td = document.createElement('td');
                td.setAttribute('data-field', key);
                td.textContent = data[key] || '—';
                tr.appendChild(td);
            });

            // Add actions cell
            const actionTd = document.createElement('td');
            actionTd.className = 'text-end';
            actionTd.innerHTML = `
                <button class="btn btn-sm btn-outline-primary view-btn">View</button>
                <button class="btn btn-sm btn-outline-secondary edit-btn">Edit</button>
                <button class="btn btn-sm btn-outline-danger delete-btn">Delete</button>
            `;
            tr.appendChild(actionTd);

            return tr;
        }

        showEmptyState(tbody) {
            const table = tbody.closest('table');
            const cols = table?.querySelector('thead tr')?.children?.length || 1;
            const row = document.createElement('tr');
            row.className = 'empty-state-row';
            row.innerHTML = `
                <td colspan="${cols}" class="text-center text-muted py-5">
                    <i class="bi bi-inbox fs-2 d-block mb-2 text-secondary"></i>
                    <p class="mb-0">No records found.</p>
                </td>
            `;
            tbody.appendChild(row);
        }

        reloadTable(table) {
            const url = table.getAttribute('data-reload-url');
            if (url) {
                ajaxFetch(url, { method: 'GET' })
                    .then(data => {
                        if (data.html) {
                            const temp = document.createElement('div');
                            temp.innerHTML = data.html;
                            const newTbody = temp.querySelector('tbody');
                            if (newTbody) {
                                const oldTbody = table.querySelector('tbody');
                                if (oldTbody) {
                                    oldTbody.innerHTML = newTbody.innerHTML;
                                }
                            }
                        }
                    })
                    .catch(err => console.error('Failed to reload table:', err));
            }
        }
    }

    // ============================================================
    // AUTO-DISMISS SERVER MESSAGES
    // ============================================================
    function autoDismissMessages() {
        document.querySelectorAll('.alert-dismissible').forEach(alert => {
            setTimeout(() => {
                const bsAlert = bootstrap.Alert.getInstance(alert);
                if (bsAlert) {
                    bsAlert.close();
                }
            }, 5000);
        });
    }

    // ============================================================
    // INITIALIZE
    // ============================================================
    document.addEventListener('DOMContentLoaded', function() {
        // Initialize handlers
        window.modalHandler = new GlobalModalHandler();
        window.tableUpdater = new GlobalTableUpdater();

        // Auto dismiss messages
        autoDismissMessages();

        // Make AJAX helpers globally available
        window.showToast = showToast;
        window.ajaxFetch = ajaxFetch;
        window.handleMessages = handleMessages;
        window.getCSRFToken = getCSRFToken;

        // Add CSS animations
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideInRight {
                0% { opacity: 0; transform: translateX(20px); }
                100% { opacity: 1; transform: translateX(0); }
            }
        `;
        document.head.appendChild(style);
    });

})();