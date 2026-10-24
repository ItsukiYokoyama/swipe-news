// Close the article tab and switch to the open Swipe News tab (or open one)
const APP_URL = "http://127.0.0.1:7870/";

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type === "back-to-swipe-news" && sender.tab) back(sender.tab);
});
// Clicking the toolbar icon also goes back
chrome.action.onClicked.addListener(tab => back(tab));

async function back(fromTab) {
  // The app may run on 7871+ when 7870 is taken, so find it by title
  const tabs = await chrome.tabs.query({ url: "http://127.0.0.1/*" });
  const app = tabs.find(t => t.title === "Swipe News") || tabs[0];
  if (app) {
    await chrome.tabs.update(app.id, { active: true });
    await chrome.windows.update(app.windowId, { focused: true });
  } else {
    await chrome.tabs.create({ url: APP_URL, windowId: fromTab.windowId });
  }
  if (fromTab.id !== app?.id) await chrome.tabs.remove(fromTab.id);
}
