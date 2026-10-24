// On an article page, when ↑ is pressed while holding ← and → (or ← and → are held for 0.7 s), notify the background script.
// Some keyboards can't register three keys at once (ghosting), so holding two also works.
// Only which arrow keys are down is observed; the page content is never read
const HOLD_MS = 700;
const down = new Set();
let timer = null, badge = null;

function showBadge() {
  if (badge) return;
  badge = document.createElement("div");
  badge.textContent = "↑ か、そのまま長押しで Swipe News に戻る";
  Object.assign(badge.style, {
    position: "fixed", left: "50%", bottom: "32px", transform: "translateX(-50%)", zIndex: 2147483647,
    background: "rgba(0,0,0,.85)", color: "#fff", font: "bold 14px sans-serif", padding: "10px 16px",
    borderRadius: "999px", pointerEvents: "none",
  });
  document.documentElement.append(badge);
}

function reset() {
  clearTimeout(timer);
  timer = null;
  badge?.remove();
  badge = null;
}

function back() {
  reset();
  down.clear();
  chrome.runtime.sendMessage({ type: "back-to-swipe-news" });
}

addEventListener("keydown", e => {
  if (!e.key.startsWith("Arrow")) return;
  down.add(e.key);
  if (!(down.has("ArrowLeft") && down.has("ArrowRight"))) return;
  e.preventDefault();  // Keep the page from scrolling sideways while the keys are held
  e.stopPropagation();
  if (e.key === "ArrowUp") return back();
  showBadge();
  if (!timer) timer = setTimeout(back, HOLD_MS);
}, true);
addEventListener("keyup", e => {
  down.delete(e.key);
  if (!(down.has("ArrowLeft") && down.has("ArrowRight"))) reset();
}, true);
addEventListener("blur", () => { down.clear(); reset(); });
