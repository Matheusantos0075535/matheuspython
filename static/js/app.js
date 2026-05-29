// ── Tab switching (login / register) ──────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', (i === 0 && tab === 'login') || (i === 1 && tab === 'register'));
  });
  const loginEl    = document.getElementById('login-form');
  const registerEl = document.getElementById('register-form');
  if (!loginEl || !registerEl) return;
  loginEl.classList.toggle('hidden', tab !== 'login');
  registerEl.classList.toggle('hidden', tab !== 'register');
}

// ── Radio visual state ─────────────────────────────────────────────────────
function updateRadio(input) {
  document.querySelectorAll('.radio-option').forEach(el => {
    el.classList.remove('selected-clean', 'selected-relapse');
  });
  const label = input.closest('.radio-option');
  if (!label) return;
  if (input.value === 'no')  label.classList.add('selected-clean');
  if (input.value === 'yes') label.classList.add('selected-relapse');
}

// Initialise radio styles on page load
document.addEventListener('DOMContentLoaded', () => {
  const checked = document.querySelector('.radio-option input[type="radio"]:checked');
  if (checked) updateRadio(checked);

  // Auto-dismiss alerts after 6 s
  document.querySelectorAll('.alert').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity 0.5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 6000);
  });
});
