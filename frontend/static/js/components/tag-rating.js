const TagRating = {
    KNOWN_RATINGS: ['none', 'safe', 'questionable', 'explicit'],

    normalize(val) {
        if (!val) return 'none';
        const str = String(val).toLowerCase().trim();
        return this.KNOWN_RATINGS.includes(str) ? str : 'none';
    },

    abbr(rating) {
        const clean = this.normalize(rating);
        const map = {
            safe: 'S',
            questionable: 'Q',
            explicit: 'E',
            none: 'N'
        };
        return map[clean] || 'N';
    },

    label(rating) {
        const clean = this.normalize(rating);
        if (typeof window !== 'undefined' && window.i18n && typeof window.i18n.t === 'function') {
            if (clean === 'none') {
                return window.i18n.t('common.none', { defaultValue: 'None' });
            }
            return window.i18n.t(`common.${clean}`, { defaultValue: clean.charAt(0).toUpperCase() + clean.slice(1) });
        }
        const fallback = {
            none: 'None',
            safe: 'Safe',
            questionable: 'Questionable',
            explicit: 'Explicit'
        };
        return fallback[clean] || 'None';
    },

    renderBadge(rating, options = {}) {
        const clean = this.normalize(rating);
        const abbr = this.abbr(clean);
        const fullLabel = this.label(clean);
        const extraClass = options.class ? ` ${options.class}` : '';
        return `<span class="tag rating-${clean} tag-text uppercase text-[10px] font-bold tracking-wider px-2 py-0.5 select-none${extraClass}" data-tag-rating="${clean}" title="${fullLabel}" aria-label="${fullLabel}">${abbr}</span>`;
    }
};

if (typeof window !== 'undefined') {
    window.TagRating = TagRating;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TagRating;
}
