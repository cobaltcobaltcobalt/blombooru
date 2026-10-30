const TagBulkModals = {
    _normalizeName(value) {
        return value.trim().toLowerCase().replace(/\s+/g, '_');
    },

    async _runBatch(tags, worker, title = null) {
        let success = 0;
        let failed = 0;
        const total = tags.length;

        let progressOverlay = null;
        let progressText = null;
        if (total > 1) {
            progressOverlay = document.createElement('div');
            progressOverlay.className = 'age-verification-overlay';
            progressOverlay.style.display = 'flex';
            progressOverlay.innerHTML = `
                <div class="surface border-2 border-primary p-6 max-w-sm w-full text-center">
                    <div class="spinner inline-block mb-3"></div>
                    <div id="bulk-progress-text" class="text-sm font-semibold text"></div>
                </div>
            `;
            document.body.appendChild(progressOverlay);
            progressText = progressOverlay.querySelector('#bulk-progress-text');
            if (progressText) {
                progressText.textContent = `${title || window.i18n.t('common.processing')} (0/${total})`;
            }
        }

        try {
            for (let i = 0; i < tags.length; i++) {
                const tag = tags[i];
                if (progressText) {
                    progressText.textContent = `${title || window.i18n.t('common.processing')} (${i + 1}/${total})`;
                }
                try {
                    await worker(tag);
                    success++;
                } catch (e) {
                    failed++;
                    console.error(`Bulk tag action failed for '${tag.name}':`, e);
                }
            }
        } finally {
            if (progressOverlay) progressOverlay.remove();
        }

        if (failed === 0) {
            app.showNotification(window.i18n.t('bulk_modal.notifications.updated_success', { count: success }), 'success');
        } else {
            app.showNotification(
                window.i18n.t('bulk_modal.notifications.updated_failed', { count: failed }),
                'error'
            );
        }

        return { success, failed };
    },

    _createDialog({ id, title, bodyHTML, submitLabel, onSubmit, onCancel }) {
        const existing = document.getElementById(id);
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = id;
        modal.className = 'age-verification-overlay';
        modal.style.display = 'flex';

        modal.innerHTML = `
            <div class="surface border-2 border-primary p-8 max-w-md w-full text-left">
                <h2 class="text-xl font-bold mb-6 text-primary text-center">${escapeHtml(title)}</h2>
                ${bodyHTML}
                <div class="flex gap-3 justify-center">
                    <button type="button" data-role="submit" class="btn-primary px-6 py-3 font-bold text-sm flex-1 cursor-pointer">
                        ${escapeHtml(submitLabel)}
                    </button>
                    <button type="button" data-role="cancel" class="btn px-6 py-3 font-bold text-sm flex-1 cursor-pointer">
                        ${window.i18n.t('common.cancel')}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const handleEscape = (e) => {
            if (e.key === 'Escape') cancel();
        };

        const close = () => {
            modal.remove();
            document.removeEventListener('keydown', handleEscape);
        };

        const cancel = () => {
            close();
            if (onCancel) onCancel();
        };

        modal.querySelector('[data-role="cancel"]').addEventListener('click', cancel);
        modal.querySelector('[data-role="submit"]').addEventListener('click', () => onSubmit(close));
        modal.addEventListener('click', (e) => {
            if (e.target === modal) cancel();
        });
        document.addEventListener('keydown', handleEscape);

        return { modal, close };
    },

    category({ tags, onCancel, onDone }) {
        const categories = TagInfoPanel.KNOWN_CATEGORIES;
        const options = categories.map(c =>
            `<div class="custom-select-option px-3 py-2 cursor-pointer hover:surface text-xs" data-value="${c}">${window.i18n.t('common.tag_category_' + c)}</div>`
        ).join('');

        const { modal, close } = this._createDialog({
            id: 'tag-bulk-category-modal',
            title: window.i18n.t('admin.tags_management.tag_category'),
            submitLabel: window.i18n.t('common.apply'),
            bodyHTML: `
                <div class="mb-6">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_management.tag_category')}</label>
                    <div id="tag-bulk-category-select" class="custom-select w-full" data-value="${categories[0]}">
                        <button class="custom-select-trigger w-full flex items-center justify-between gap-3 px-3 py-2 bg border text-xs cursor-pointer focus:outline-none hover:border-primary transition-colors focus:border-primary" type="button">
                            <span class="custom-select-value text">${window.i18n.t('common.tag_category_' + categories[0])}</span>
                            ${window.Icons.selectArrow({ size: 12 })}
                        </button>
                        <div class="custom-select-dropdown bg border border-primary max-h-60 overflow-y-auto shadow-lg">
                            ${options}
                        </div>
                    </div>
                </div>
            `,
            onCancel,
            onSubmit: async (closeDialog) => {
                const newCategory = categorySelect.getValue();
                closeDialog();

                let progressOverlay = null;
                if (tags.length > 1) {
                    progressOverlay = document.createElement('div');
                    progressOverlay.className = 'age-verification-overlay';
                    progressOverlay.style.display = 'flex';
                    progressOverlay.innerHTML = `
                        <div class="surface border-2 border-primary p-6 max-w-sm w-full text-center">
                            <div class="spinner inline-block mb-3"></div>
                            <div id="bulk-category-progress-text" class="text-sm font-semibold text"></div>
                        </div>
                    `;
                    document.body.appendChild(progressOverlay);
                    const catText = progressOverlay.querySelector('#bulk-category-progress-text');
                    if (catText) {
                        catText.textContent = `${window.i18n.t('common.processing')} (${tags.length})`;
                    }
                }

                try {
                    const tagIds = tags.map(t => t.id);
                    const res = await app.apiCall('/api/admin/tags/bulk-category', {
                        method: 'POST',
                        body: JSON.stringify({
                            tag_ids: tagIds,
                            category: newCategory
                        })
                    });
                    const count = (res && typeof res.updated === 'number') ? res.updated : tags.length;
                    app.showNotification(window.i18n.t('bulk_modal.notifications.updated_success', { count }), 'success');
                } catch (err) {
                    console.error('Bulk category update failed:', err);
                    app.showNotification(err.message, 'error');
                } finally {
                    if (progressOverlay) progressOverlay.remove();
                }

                if (onDone) await onDone();
            }
        });

        const categorySelect = new CustomSelect(modal.querySelector('#tag-bulk-category-select'));
        categorySelect.setValue(categories[0]);
    },

    rating({ tags, onCancel, onDone }) {
        const ratings = [
            { value: 'none', label: window.i18n.t('common.none', { defaultValue: 'None' }) },
            { value: 'safe', label: window.i18n.t('common.safe', { defaultValue: 'Safe' }) },
            { value: 'questionable', label: window.i18n.t('common.questionable', { defaultValue: 'Questionable' }) },
            { value: 'explicit', label: window.i18n.t('common.explicit', { defaultValue: 'Explicit' }) },
        ];
        const options = ratings.map(r =>
            `<div class="custom-select-option px-3 py-2 cursor-pointer hover:surface text-xs" data-value="${r.value}">${r.label}</div>`
        ).join('');

        const { modal, close } = this._createDialog({
            id: 'tag-bulk-rating-modal',
            title: window.i18n.t('admin.tags_management.tag_rating', { defaultValue: 'Tag Rating' }),
            submitLabel: window.i18n.t('common.apply'),
            bodyHTML: `
                <div class="mb-6">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_management.tag_rating', { defaultValue: 'Tag Rating' })}</label>
                    <div id="tag-bulk-rating-select" class="custom-select w-full" data-value="${ratings[0].value}">
                        <button class="custom-select-trigger w-full flex items-center justify-between gap-3 px-3 py-2 bg border text-xs cursor-pointer focus:outline-none hover:border-primary transition-colors focus:border-primary" type="button">
                            <span class="custom-select-value text flex items-center gap-2">
                                <span>${ratings[0].label}</span>
                            </span>
                            ${window.Icons.selectArrow({ size: 12 })}
                        </button>
                        <div class="custom-select-dropdown bg border border-primary max-h-60 overflow-y-auto shadow-lg">
                            ${options}
                        </div>
                    </div>
                </div>
            `,
            onCancel,
            onSubmit: async (closeDialog) => {
                const newRating = ratingSelect.getValue();
                closeDialog();

                let progressOverlay = null;
                if (tags.length > 1) {
                    progressOverlay = document.createElement('div');
                    progressOverlay.className = 'age-verification-overlay';
                    progressOverlay.style.display = 'flex';
                    progressOverlay.innerHTML = `
                        <div class="surface border-2 border-primary p-6 max-w-sm w-full text-center">
                            <div class="spinner inline-block mb-3"></div>
                            <div id="bulk-rating-progress-text" class="text-sm font-semibold text"></div>
                        </div>
                    `;
                    document.body.appendChild(progressOverlay);
                    const ratText = progressOverlay.querySelector('#bulk-rating-progress-text');
                    if (ratText) {
                        ratText.textContent = `${window.i18n.t('common.processing')} (${tags.length})`;
                    }
                }

                try {
                    const tagIds = tags.map(t => t.id);
                    const res = await app.apiCall('/api/admin/tags/bulk-rating', {
                        method: 'POST',
                        body: JSON.stringify({
                            tag_ids: tagIds,
                            rating: newRating
                        })
                    });
                    const count = (res && typeof res.updated === 'number') ? res.updated : tags.length;
                    app.showNotification(window.i18n.t('bulk_modal.notifications.updated_success', { count }), 'success');
                } catch (err) {
                    console.error('Bulk rating update failed:', err);
                    app.showNotification(err.message, 'error');
                } finally {
                    if (progressOverlay) progressOverlay.remove();
                }

                if (onDone) await onDone();
            }
        });

        const ratingSelect = new CustomSelect(modal.querySelector('#tag-bulk-rating-select'));
        ratingSelect.setValue(ratings[0].value);
    },

    implies({ tags, onCancel, onDone }) {
        const { modal } = this._createDialog({
            id: 'tag-bulk-implies-modal',
            title: window.i18n.t('admin.tags_implications.title'),
            submitLabel: window.i18n.t('common.apply'),
            bodyHTML: `
                <div class="relative mb-6">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_implications.implies_tags')}</label>
                    <input type="text" id="tag-bulk-implies-input"
                        class="w-full bg px-3 py-2 border text-xs focus:outline-none hover:border-primary transition-colors focus:border-primary"
                        placeholder="${escapeHtml(window.i18n.t('tags_gallery.add_implied_tag'))}" autocomplete="off" spellcheck="false">
                </div>
            `,
            onCancel,
            onSubmit: async (closeDialog) => {
                const impliedTags = [...new Set(
                    input.value.split(/\s+/).map(t => this._normalizeName(t)).filter(Boolean)
                )];

                if (impliedTags.length === 0) {
                    input.classList.add('border-danger');
                    input.focus();
                    return;
                }

                closeDialog();

                try {
                    await app.apiCall('/api/tag-implications/', {
                        method: 'POST',
                        body: JSON.stringify({
                            target_tags: tags.map(t => t.name),
                            implied_tags: impliedTags
                        })
                    });
                    app.showNotification(window.i18n.t('tags_gallery.implication_added'), 'success');
                } catch (e) {
                    app.showNotification(e.message, 'error');
                }

                if (onDone) await onDone();
            }
        });

        const input = modal.querySelector('#tag-bulk-implies-input');

        if (typeof TagAutocomplete !== 'undefined') {
            new TagAutocomplete(input, {
                multipleValues: true,
                appendSpace: true,
                allowCreate: true
            });
        }

        input.addEventListener('input', () => input.classList.remove('border-danger'));
        input.focus();
    },

    merge({ tags, onCancel, onDone }) {
        const { modal } = this._createDialog({
            id: 'tag-bulk-merge-modal',
            title: window.i18n.t('admin.tags_management.merge_tag'),
            submitLabel: window.i18n.t('admin.tags_management.merge_into'),
            bodyHTML: `
                <div class="relative mb-6">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_management.target_tag_name')}</label>
                    <input type="text" id="tag-bulk-merge-input"
                        class="w-full bg px-3 py-2 border text-xs focus:outline-none hover:border-primary transition-colors focus:border-primary"
                        placeholder="cat_ears" autocomplete="off" spellcheck="false">
                    <p id="tag-bulk-merge-error" class="text-xs text-danger mt-1" style="display:none;"></p>
                </div>
            `,
            onCancel,
            onSubmit: (closeDialog) => {
                if (!validate()) return;

                const targetTag = this._normalizeName(input.value);
                const sources = tags.filter(t => t.name.toLowerCase() !== targetTag);
                closeDialog();

                const sourceNamesStr = sources.length <= 3
                    ? sources.map(s => s.name).join(', ')
                    : `${sources.slice(0, 3).map(s => s.name).join(', ')} (+${sources.length - 3} more)`;
                const sourceLabel = sources.length === 1
                    ? sources[0].name
                    : `${sources.length} tags (${sourceNamesStr})`;

                const message = `
                    <div class="text-base font-semibold text mb-2">
                        ${window.i18n.t('admin.tags_management.confirm_merge_subtitle', { source_tag: escapeHtml(sourceLabel), target_tag: escapeHtml(targetTag) })}
                    </div>
                    <ul class="text-left text-sm space-y-2 text list-disc px-6">
                        <li>${window.i18n.t('admin.tags_management.confirm_merge_apply', { source_tag: escapeHtml(sourceLabel), target_tag: escapeHtml(targetTag) })}</li>
                        <li>${window.i18n.t('admin.tags_management.confirm_merge_delete', { source_tag: escapeHtml(sourceLabel), target_tag: escapeHtml(targetTag) })}</li>
                        <li>${window.i18n.t('admin.tags_management.confirm_merge_alias', { source_tag: escapeHtml(sourceLabel), target_tag: escapeHtml(targetTag) })}</li>
                    </ul>
                `;

                new ModalHelper({
                    id: 'confirm-bulk-merge-tag-modal',
                    type: 'warning',
                    title: window.i18n.t('admin.tags_management.confirm_merge_title'),
                    message,
                    confirmText: window.i18n.t('admin.tags_management.merge_tag'),
                    cancelText: window.i18n.t('common.cancel'),
                    onConfirm: async () => {
                        await this._runBatch(sources, (tag) => app.apiCall(`/api/admin/tags/${tag.id}/merge-into`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ target_tag_name: targetTag })
                        }));
                        if (onDone) await onDone();
                    },
                    onCancel: () => {
                        if (onCancel) onCancel();
                    }
                }).show();
            }
        });

        const input = modal.querySelector('#tag-bulk-merge-input');
        const errorEl = modal.querySelector('#tag-bulk-merge-error');

        const showError = (text) => {
            input.classList.add('border-danger');
            errorEl.textContent = text;
            errorEl.style.display = '';
        };

        const validate = () => {
            const val = this._normalizeName(input.value);
            if (!val) {
                showError(window.i18n.t('admin.tags_management.target_tag_name'));
                return false;
            }
            if (tags.every(t => t.name.toLowerCase() === val)) {
                showError(window.i18n.t('notifications.admin.cannot_merge_self'));
                return false;
            }
            input.classList.remove('border-danger');
            errorEl.style.display = 'none';
            return true;
        };

        if (typeof TagAutocomplete !== 'undefined') {
            new TagAutocomplete(input, {
                multipleValues: false,
                appendSpace: false,
                allowCreate: false,
                onSelect: () => validate()
            });
        }

        input.addEventListener('input', () => {
            const pos = input.selectionStart;
            input.value = input.value.replace(/ /g, '_');
            input.setSelectionRange(pos, pos);
            validate();
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                modal.querySelector('[data-role="submit"]').click();
            }
        });

        input.focus();
    },

    remove({ tags, onCancel, onDone }) {
        const count = tags.length;
        const title = count > 1
            ? window.i18n.t('tags_gallery.bulk_delete_title', { count })
            : window.i18n.t('modal.delete_tag.title');
        const message = count > 1
            ? window.i18n.t('tags_gallery.bulk_delete_message', { count })
            : window.i18n.t('modal.delete_tag.message');

        new ModalHelper({
            id: 'bulk-delete-tags-modal',
            type: 'danger',
            title,
            message,
            confirmText: window.i18n.t('common.yes_delete'),
            cancelText: window.i18n.t('common.cancel'),
            onConfirm: async () => {
                await this._runBatch(tags, (tag) => app.apiCall(`/api/admin/tags/${tag.id}`, { method: 'DELETE' }));
                if (onDone) await onDone();
            },
            onCancel: () => {
                if (onCancel) onCancel();
            }
        }).show();
    }
};

window.TagBulkModals = TagBulkModals;
