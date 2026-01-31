class BulkManualTagEditorModal extends BulkTagModalBase {
    constructor(options = {}) {
        super({
            id: 'bulk-manual-tag-editor-modal',
            title: window.i18n.t('bulk_modal.manual.title'),
            classPrefix: 'bulk-manual',
            emptyMessage: window.i18n.t('bulk_modal.manual.empty_message'),
            closeOnOutsideClick: false,
            ...options
        });

        this.init();
    }

    getBodyHTML() {
        return `
            ${this.getLoadingHTML(window.i18n.t('bulk_modal.progress.fetching_metadata'))}
            ${this.getContentHTML()}
            ${this.getEmptyHTML()}
            ${this.getCancelledHTML()}
        `;
    }

    async fetchTags() {
        if (this.isCancelled) return;

        this.showState('loading');
        const prefix = this.options.classPrefix;
        const itemsContainer = this.modalElement.querySelector(`.${prefix}-items`);

        const selectedArray = Array.from(this.selectedItems);

        // Fetch media data in batch
        this.updateProgress(0, selectedArray.length, window.i18n.t('bulk_modal.progress.fetching_metadata'), window.i18n.t('bulk_modal.progress.items_fetched'));

        try {
            const idsParam = selectedArray.join(',');
            const res = await this.fetchWithAbort(`/api/media/batch?ids=${idsParam}`);

            if (!res.ok) throw new Error('Failed to fetch media');

            const data = await res.json();
            const items = data.items || [];

            if (items.length === 0) {
                this.showState('empty');
                return;
            }

            // Process items
            this.itemsData = items.map(item => {
                const currentTags = (item.tags || []).map(t => t.name || t);
                return {
                    mediaId: item.id,
                    currentTags: [...currentTags], // Original tags
                    newTags: [...currentTags],     // Editable tags (initially same as current)
                    filename: item.filename || window.i18n.t('bulk_modal.ai_tags.default_media_name', { id: item.id })
                };
            });

            this.renderItems();
            await this.initializeInputHelpers(itemsContainer);

            if (this.isCancelled) return;

            this.showState('content');
            this.showSaveButton();

        } catch (e) {
            if (e.name === 'AbortError') return;
            console.error('Error fetching tags:', e);
            this.showError(window.i18n.t('bulk_modal.messages.error_occurred'));
        }
    }

    // Override saveTags to replace tags instead of merging
    async saveTags() {
        const prefix = this.options.classPrefix;
        const saveBtn = this.modalElement.querySelector(`.${prefix}-save`);

        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.textContent = window.i18n.t('modal.buttons.saving');
        }

        let successCount = 0;
        let errorCount = 0;

        const saveItem = async (index) => {
            const item = this.itemsData[index];
            const input = this.modalElement.querySelector(`.${prefix}-input[data-index="${index}"]`);

            if (!input) return;

            let finalTags = [];
            if (this.tagInputHelper) {
                finalTags = this.tagInputHelper.getValidTagsFromInput(input);
            } else {
                finalTags = input.innerText.trim().split(/\s+/).filter(t => t.length > 0);
            }

            // For manual editor, we send whatever is in the input, even if empty (clearing tags)
            // But usually we want to avoid accidental clears? 
            // The user requested "edit media's tags freely". So clearing is valid.

            try {
                const response = await fetch(`/api/media/${item.mediaId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tags: finalTags })
                });

                if (response.ok) successCount++;
                else errorCount++;
            } catch (e) {
                console.error(`Error saving tags for media ${item.mediaId}:`, e);
                errorCount++;
            }
        };

        const indices = this.itemsData.map((_, i) => i);
        await this.processBatch(indices, saveItem, 5);

        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = window.i18n.t('modal.buttons.save_all');
        }

        this.hide();

        if (typeof this.options.onSave === 'function') {
            this.options.onSave({ successCount, errorCount });
        }

        if (typeof app !== 'undefined' && app.showNotification) {
            if (successCount > 0) app.showNotification(window.i18n.t('bulk_modal.notifications.updated_success', { count: successCount }), 'success');
            if (errorCount > 0) app.showNotification(window.i18n.t('bulk_modal.notifications.updated_failed', { count: errorCount }), 'error');
        }
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = BulkManualTagEditorModal;
}
