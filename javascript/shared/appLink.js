/**
 * The dialog of the host page's Image Bench button without the openFromHostUI setting: Image Bench is started by
 * its own link (/image-bench/app), which loads the host UI in its iframe
 */

export const APP_URL = "/image-bench/app";

const DIALOG_ID = "image-bench-app-link-dialog";

const STYLE = `
  #${DIALOG_ID} {
    max-width: 460px; padding: 0; border: 1px solid #3f3f46; border-radius: 10px;
    background: #1c1c21; color: #e4e4e7; font: 14px/1.5 system-ui, sans-serif; box-shadow: 0 12px 40px #000a;
  }
  #${DIALOG_ID} > div { padding: 20px 24px; }
  #${DIALOG_ID}::backdrop { background: #0008; }
  #${DIALOG_ID} h2 { margin: 0 0 10px; font-size: 18px; font-weight: 600; color: inherit; }
  #${DIALOG_ID} p { margin: 0 0 12px; color: #b4b4bc; }
  #${DIALOG_ID} a.image-bench-app-link {
    display: block; margin: 0 0 14px; padding: 10px 12px; border-radius: 8px; background: #f97316; color: #1a0b00;
    font-weight: 600; text-align: center; text-decoration: none; word-break: break-all;
  }
  #${DIALOG_ID} a.image-bench-app-link:hover { background: #fb8a3c; }
  #${DIALOG_ID} .image-bench-dialog-buttons { display: flex; justify-content: flex-end; margin-top: 16px; }
  #${DIALOG_ID} button {
    font: inherit; padding: 6px 18px; border: 1px solid #52525b; border-radius: 6px; background: #27272a;
    color: inherit; cursor: pointer;
  }
  #${DIALOG_ID} button:hover { background: #3f3f46; }
`;

function escapeHtml(text) {
    return text.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
}

/**
 * Show the link to Image Bench in a modal dialog of the host page
 * @param {string} hostName - "WebUI" or "ComfyUI"
 */
export function showAppLinkDialog(hostName) {
    document.getElementById(DIALOG_ID)?.remove();

    if (!document.getElementById(`${DIALOG_ID}-style`)) {
        const style = document.createElement("style");
        style.id = `${DIALOG_ID}-style`;
        style.textContent = STYLE;
        document.head.append(style);
    }

    const url = new URL(APP_URL, location.href).href;
    const host = escapeHtml(hostName);

    const dialog = document.createElement("dialog");
    dialog.id = DIALOG_ID;
    dialog.innerHTML = `<div>
      <h2>🔬 Image Bench</h2>
      <p>Image Bench is started by its own link, which loads the ${host} interface inside it in the background.
        Open it with the link below:</p>
      <a class="image-bench-app-link" href="${escapeHtml(url)}">${escapeHtml(url)}</a>
      <p>Bookmark this link to start Image Bench from now on: drag it to the bookmarks bar, or press Ctrl+D once
        Image Bench is open.</p>
      <p>To open Image Bench with this button instead, turn on <i>Open Image Bench from the ${host} interface</i>
        in its Settings tab.</p>
      <div class="image-bench-dialog-buttons"><button type="button">Close</button></div>
    </div>`;

    // A click replaces the host UI in this tab, which Image Bench then loads in its iframe, also with Ctrl or Shift.
    // A middle click keeps the browser default. Dragging it to the bookmarks still works
    const link = dialog.querySelector("a");
    link.addEventListener("click", e => {
        e.preventDefault();
        location.assign(url);
    });

    dialog.querySelector("button").addEventListener("click", () => dialog.close());
    // Only a click on the backdrop targets the dialog itself, its content is in the padded div
    dialog.addEventListener("click", e => e.target === dialog && dialog.close());
    dialog.addEventListener("close", () => dialog.remove());

    document.body.append(dialog);
    dialog.showModal();
}
