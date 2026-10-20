document.addEventListener('DOMContentLoaded', async function() {
    const core = await import("/image-bench/js/core.js");
    onUiLoaded(core.init);
});

