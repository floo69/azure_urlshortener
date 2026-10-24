// Single setting: Function base URL, no trailing slash.
// Local default matches host.json LocalHttpPort in local.settings.example.json.
const API_BASE_URL = "https://urlshort-api-dev-hfaqfha4edftdjck.centralindia-01.azurewebsites.net";

const form = document.getElementById("shorten-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
const shortUrlEl = document.getElementById("short-url");
const copyBtn = document.getElementById("copy-btn");
const copyStatus = document.getElementById("copy-status");

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = false;
  resultEl.hidden = true;
}

function showResult(shortUrl) {
  errorEl.hidden = true;
  shortUrlEl.value = shortUrl;
  resultEl.hidden = false;
  copyStatus.hidden = true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  errorEl.hidden = true;

  try {
    const response = await fetch(`${API_BASE_URL}/links`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: urlInput.value.trim() }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showError(data.error || `Request failed (${response.status})`);
      return;
    }
    showResult(data.short_url);
  } catch (err) {
    showError(
      "Could not reach the API. Check API_BASE_URL in app.js and CORS_ALLOWED_ORIGIN on the Function."
    );
  } finally {
    submitBtn.disabled = false;
  }
});

copyBtn.addEventListener("click", async () => {
  const value = shortUrlEl.value;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    shortUrlEl.select();
    document.execCommand("copy");
  }
  copyStatus.textContent = "Copied.";
  copyStatus.hidden = false;
});
