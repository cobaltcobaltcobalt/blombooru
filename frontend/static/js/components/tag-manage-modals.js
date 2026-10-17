const TagManageModals = {
    _helper: null,

    _getHelper(provided) {
        if (provided) return provided;
        if (!this._helper && typeof TagInputHelper !== 'undefined') {
            this._helper = new TagInputHelper();
        }
        return this._helper;
    },

    remove({ tagId, tagName, tagCategory, onCancel, onDeleted }) {
        const modal = new ModalHelper({
            id: 'delete-tag-modal',
            type: 'danger',
            title: window.i18n.t('modal.delete_tag.title'),
            message: window.i18n.t('modal.delete_tag.message'),
            confirmText: window.i18n.t('common.yes_delete'),
            cancelText: window.i18n.t('common.cancel'),
            confirmId: 'delete-tag-confirm-yes',
            cancelId: 'delete-tag-confirm-no',
            onConfirm: async () => {
                try {
                    const result = await app.apiCall(`/api/admin/tags/${tagId}`, { method: 'DELETE' });
                    app.showNotification(window.i18n.t('notifications.admin.tag_deleted', { tag_name: result.tag_name }), 'success');
                    if (onDeleted) await onDeleted(result);
                } catch (e) {
                    app.showNotification(e.message, 'error', window.i18n.t('notifications.admin.error_deleting_tag'));
                }
            },
            onCancel: () => {
                if (tagName && tagCategory && onCancel) onCancel();
            }
        });

        modal.show();
    },

    merge({ tagId, tagName, onCancel, onMerged }) {
        const existingModal = document.getElementById('tag-merge-modal');
        if (existingModal) existingModal.remove();

        const modal = document.createElement('div');
        modal.id = 'tag-merge-modal';
        modal.className = 'age-verification-overlay';
        modal.style.display = 'flex';

        modal.innerHTML = `
            <div class="surface border-2 border-primary p-8 max-w-md w-full text-left">
                <h2 class="text-xl font-bold mb-6 text-primary text-center">
                    ${window.i18n.t('admin.tags_management.merge_tag')}
                </h2>

                <div class="relative mb-6">
                    <label class="block text-xs font-bold mb-2">
                        ${window.i18n.t('admin.tags_management.target_tag_name')}
                    </label>
                    <input type="text" id="tag-merge-target-input"
                        class="w-full bg px-3 py-2 border text-xs focus:outline-none hover:border-primary transition-colors focus:border-primary"
                        placeholder="cat_ears" autocomplete="off" spellcheck="false">
                    <p id="tag-merge-target-error" class="text-xs text-danger mt-1" style="display:none;"></p>
                </div>

                <div class="flex gap-3 justify-center">
                    <button id="tag-merge-submit" class="btn-primary px-6 py-3 font-bold text-sm flex-1 cursor-pointer">
                        ${window.i18n.t('admin.tags_management.merge_into')}
                    </button>
                    <button id="tag-merge-cancel" class="btn px-6 py-3 font-bold text-sm flex-1 cursor-pointer">
                        ${window.i18n.t('common.cancel')}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const input = document.getElementById('tag-merge-target-input');
        const errorEl = document.getElementById('tag-merge-target-error');

        const validateTargetTag = () => {
            const val = input.value.trim().toLowerCase().replace(/\s+/g, '_');
            if (!val) {
                input.classList.add('border-danger');
                errorEl.textContent = window.i18n.t('admin.tags_management.target_tag_name');
                errorEl.style.display = '';
                return false;
            }
            if (val === tagName.toLowerCase()) {
                input.classList.add('border-danger');
                errorEl.textContent = window.i18n.t('notifications.admin.cannot_merge_self');
                errorEl.style.display = '';
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
                onSelect: () => {
                    validateTargetTag();
                }
            });
        }

        input.addEventListener('input', () => {
            const pos = input.selectionStart;
            input.value = input.value.replace(/ /g, '_');
            input.setSelectionRange(pos, pos);
            validateTargetTag();
        });

        input.focus();

        const handleEscape = (e) => {
            if (e.key === 'Escape') cancel();
        };

        const closeModal = () => {
            modal.remove();
            document.removeEventListener('keydown', handleEscape);
        };

        const cancel = () => {
            closeModal();
            if (onCancel) onCancel();
        };

        document.getElementById('tag-merge-cancel').addEventListener('click', cancel);

        modal.addEventListener('click', (e) => {
            if (e.target === modal) cancel();
        });

        document.addEventListener('keydown', handleEscape);

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('tag-merge-submit').click();
            }
        });

        document.getElementById('tag-merge-submit').addEventListener('click', async () => {
            if (!validateTargetTag()) return;
            const targetTag = input.value.trim().toLowerCase().replace(/\s+/g, '_');

            closeModal();

            const tagParams = {
                source_tag: escapeHtml(tagName),
                target_tag: escapeHtml(targetTag)
            };

            const subtitle = window.i18n.t('admin.tags_management.confirm_merge_subtitle', tagParams);
            const applyAction = window.i18n.t('admin.tags_management.confirm_merge_apply', tagParams);
            const deleteAction = window.i18n.t('admin.tags_management.confirm_merge_delete', tagParams);
            const aliasAction = window.i18n.t('admin.tags_management.confirm_merge_alias', tagParams);

            const messageHTML = `
                <div class="text-base font-semibold text mb-2">${subtitle}</div>
                <ul class="text-left text-sm space-y-2 text list-disc px-6">
                    <li>${applyAction}</li>
                    <li>${deleteAction}</li>
                    <li>${aliasAction}</li>
                </ul>
            `;

            const confirmModal = new ModalHelper({
                id: 'confirm-merge-tag-modal',
                type: 'warning',
                title: window.i18n.t('admin.tags_management.confirm_merge_title'),
                message: messageHTML,
                confirmText: window.i18n.t('admin.tags_management.merge_tag'),
                cancelText: window.i18n.t('common.cancel'),
                confirmId: 'confirm-merge-yes',
                cancelId: 'confirm-merge-no',
                onConfirm: async () => {
                    try {
                        const result = await app.apiCall(`/api/admin/tags/${tagId}/merge-into`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ target_tag_name: targetTag })
                        });
                        app.showNotification(
                            window.i18n.t('notifications.admin.tag_merged', {
                                source_tag: result.source_tag_name,
                                target_tag: result.target_tag_name
                            }),
                            'success'
                        );
                        if (onMerged) await onMerged(result);
                    } catch (e) {
                        app.showNotification(e.message, 'error', window.i18n.t('notifications.admin.error_merging_tag'));
                    }
                },
                onCancel: () => {
                    if (onCancel) onCancel();
                }
            });

            confirmModal.show();
        });
    },

    async edit({ tagId, tagName, tagCategory, tagInputHelper, onCancel, onSaved }) {
        const existingModal = document.getElementById('tag-edit-modal');
        if (existingModal) existingModal.remove();

        const helper = this._getHelper(tagInputHelper);

        // Fetch tag details including aliases
        let currentAliases = [];
        try {
            const res = await fetch(`/api/admin/tags/${tagId}`);
            if (!res.ok) {
                throw new Error(window.i18n.t('tags_gallery.load_details_failed'));
            }
            const data = await res.json();
            if (Array.isArray(data.aliases)) {
                currentAliases = data.aliases;
            }
        } catch (e) {
            console.error('Error fetching tag details:', e);
            app.showNotification(e.message || window.i18n.t('tags_gallery.load_details_failed'), 'error');
            if (onCancel) onCancel();
            return;
        }

        const categories = [
            { value: 'general', label: window.i18n.t('common.tag_category_general') },
            { value: 'artist', label: window.i18n.t('common.tag_category_artist') },
            { value: 'character', label: window.i18n.t('common.tag_category_character') },
            { value: 'copyright', label: window.i18n.t('common.tag_category_copyright') },
            { value: 'meta', label: window.i18n.t('common.tag_category_meta') },
        ];

        const categoryOptions = categories.map(c =>
            `<div class="custom-select-option px-3 py-2 cursor-pointer hover:surface text-xs" data-value="${c.value}">${c.label}</div>`
        ).join('');

        const currentCategory = categories.find(c => c.value === tagCategory) || categories[0];

        const modal = document.createElement('div');
        modal.id = 'tag-edit-modal';
        modal.className = 'age-verification-overlay';
        modal.style.display = 'flex';

        modal.innerHTML = `
            <div class="surface border-2 border-primary p-8 max-w-md w-full">
                <h2 class="text-xl font-bold mb-6 text-primary text-center">${window.i18n.t('admin.tags_management.edit_tag')}</h2>

                <div class="mb-4">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_management.tag_name')}</label>
                    <input type="text" id="tag-edit-name" value="${escapeHtml(tagName)}"
                        class="w-full bg px-3 py-2 border text-xs focus:outline-none hover:border-primary transition-colors focus:border-primary"
                        autocomplete="off" spellcheck="false">
                    <p id="tag-edit-name-error" class="text-xs text-danger mt-1" style="display:none;"></p>
                </div>

                <div class="mb-4">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_management.tag_category')}</label>
                    <div id="tag-edit-category-select" class="custom-select w-full" data-value="${currentCategory.value}">
                        <button class="custom-select-trigger w-full flex items-center justify-between gap-3 px-3 py-2 bg border text-xs cursor-pointer focus:outline-none hover:border-primary transition-colors focus:border-primary" type="button">
                            <span class="custom-select-value text">${currentCategory.label}</span>
                            ${window.Icons.selectArrow({ size: 12 })}
                        </button>
                        <div class="custom-select-dropdown bg border border-primary max-h-60 overflow-y-auto shadow-lg">
                            ${categoryOptions}
                        </div>
                    </div>
                </div>

                <div class="mb-6">
                    <label class="block text-xs font-bold mb-2">${window.i18n.t('admin.tags_management.tag_aliases')}</label>
                    <div id="tag-edit-aliases" contenteditable="true" spellcheck="false"
                        class="w-full bg px-3 py-2 border text-xs min-h-15 max-h-30 overflow-y-auto focus:outline-none hover:border-primary transition-colors focus:border-primary"></div>
                    <p class="text-xs text-secondary mt-1">${window.i18n.t('admin.tags_management.tag_aliases_hint')}</p>
                </div>

                <div class="flex gap-3 justify-center">
                    <button id="tag-edit-save" class="btn-primary px-6 py-3 font-bold text-sm flex-1 cursor-pointer">
                        ${window.i18n.t('common.save')}
                    </button>
                    <button id="tag-edit-cancel" class="btn px-6 py-3 font-bold text-sm flex-1 cursor-pointer">
                        ${window.i18n.t('common.cancel')}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const categorySelectEl = document.getElementById('tag-edit-category-select');
        const categorySelect = new CustomSelect(categorySelectEl);
        categorySelect.setValue(currentCategory.value);

        const aliasesInput = document.getElementById('tag-edit-aliases');
        const currentAliasSet = new Set(currentAliases.map(a => a.toLowerCase()));

        // Prepopulate aliases input
        if (currentAliases.length > 0) {
            aliasesInput.textContent = currentAliases.join(' ') + ' ';
        }

        // Setup alias validation using TagInputHelper in inverted mode
        const aliasValidationCache = new Map();
        const checkAliasConflict = async (alias) => {
            const normalized = alias.toLowerCase().trim();
            // If it's one of this tag's own aliases or the tag's current/new name, it's not a conflict
            if (currentAliasSet.has(normalized) || normalized === tagName.toLowerCase()) {
                return false;
            }
            return await helper.checkTagOrAliasExists(normalized);
        };

        if (helper) {
            helper.setupTagInput(aliasesInput, 'tag-edit-aliases', {
                validationCache: aliasValidationCache,
                checkFunction: checkAliasConflict,
                invertLogic: true,
                expandImplications: false
            });
            // Initial styling pass
            await helper.validateAndStyleTags(aliasesInput, {
                validationCache: aliasValidationCache,
                checkFunction: checkAliasConflict,
                invertLogic: true
            });
        }

        // Inverse validation with current tag's own name seeded as "not a conflict"
        const nameInput = document.getElementById('tag-edit-name');
        const nameError = document.getElementById('tag-edit-name-error');
        let nameConflict = false;
        let validationTimer = null;

        const validateName = async () => {
            const val = nameInput.value.trim().toLowerCase().replace(/\s+/g, '_');
            if (!val || val === tagName.toLowerCase()) {
                nameConflict = false;
                nameInput.classList.remove('border-danger');
                nameError.style.display = 'none';
                return;
            }
            // Check if name conflicts with an existing tag or alias
            try {
                const res = await fetch(`/api/tags/${encodeURIComponent(val)}`);
                if (res.ok) {
                    nameConflict = true;
                    nameInput.classList.add('border-danger');
                    nameError.textContent = window.i18n.t('notifications.admin.tag_name_conflict');
                    nameError.style.display = '';
                    return;
                }
                const aliasRes = await fetch(`/api/admin/check-alias?name=${encodeURIComponent(val)}`);
                if (aliasRes.ok) {
                    const aliasData = await aliasRes.json();
                    if (aliasData.exists) {
                        nameConflict = true;
                        nameInput.classList.add('border-danger');
                        nameError.textContent = window.i18n.t('notifications.admin.tag_name_conflict');
                        nameError.style.display = '';
                        return;
                    }
                }
            } catch (e) { /* network error: allow save */ }
            nameConflict = false;
            nameInput.classList.remove('border-danger');
            nameError.style.display = 'none';
        };

        nameInput.addEventListener('input', () => {
            // Replace spaces with underscores as user types
            const pos = nameInput.selectionStart;
            nameInput.value = nameInput.value.replace(/ /g, '_');
            nameInput.setSelectionRange(pos, pos);
            clearTimeout(validationTimer);
            validationTimer = setTimeout(validateName, 400);
        });

        nameInput.focus();
        nameInput.select();

        const handleEscape = (e) => {
            if (e.key === 'Escape') cancel();
        };

        const closeModal = () => {
            modal.remove();
            document.removeEventListener('keydown', handleEscape);
        };

        const cancel = () => {
            closeModal();
            if (onCancel) onCancel();
        };

        const doSave = async () => {
            const newName = nameInput.value.trim().toLowerCase().replace(/\s+/g, '_');
            if (!newName) {
                nameInput.classList.add('border-danger');
                nameError.textContent = window.i18n.t('admin.tags_management.tag_name');
                nameError.style.display = '';
                return;
            }
            if (nameConflict) {
                nameInput.focus();
                return;
            }

            // Collect non-conflicting aliases from aliasesInput
            const aliasText = helper ? helper.getPlainTextFromDiv(aliasesInput) : (aliasesInput.textContent || '');
            const rawAliasTokens = aliasText.split(/\s+/).filter(t => t.length > 0);
            const validAliases = [];
            let aliasConflictFound = false;

            for (const token of rawAliasTokens) {
                const norm = token.toLowerCase().trim();
                // Check if marked invalid in cache
                if (aliasValidationCache.get(norm) === true) {
                    // In invertLogic, true means exists (conflict)
                    aliasConflictFound = true;
                } else {
                    validAliases.push(norm);
                }
            }

            if (aliasConflictFound) {
                aliasesInput.focus();
                app.showNotification(window.i18n.t('notifications.admin.tag_name_conflict'), 'error');
                return;
            }

            const newCategory = categorySelect.getValue();
            closeModal();
            try {
                const result = await app.apiCall(`/api/admin/tags/${tagId}`, {
                    method: 'PUT',
                    body: JSON.stringify({ name: newName, category: newCategory, aliases: validAliases })
                });
                app.showNotification(
                    window.i18n.t('notifications.admin.tag_updated', { old_name: result.old_name }),
                    'success'
                );
                if (onSaved) await onSaved(result);
            } catch (e) {
                app.showNotification(e.message, 'error', window.i18n.t('notifications.admin.error_updating_tag'));
            }
        };

        document.getElementById('tag-edit-save').addEventListener('click', doSave);
        document.getElementById('tag-edit-cancel').addEventListener('click', cancel);

        nameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); doSave(); }
        });

        document.addEventListener('keydown', handleEscape);
    }
};

window.TagManageModals = TagManageModals;
