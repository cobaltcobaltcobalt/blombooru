// Core functionality
class Blombooru {
    constructor() {
        this.isAdminMode = this.getCookie('admin_mode') === 'true';
        this.isAuthenticated = !!this.getCookie('admin_token');
        this.currentPage = 1;
        this.isLoading = false;
        this.hasMore = true;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.updateUI();
        
        // Load settings from cookie
        const savedRating = this.getCookie('rating_filter');
        if (savedRating) {
            this.setRatingFilter(savedRating);
        }
    }
    
    setupEventListeners() {
        // Admin mode toggle
        const adminToggle = document.getElementById('admin-mode-toggle');
        if (adminToggle) {
            adminToggle.addEventListener('click', () => this.toggleAdminMode());
        }
        
        // Logout
        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => this.logout());
        }
        
        // Rating filter
        const ratingInputs = document.querySelectorAll('input[name="rating"]');
        ratingInputs.forEach(input => {
            input.addEventListener('change', (e) => {
                this.setRatingFilter(e.target.value);
                this.setCookie('rating_filter', e.target.value, 365);
            });
        });
        
        // Search form
        const searchForm = document.getElementById('search-form');
        if (searchForm) {
            searchForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.performSearch();
            });
        }
    }
    
    async toggleAdminMode() {
        if (!this.isAuthenticated) {
            window.location.href = '/admin';
            return;
        }
        
        const newMode = !this.isAdminMode;
        
        try {
            const response = await fetch('/api/admin/toggle-admin-mode?enabled=' + newMode, {
                method: 'POST'
            });
            
            if (response.ok) {
                this.isAdminMode = newMode;
                this.updateUI();
                location.reload();
            }
        } catch (error) {
            console.error('Error toggling admin mode:', error);
        }
    }
    
    async logout() {
        try {
            await fetch('/api/admin/logout', { method: 'POST' });
            window.location.href = '/';
        } catch (error) {
            console.error('Error logging out:', error);
        }
    }
    
    updateUI() {
        const body = document.body;
        
        if (this.isAdminMode) {
            body.classList.add('admin-mode');
        } else {
            body.classList.remove('admin-mode');
        }
        
        // Update admin mode button
        const adminToggle = document.getElementById('admin-mode-toggle');
        if (adminToggle) {
            adminToggle.textContent = this.isAdminMode ? 'Exit Admin Mode' : 'Admin Mode';
        }
    }
    
    setRatingFilter(rating) {
        const input = document.querySelector(`input[name="rating"][value="${rating}"]`);
        if (input) {
            input.checked = true;
        }
    }
    
    performSearch() {
        const searchInput = document.getElementById('search-input');
        const query = searchInput.value;
        
        if (query) {
            window.location.href = `/?q=${encodeURIComponent(query)}`;
        }
    }
    
    getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }
    
    setCookie(name, value, days) {
        const expires = new Date();
        expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000);
        document.cookie = `${name}=${value};expires=${expires.toUTCString()};path=/;SameSite=Lax`;
    }
    
    async apiCall(endpoint, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            }
        };
        
        const response = await fetch(endpoint, { ...defaultOptions, ...options });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API call failed');
        }
        
        return response.json();
    }
}

// Initialize app
const app = new Blombooru();
