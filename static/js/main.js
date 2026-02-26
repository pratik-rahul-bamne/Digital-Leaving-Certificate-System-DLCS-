/* College LC System — Client-side JS helpers (Bootstrap 5) */

document.addEventListener('DOMContentLoaded', () => {

  // 1. Auto-dismiss flash alerts via Toasts / Alerts
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach((alertEl, index) => {
    // Automatically hide it after 5 seconds + staggering
    setTimeout(() => {
      const bsAlert = new bootstrap.Alert(alertEl);
      bsAlert.close();
    }, 5000 + (index * 500));
  });

  // 2. Loading state for generic forms
  document.querySelectorAll('form').forEach(form => {
    // Exclude search forms or forms explicitly marked with nolaser
    if (form.method.toLowerCase() === 'get' || form.classList.contains('no-spin')) return;

    form.addEventListener('submit', function (e) {
      // Check HTML5 validity
      if (!this.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.add('was-validated');
        return;
      }

      const button = this.querySelector('button[type="submit"]');
      if (button && !button.hasAttribute('data-no-load')) {
        // If it's the generate PDF form, use a special visual
        if (this.classList.contains('generate-pdf-form')) {
          const origHtml = button.innerHTML;
          button.disabled = true;
          button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Generating PDF...';
          setTimeout(() => { button.disabled = false; button.innerHTML = origHtml; }, 8000);
        } else {
          const origHtml = button.innerHTML;
          button.disabled = true;
          button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Wait...';
          setTimeout(() => { button.disabled = false; button.innerHTML = origHtml; }, 5000);
        }
      }
    });
  });

  // 3. Highlight active nav link by current path for sidebar
  const path = window.location.pathname;
  document.querySelectorAll('#sidebar-wrapper .list-group-item').forEach(link => {
    const href = link.getAttribute('href') || '';
    // Exact match or active-nav class is already controlled via Jinja, 
    // but as a fallback/enhancement:
    if (href !== '/' && path.startsWith(href) && !link.classList.contains('active-nav')) {
      link.classList.add('active-nav');
    }
  });

});
