// On the Swipe News page (127.0.0.1), tell the app that this extension is installed, so it stops suggesting it.
// Only sets an attribute; nothing is read from the page
document.documentElement.dataset.swipeNewsExtension = chrome.runtime.getManifest().version;
