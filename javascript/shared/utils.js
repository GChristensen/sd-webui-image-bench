
export function sleep(ms) {
   return new Promise(rs => setTimeout(rs, ms));
}

export function createGenerationId() {
   const dateTimeString = getDateTimeString();
   return `gen_${dateTimeString}`;
}

function getDateTimeString()  {
   const now = new Date();
   const year = now.getFullYear();
   const month = String(now.getMonth() + 1).padStart(2, '0');
   const day = String(now.getDate()).padStart(2, '0');

   const hours = String(now.getHours()).padStart(2, '0');
   const minutes = String(now.getMinutes()).padStart(2, '0');
   const seconds = String(now.getSeconds()).padStart(2, '0');
   //const milliseconds = String(now.getMilliseconds()).padStart(3, '0');

   const dateString = `${year}${month}${day}`;
   const timeString = `${hours}${minutes}${seconds}`;
   return `${dateString}_${timeString}`;
}

export async function loadAppConfig() {
    return await fetch('/image-bench/config.json?' + (+new Date()))
        .then(response => response.json())
        .catch(error => console.error('[state]: Error getting JSON file:', error));
}