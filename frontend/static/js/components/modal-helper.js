class ModalHelper {
    constructor(options = {}) {
        const modalId = options.id || 'modal-helper';
        this.options = {
            id: modalId,
            type: options.type || 'info', // 'info', 'warning', 'danger'
            title: options.title || this.getDefaultTitle(options.type),
            message: options.message || '',
            showIcon: options.showIcon !== false,
            confirmText: options.confirmText || window.i18n.t('common.yes'),
            cancelText: options.cancelText || window.i18n.t('common.no'),
            confirmId: options.confirmId || `${modalId}-confirm-yes`,
            cancelId: options.cancelId || `${modalId}-confirm-no`,
            onConfirm: options.onConfirm || null,
            onCancel: options.onCancel || null,
            blurTarget: options.blurTarget || null, // CSS selector for element to blur
            closeOnEscape: options.closeOnEscape !== false,
            closeOnOutsideClick: options.closeOnOutsideClick !== false,
            ...options
        };

        this.modalElement = null;
        this.isVisible = false;
        this._escapeHandler = null;

        this.init();
    }

    init() {
        this.createModal();
        this.setupEventListeners();
    }

    getDefaultTitle(type) {
        const titles = {
            primary: window.i18n.t('common.info'),
            info: window.i18n.t('common.info'),
            warning: window.i18n.t('common.warning'),
            danger: window.i18n.t('common.explicit_content_warning')
        };
        return titles[type] || window.i18n.t('common.info');
    }

    getIconSVG(type) {
        const icons = {
            primary: window.Icons.primary({ class: 'mx-auto mb-4 text-primary' }),
            info: window.Icons.info({ class: 'mx-auto mb-4 text-info' }),
            warning: window.Icons.warning({ class: 'mx-auto mb-4 text-warning' }),
            danger: window.Icons.danger({ class: 'mx-auto mb-4 text-danger' })
        };
        return icons[type] || icons.info;
    }

    getTitleClass(type) {
        const classes = {
            primary: 'text-primary',
            info: 'text-info',
            warning: 'text-warning',
            danger: 'text-danger'
        };
        return classes[type] || classes.info;
    }

    getBorderClass(type) {
        const classes = {
            primary: 'border-primary',
            info: 'border-info',
            warning: 'border-warning',
            danger: 'border-danger'
        };
        return classes[type] || classes.info;
    }

    getConfirmButtonClass(type) {
        const classes = {
            primary: 'btn-primary',
            info: 'bg-info hover:bg-info tag-text',
            warning: 'bg-warning hover:bg-warning tag-text',
            danger: 'btn-danger'
        };
        return classes[type] || classes.info;
    }

    getCancelButtonClass() {
        return 'btn';
    }

    createModal() {
        // Check if modal already exists and remove it to prevent event listener duplication
        const existing = document.getElementById(this.options.id);
        if (existing) {
            existing.remove();
        }

        const modal = document.createElement('div');
        modal.id = this.options.id;
        modal.className = 'age-verification-overlay';
        modal.style.display = 'none';

        const iconHTML = this.options.showIcon ? this.getIconSVG(this.options.type) : '';

        modal.innerHTML = `
            <div class="surface border-2 ${this.getBorderClass(this.options.type)} p-4 pb-2 md:p-8 md:pb-4 mx-1 md:mx-0 ${this.options.maxWidth || 'max-w-lg'} w-full text-center">
                ${iconHTML}
                <h2 class="text-xl font-bold mb-4 ${this.getTitleClass(this.options.type)}">${this.options.title}</h2>
                <div class="text-base mb-6 text">${this.options.message}</div>
                <div class="flex gap-4 mt-2 md:mt-4 justify-center">
                    <button id="${this.options.confirmId}" class="px-6 py-3 ${this.getConfirmButtonClass(this.options.type)} font-bold text-sm cursor-pointer">
                        ${this.options.confirmText}
                    </button>
                    ${this.options.cancelText ? `<button id="${this.options.cancelId}" class="px-6 py-3 ${this.getCancelButtonClass()} font-bold text-sm cursor-pointer">
                        ${this.options.cancelText}
                    </button>` : ''}
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        this.modalElement = modal;
    }

    setupEventListeners() {
        const confirmBtn = this.modalElement
            ? this.modalElement.querySelector(`#${CSS.escape(this.options.confirmId)}`)
            : document.getElementById(this.options.confirmId);
        const cancelBtn = this.modalElement
            ? this.modalElement.querySelector(`#${CSS.escape(this.options.cancelId)}`)
            : document.getElementById(this.options.cancelId);

        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => this.confirm());
        }

        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.cancel());
        }

        if (this.options.closeOnEscape) {
            if (this._escapeHandler) {
                document.removeEventListener('keydown', this._escapeHandler);
            }
            this._escapeHandler = (e) => {
                if (e.key === 'Escape' && this.isVisible) {
                    this.cancel();
                }
            };
            document.addEventListener('keydown', this._escapeHandler);
        }

        if (this.options.closeOnOutsideClick) {
            this.modalElement.addEventListener('click', (e) => {
                if (e.target === this.modalElement) {
                    this.cancel();
                }
            });
        }
    }

    show() {
        if (!this.modalElement) {
            this.createModal();
        }

        this.modalElement.style.display = 'flex';
        this.isVisible = true;

        // Blur target element if specified
        if (this.options.blurTarget) {
            const target = document.querySelector(this.options.blurTarget);
            if (target) {
                target.classList.add('media-blurred');
            }
        }

        return this;
    }

    hide() {
        if (this.modalElement) {
            this.modalElement.style.display = 'none';
            this.isVisible = false;

            // Remove blur from target element
            if (this.options.blurTarget) {
                const target = document.querySelector(this.options.blurTarget);
                if (target) {
                    target.classList.remove('media-blurred');
                }
            }
        }

        return this;
    }

    confirm() {
        this.hide();
        if (typeof this.options.onConfirm === 'function') {
            this.options.onConfirm();
        }
    }

    cancel() {
        this.hide();
        if (typeof this.options.onCancel === 'function') {
            this.options.onCancel();
        }
    }

    updateContent(options = {}) {
        if (options.title) {
            this.options.title = options.title;
        }
        if (options.message) {
            this.options.message = options.message;
        }
        if (options.type) {
            this.options.type = options.type;
        }

        if (this._escapeHandler) {
            document.removeEventListener('keydown', this._escapeHandler);
            this._escapeHandler = null;
        }

        // Recreate modal with new content
        if (this.modalElement && this.modalElement.parentNode) {
            this.modalElement.parentNode.removeChild(this.modalElement);
        }
        this.createModal();
        this.setupEventListeners();

        return this;
    }

    destroy() {
        this.hide();
        if (this._escapeHandler) {
            document.removeEventListener('keydown', this._escapeHandler);
            this._escapeHandler = null;
        }
        if (this.modalElement && this.modalElement.parentNode) {
            this.modalElement.parentNode.removeChild(this.modalElement);
        }
        this.modalElement = null;
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ModalHelper;
}
