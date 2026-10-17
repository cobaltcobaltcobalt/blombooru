class ChangelogModal {
    constructor() {
        this.modalElement = null;
    }

    static getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    static async init() {
        if (ChangelogModal.getCookie('admin_mode') !== 'true') {
            return;
        }

        const instance = new ChangelogModal();
        await instance.checkAndShow();
    }

    async checkAndShow() {
        try {
            const response = await fetch('/api/changelog');
            if (!response.ok) {
                return;
            }

            const data = await response.json();
            if (data && data.needs_modal && data.html) {
                this.render(data);
            }
        } catch (error) {
            console.error('Failed to check changelog:', error);
        }
    }

    render(data) {
        // Prevent duplicate modals
        const existing = document.getElementById('changelog-modal-overlay');
        if (existing) {
            existing.remove();
        }

        const overlay = document.createElement('div');
        overlay.id = 'changelog-modal-overlay';
        overlay.className = 'age-verification-overlay';

        const t = (key, params) => window.i18n.t(key, params);
        const currentLang = window.CURRENT_LANGUAGE || 'en';
        const showNotice = currentLang !== 'en';

        overlay.innerHTML = `
            <div class="surface border-2 border-primary p-4 md:p-6 mx-2 md:mx-0 max-w-5xl w-full flex flex-col shadow-2xl" style="max-height: 85vh;">
                <div class="flex items-center justify-between gap-2 mb-2">
                    <h2 class="text-lg md:text-xl font-bold text-primary">${t('changelog.modal_title')}</h2>
                    ${data.current_version ? `<span class="font-mono text-xs px-2 py-0.5 bg border text-secondary">v${data.current_version.replace(/^v/, '')}</span>` : ''}
                </div>
                ${showNotice ? `<p class="text-xs text-secondary italic">${t('changelog.english_only_notice')}</p>` : ''}
                <div class="overflow-y-auto custom-scrollbar flex-1 text-left text-sm mt-2 space-y-3" style="overscroll-behavior: contain;">
                    ${data.html}
                </div>
                <div class="flex pt-4 border-t justify-center">
                    <button id="changelog-got-it-btn" class="btn-primary px-6 py-3 font-bold text-sm cursor-pointer">
                        ${t('common.got_it')}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        this.modalElement = overlay;

        const gotItBtn = overlay.querySelector('#changelog-got-it-btn');
        if (gotItBtn) {
            gotItBtn.addEventListener('click', async () => {
                gotItBtn.disabled = true;
                try {
                    await fetch('/api/changelog/acknowledge', { method: 'POST' });
                } catch (err) {
                    console.error('Failed to acknowledge changelog:', err);
                } finally {
                    this.close();
                }
            });
        }
    }

    close() {
        if (this.modalElement) {
            this.modalElement.remove();
            this.modalElement = null;
        }
    }
}

// Auto-initialize on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    ChangelogModal.init();
});
