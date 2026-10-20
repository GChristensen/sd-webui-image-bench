import {SELECTORS} from "./adapters/selectors.js";

export function setStyle(elements, style) {
    if (elements instanceof NodeList) {
        elements = Array.from(elements);
    } else if (elements instanceof Node){
        elements = [elements];
    } else {
        return;
    }
    elements.forEach(element => {
        for (let key in style) {
            if (style.hasOwnProperty(key)) {
                element.style[key] = style[key];
            }
        }
    });
}

export function create(type, props, style) {
    const element = document.createElement(type);
    if (props) {
        for (let key in props) {
            if (props.hasOwnProperty(key)) {
                element[key] = props[key];
            }
        }
    }
    if (style) {
        setStyle(element, style);
    }
    return element;
}

export function createButton(text, onclick) {
    const btn = document.createElement('button');
    btn.innerHTML = text;
    btn.onclick = onclick || function () {};
    btn.className = 'gr-button gr-button-lg gr-button-primary';
    return btn;
}

export function createHeaderButton(title, text, style, action, after) {
    let quickSettings = gradioApp().getElementById(SELECTORS.QUICK_SETTINGS);
    let className = quickSettings.querySelector('button').className;

    const button = create('button', {
        title: title,
        innerHTML: text,
        className: className,
    }, style);

    if (action) {
        button.addEventListener('click', action);
    }

    if (after)
        after.after(button)
    else
        quickSettings.appendChild(button);

    return button;
}