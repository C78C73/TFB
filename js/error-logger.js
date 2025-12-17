// Simple Error Logging System
const ERROR_LOG_KEY = 'tfb_error_log';
const MAX_LOG_ENTRIES = 50;

// Error logger class
class ErrorLogger {
    constructor() {
        this.setupGlobalErrorHandler();
    }

    setupGlobalErrorHandler() {
        // Catch unhandled errors
        window.addEventListener('error', (event) => {
            this.logError({
                type: 'JavaScript Error',
                message: event.message,
                source: event.filename,
                line: event.lineno,
                column: event.colno,
                stack: event.error?.stack
            });
        });

        // Catch unhandled promise rejections
        window.addEventListener('unhandledrejection', (event) => {
            this.logError({
                type: 'Unhandled Promise Rejection',
                message: event.reason?.message || event.reason,
                stack: event.reason?.stack
            });
        });
    }

    logError(errorInfo) {
        const timestamp = new Date().toISOString();
        const errorEntry = {
            timestamp,
            page: window.location.pathname,
            ...errorInfo
        };

        // Log to console
        console.error('🚨 TFB Error:', errorEntry);

        // Save to localStorage for debugging
        this.saveToLocalStorage(errorEntry);
    }

    saveToLocalStorage(errorEntry) {
        try {
            let errorLog = JSON.parse(localStorage.getItem(ERROR_LOG_KEY) || '[]');
            errorLog.unshift(errorEntry);
            
            if (errorLog.length > MAX_LOG_ENTRIES) {
                errorLog = errorLog.slice(0, MAX_LOG_ENTRIES);
            }
            
            localStorage.setItem(ERROR_LOG_KEY, JSON.stringify(errorLog));
        } catch (e) {
            console.error('Failed to save error log:', e);
        }
    }

    getErrors() {
        try {
            return JSON.parse(localStorage.getItem(ERROR_LOG_KEY) || '[]');
        } catch (e) {
            return [];
        }
    }

    clearErrors() {
        localStorage.removeItem(ERROR_LOG_KEY);
        console.log('Error log cleared');
    }
}

// Initialize error logger
const errorLogger = new ErrorLogger();

// Expose to window for debugging in console
window.errorLogger = errorLogger;

console.log('%c🛡️ Error logging active', 'color: #2ecc71; font-weight: bold;');
